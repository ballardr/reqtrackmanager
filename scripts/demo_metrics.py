#!/usr/bin/env python3
"""
Module: demo_metrics

Bundles the usage metrics a demonstration stack has collected, for a developer to review, and opens a bundle again.

Responsibilities:
- `export`: write one `.tar.gz` holding a Prometheus TSDB snapshot, `series.jsonl` (every series over the range at a
  fixed step), `manifest.json` and `README.txt`.
- `view`: start a throwaway Prometheus on a bundle's snapshot, on loopback port 9091, removed on exit.
- `purge`: stop the demonstration Prometheus and remove its volume (the only way the collected metrics are removed;
  a demonstration reset leaves them alone).
- Refuse to write a bundle whose series carry a label name or value outside the allow-list (`check_labels`), so a
  record title, code, e-mail address or search text can never leave the host through it.

Design decisions:
- Host-side and standard library only: it is run through `scripts/demo.sh` on the demonstration host, talks to
  Prometheus on `127.0.0.1` and to the stack through `docker compose`. The application has no download route for it
  (a demonstration-only code path in a product that also runs in production) and no use-metric extension point.
- The bundle holds metrics only. Logs, traces, configuration, environment values and the sign-in details message are
  not read. The manifest carries counts per database table (no content) and times.
- Every sample time is a past instant in UTC. The daily reset is a future wall-clock time with its IANA zone, reported
  as configured and as the next resolved UTC instant; past resets come from the history the reset command appends.
- `series.jsonl` omits a series that is constant zero (no information, and it dominates a stack that pre-creates
  series); the manifest counts how many were left out. The snapshot keeps everything at full resolution.

External dependencies: `docker compose` (in `tests/container`), the Prometheus HTTP API and its admin API.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_DIR = ROOT / "tests" / "container"
BUNDLE_FORMAT = 1
PROM_URL = os.environ.get("DEMO_PROMETHEUS_URL", "http://127.0.0.1:9090")
VIEW_PORT = 9091
PROM_IMAGE = "prom/prometheus:v2.54.1"
PROFILE = "demo-metrics"
SERVICE = "prometheus"
VOLUME = "reqtrack_demo_metrics"
DEFAULT_SINCE = "30d"
MAX_POINTS = 2000
"""Target points per series: the step grows with the range so a 30-day bundle stays shareable."""
WINDOW_POINTS = 1000
"""Points per `query_range` call, well under Prometheus's 11,000 limit and its sample cap."""
HISTORY_FILE = "reqtrack-demo-resets.jsonl"
SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

LABEL_RULES: dict[str, re.Pattern[str]] = {
    "__name__": re.compile(r"^[a-z_:][a-z0-9_:]{0,127}$"),
    "method": re.compile(r"^[A-Z]{3,10}$"),
    "path": re.compile(r"^(unmatched|/[A-Za-z0-9_./{}-]{0,255})$"),
    "status_code": re.compile(r"^\d{3}$"),
    "code": re.compile(r"^\d{3}$"),
    "server": re.compile(r"^[a-z0-9_]{1,40}$"),
    "handler": re.compile(r"^[a-z_]{1,32}$"),
    "le": re.compile(r"^(\+Inf|\d+(\.\d+)?)$"),
    "operation": re.compile(r"^(select|insert|update|delete|other)$"),
    "result": re.compile(r"^[a-z_]{1,32}$"),
    "state": re.compile(r"^[a-z_]{1,32}$"),
    "pid": re.compile(r"^\d{1,10}$"),
    "job": re.compile(r"^[A-Za-z0-9_.:-]{1,64}$"),
    "instance": re.compile(r"^[A-Za-z0-9_.:-]{1,64}$"),
}
"""The label names a bundle may carry and the shape each value must have. A route template contains no path value."""
UUID_IN_PATH = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

Runner = Callable[..., str]
"""`run(command, optional=False)`: runs a command in `tests/container`; an `optional` read that fails returns an empty string."""

GLOSSARY = """\
http_requests_total{method,path,status_code}      requests; path is the route template, never a record value
http_request_duration_seconds_{bucket,sum,count}  request latency per route template and method
caddy_http_requests_total{server,handler,code,method}   the HTTPS proxy's requests by status code (no host or path)
requests_shed_total                               requests refused with 503 because no slot freed in time
requirements_*_total, change_requests_*_total     lifecycle transitions (created, updated, approved, completed, archived)
login_attempts_total{result}                      sign-in outcomes
db_statements_total{operation}                    database statements by operation
db_pool_connections{state}, worker_resident_memory_bytes   pool and memory gauges per worker (pid)
storage_write_healthy                             1 while file storage accepts writes
up, scrape_*                                      Prometheus's own view of the scrape
"""


class ScrubError(RuntimeError):
    """A series carries a label name or value outside the allow-list; nothing is written."""


class MetricsError(RuntimeError):
    """The metrics cannot be read or bundled (Prometheus unreachable, no stack, bad option)."""


# ---- pure helpers -------------------------------------------------------------------------------------------


def parse_since(text: str) -> timedelta:
    """Parses a duration such as `90m`, `7d` or `2w`.

    Args:
        text: A whole number followed by one of s, m, h, d, w.

    Returns:
        The duration.

    Raises:
        MetricsError: If the text is not of that shape or is zero.
    """
    match = re.fullmatch(r"(\d{1,5})([smhdw])", text.strip())
    if not match or int(match.group(1)) == 0:
        raise MetricsError(f"Cannot read the duration '{text}'; use a number and s, m, h, d or w (for example 7d).")
    return timedelta(seconds=int(match.group(1)) * SECONDS[match.group(2)])


def choose_step(span: timedelta) -> int:
    """Returns the sample step in seconds (a multiple of 60) that keeps a series near `MAX_POINTS` points."""
    return max(60, math.ceil(span.total_seconds() / MAX_POINTS / 60) * 60)


def check_labels(labels: dict[str, str]) -> None:
    """Fails when a series' labels could carry something other than system behaviour.

    Args:
        labels: The series' label set including `__name__`.

    Raises:
        ScrubError: Naming the label (never its value) when the name is not allowed, the value does not have the
            shape the label is allowed, or a path holds an identifier.
    """
    for name, value in labels.items():
        rule = LABEL_RULES.get(name)
        if rule is None:
            raise ScrubError(f"Series label '{name}' is not on the allow-list; the bundle was not written.")
        if not rule.match(value) or (name == "path" and UUID_IN_PATH.search(value)):
            raise ScrubError(f"A value of label '{name}' does not have the allowed shape; the bundle was not written.")


def is_constant_zero(values: list[list]) -> bool:
    """True when every sample of a series is zero."""
    return all(float(v) == 0.0 for _, v in values)


def resolve_next_reset(at: str, zone: str, now: datetime) -> dict:
    """The configured daily reset and its next occurrence as a UTC instant.

    The reset is a future wall-clock time kept with its IANA zone; it is resolved only here, at the moment of use.

    Args:
        at: `HH:MM` local time.
        zone: IANA zone name.
        now: The current instant (timezone-aware).

    Returns:
        `{"at", "timezone", "next_utc"}`.

    Raises:
        MetricsError: If the time or zone is invalid.
    """
    try:
        hour, minute = (int(part) for part in at.split(":"))
        tz = ZoneInfo(zone)
        local_now = now.astimezone(tz)
        candidate = datetime(local_now.year, local_now.month, local_now.day, hour, minute, tzinfo=tz)
        if candidate <= local_now:
            candidate = datetime.combine(local_now.date() + timedelta(days=1), candidate.timetz().replace(tzinfo=None), tzinfo=tz)
    except (ValueError, KeyError) as exc:
        raise MetricsError(f"Cannot read the reset schedule ({at} {zone}).") from exc
    return {"at": at, "timezone": zone, "next_utc": candidate.astimezone(UTC).isoformat().replace("+00:00", "Z")}


def parse_history(text: str) -> list[dict]:
    """Reads the reset history file (one JSON object per line), skipping a line that is not valid."""
    events = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and {"event", "at"} <= item.keys():
            events.append({"event": str(item["event"]), "at": str(item["at"]), "succeeded": item.get("succeeded")})
    return events


# ---- Prometheus access --------------------------------------------------------------------------------------


class Prometheus:
    """A small client for the parts of the Prometheus HTTP API the bundle needs."""

    def __init__(self, base_url: str = PROM_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, str] | None = None, method: str = "GET") -> dict:
        query = "?" + urllib.parse.urlencode(params) if params else ""
        request = urllib.request.Request(f"{self.base_url}{path}{query}", method=method)  # noqa: S310  (loopback URL)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                return json.load(response)
        except (OSError, ValueError) as exc:
            raise MetricsError(
                f"Cannot read Prometheus at {self.base_url} ({type(exc).__name__}). Is the demonstration running with metrics?"
            ) from exc

    def metric_names(self) -> list[str]:
        """Every metric name Prometheus holds."""
        return list(self._get("/api/v1/label/__name__/values")["data"])

    def query_range(self, query: str, start: datetime, end: datetime, step: int) -> list[dict]:
        """Runs one range query; returns Prometheus's `result` list (`metric`, `values`)."""
        params = {"query": query, "start": f"{start.timestamp():.3f}", "end": f"{end.timestamp():.3f}", "step": str(step)}
        data = self._get("/api/v1/query_range", params)
        return list(data["data"]["result"])

    def snapshot(self) -> str:
        """Takes a TSDB snapshot (admin API) and returns its directory name."""
        return str(self._get("/api/v1/admin/tsdb/snapshot", method="POST")["data"]["name"])


def collect_series(prom: Prometheus, start: datetime, end: datetime, step: int) -> tuple[list[dict], int]:
    """Reads every series over the range, merged across query windows, with constant-zero series left out.

    Args:
        prom: The Prometheus client.
        start: Range start (UTC).
        end: Range end (UTC).
        step: Sample step in seconds.

    Returns:
        The series as `{"labels", "values"}` (values are `[unix seconds, float]`) and how many were left out.

    Raises:
        ScrubError: If any series fails `check_labels`.
        MetricsError: If Prometheus cannot be read.
    """
    window = timedelta(seconds=step * WINDOW_POINTS)
    merged: dict[tuple, dict] = {}
    for name in prom.metric_names():
        cursor = start
        while cursor < end:
            upper = min(cursor + window, end)
            for item in prom.query_range(f'{{__name__="{name}"}}', cursor, upper, step):
                labels = dict(item["metric"])
                check_labels(labels)
                entry = merged.setdefault(tuple(sorted(labels.items())), {"labels": labels, "values": []})
                known = entry["values"][-1][0] if entry["values"] else None
                entry["values"] += [[float(t), float(v)] for t, v in item["values"] if known is None or float(t) > known]
            cursor = upper + timedelta(seconds=step)
    kept = [series for series in merged.values() if series["values"] and not is_constant_zero(series["values"])]
    return kept, len(merged) - len(kept)


# ---- the bundle ---------------------------------------------------------------------------------------------


def readme_text(manifest: dict, with_snapshot: bool) -> str:
    """The README.txt in the bundle: how to open it and what the metric names mean."""
    snapshot = (
        "Open the snapshot in Prometheus (no setup beyond Docker):\n"
        "    scripts/demo.sh --view-metrics <this bundle>.tar.gz\n"
        "or by hand, from the extracted folder:\n"
        f"    docker run --rm -p 127.0.0.1:{VIEW_PORT}:9090 --user \"$(id -u)\" -v \"$PWD/snapshot:/prometheus\" {PROM_IMAGE} \\\n"
        "        --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=3650d\n"
        if with_snapshot else "This bundle was written without a snapshot (--no-snapshot); series.jsonl is the only data.\n"
    )
    return (
        "ReqTrackManager demonstration usage metrics\n"
        "===========================================\n\n"
        f"Range: {manifest['range']['start']} to {manifest['range']['end']} (UTC), step {manifest['range']['step_seconds']} s in series.jsonl.\n"
        "The metrics describe system behaviour (routes, latency, status, counts). They do not say who did what or why;\n"
        "that is what the session recordings are for, matched by time only.\n\n"
        f"{snapshot}\n"
        "series.jsonl, one series per line: {\"labels\": {...}, \"values\": [[unix_seconds, value], ...]}\n"
        "    jq -r 'select(.labels.__name__==\"http_requests_total\") | [.labels.path, .values[-1][1]] | @tsv' series.jsonl | sort -k2 -n -r | head\n"
        "    python3 -c 'import json,sys; [print(json.loads(l)[\"labels\"][\"__name__\"]) for l in open(\"series.jsonl\")]' | sort | uniq -c\n\n"
        "manifest.json lists the application version, the range, the reset times (a counter falls to zero at each reset)\n"
        "and the number of rows per database table at export time.\n\n"
        "Metric names\n------------\n"
        f"{GLOSSARY}"
    )


def build_manifest(*, version: str, start: datetime, end: datetime, step: int, scrape_interval: str, series_count: int,
                   omitted: int, resets: list[dict], schedule: dict | None, clarity: bool | None, table_counts: dict[str, int],
                   with_snapshot: bool, exported: datetime) -> dict:
    """The bundle's `manifest.json` content (times and counts only)."""
    def stamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "bundle_format": BUNDLE_FORMAT,
        "application_version": version,
        "exported_at": stamp(exported),
        "range": {"start": stamp(start), "end": stamp(end), "step_seconds": step},
        "scrape_interval": scrape_interval,
        "series": {"written": series_count, "omitted_constant_zero": omitted},
        "snapshot_included": with_snapshot,
        "resets": resets,
        "reset_schedule": schedule,
        "session_recording_enabled": clarity,
        "table_row_counts": table_counts,
    }


def write_bundle(target: Path, *, series: list[dict], manifest: dict, snapshot_dir: Path | None) -> int:
    """Writes the archive and returns its size in bytes.

    Args:
        target: The `.tar.gz` path.
        series: The series to write.
        manifest: The manifest content.
        snapshot_dir: The copied TSDB snapshot, or None.

    Returns:
        The archive size.
    """
    base = target.name.removesuffix(".tar.gz")
    with tempfile.TemporaryDirectory(prefix="demo-metrics-") as work:
        folder = Path(work) / base
        folder.mkdir()
        with open(folder / "series.jsonl", "w", encoding="utf-8") as out:
            for item in series:
                out.write(json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n")
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (folder / "README.txt").write_text(readme_text(manifest, snapshot_dir is not None), encoding="utf-8")
        if snapshot_dir is not None:
            shutil.copytree(snapshot_dir, folder / "snapshot")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as archive:
            archive.add(folder, arcname=base)
    return target.stat().st_size


def export_bundle(prom: Prometheus, run: Runner, target: Path, *, since: timedelta, with_snapshot: bool = True,
                  now: datetime | None = None, environment: dict[str, str] | None = None) -> dict:
    """Reads the metrics, checks them and writes the bundle.

    Args:
        prom: The Prometheus client.
        run: Runs a command in `tests/container` and returns its standard output (raises `MetricsError`).
        target: The archive path.
        since: How far back to read.
        with_snapshot: Whether to include the TSDB snapshot.
        now: The current instant (default: now, UTC).
        environment: Variables for the reset schedule (`DEMO_RESET_AT`, `DEMO_RESET_TZ`).

    Returns:
        The manifest written, plus `bytes` (the archive size).

    Raises:
        ScrubError: If a series fails the allow-list; no file is written.
        MetricsError: If Prometheus or the stack cannot be read.
    """
    now = now or datetime.now(UTC)
    env = environment if environment is not None else dict(os.environ)
    end, start = now, now - since
    step = choose_step(since)
    series, omitted = collect_series(prom, start, end, step)
    snapshot_dir = None
    work = Path(tempfile.mkdtemp(prefix="demo-snapshot-"))
    try:
        if with_snapshot:
            name = prom.snapshot()
            run(["docker", "compose", "--profile", PROFILE, "cp", f"{SERVICE}:/prometheus/snapshots/{name}", str(work / "snapshot")])
            run(["docker", "compose", "--profile", PROFILE, "exec", "-T", SERVICE, "rm", "-rf", f"/prometheus/snapshots/{name}"])
            snapshot_dir = work / "snapshot"
        counts = json.loads(run(["docker", "compose", "exec", "-T", "backend", "python", "scripts/demo_table_counts.py"]) or "{}")
        history = parse_history(run(["docker", "compose", "exec", "-T", "backend", "cat", f"/demo/status/{HISTORY_FILE}"], optional=True))
        version = run(["docker", "compose", "exec", "-T", "backend", "printenv", "APP_VERSION"]).strip() or "dev"
        clarity_text = run(["docker", "compose", "exec", "-T", "frontend", "printenv", "CLARITY_PROJECT_ID"], optional=True)
        schedule = resolve_next_reset(env.get("DEMO_RESET_AT", "00:00") or "00:00", env.get("DEMO_RESET_TZ", "UTC") or "UTC", now)
        manifest = build_manifest(
            version=version, start=start, end=end, step=step, scrape_interval="15s", series_count=len(series), omitted=omitted,
            resets=[e for e in history if _within(e["at"], start)], schedule=schedule, clarity=bool(clarity_text.strip()),
            table_counts=counts, with_snapshot=with_snapshot, exported=now,
        )
        size = write_bundle(target, series=series, manifest=manifest, snapshot_dir=snapshot_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {**manifest, "bytes": size}


def _within(stamp: str, start: datetime) -> bool:
    """True when an ISO instant is at or after `start` (an unreadable one is kept)."""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= start
    except ValueError:
        return True


# ---- commands -----------------------------------------------------------------------------------------------


def run_compose(command: list[str], optional: bool = False) -> str:
    """Runs a command in `tests/container`.

    Args:
        command: The command and arguments.
        optional: True for a read that may legitimately fail (a missing history file, an unset variable): a failure
            returns an empty string.

    Returns:
        Standard output.

    Raises:
        MetricsError: If `docker` is missing, or a required command fails.
    """
    try:
        done = subprocess.run(command, cwd=COMPOSE_DIR, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MetricsError(f"Cannot run docker ({type(exc).__name__}).") from exc
    if done.returncode != 0:
        if optional:
            return ""
        raise MetricsError(f"A docker command failed ({' '.join(command[:4])}…, exit {done.returncode}).")
    return done.stdout


def default_target(now: datetime) -> Path:
    """`demo-metrics-<UTC timestamp>.tar.gz` in the current directory."""
    return Path.cwd() / f"demo-metrics-{now.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"


def view(bundle: Path) -> int:
    """Starts a throwaway Prometheus on the bundle's snapshot (loopback port `VIEW_PORT`) until interrupted."""
    with tempfile.TemporaryDirectory(prefix="demo-view-") as work:
        with tarfile.open(bundle) as archive:
            archive.extractall(work, filter="data")
        snapshots = list(Path(work).glob("*/snapshot"))
        if not snapshots:
            print("demo-metrics: the bundle has no snapshot; read series.jsonl instead.", file=sys.stderr)
            return 2
        os.chmod(snapshots[0], 0o777)
        print(f"Prometheus on the bundle: http://127.0.0.1:{VIEW_PORT} (Ctrl-C to stop and remove it)")
        command = [
            "docker", "run", "--rm", "-p", f"127.0.0.1:{VIEW_PORT}:9090", "--user", f"{os.getuid()}", "-v", f"{snapshots[0]}:/prometheus",
            PROM_IMAGE, "--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus", "--storage.tsdb.retention.time=3650d",
            "--web.listen-address=[::]:9090",
        ]
        try:
            return subprocess.run(command, check=False).returncode
        except KeyboardInterrupt:
            return 0


def purge() -> int:
    """Stops the demonstration Prometheus and removes its volume."""
    run_compose(["docker", "compose", "--profile", PROFILE, "rm", "-sf", SERVICE])
    project = json.loads(run_compose(["docker", "compose", "--profile", PROFILE, "config", "--format", "json"]))["name"]
    names = subprocess.run(
        [
            "docker", "volume", "ls", "-q",
            "--filter", f"label=com.docker.compose.volume={VOLUME}", "--filter", f"label=com.docker.compose.project={project}",
        ],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    for name in names:
        subprocess.run(["docker", "volume", "rm", name], capture_output=True, check=False)
    print(f"Removed the collected demonstration metrics ({len(names)} volume).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The command line: `export [PATH]`, `view BUNDLE`, `purge`."""
    parser = argparse.ArgumentParser(description="Bundle, view or remove the demonstration usage metrics.")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="write a metrics bundle")
    export.add_argument("path", nargs="?", help="archive path (default demo-metrics-<UTC timestamp>.tar.gz here)")
    export.add_argument("--since", default=DEFAULT_SINCE, help=f"how far back, such as 7d (default {DEFAULT_SINCE})")
    export.add_argument("--no-snapshot", action="store_true", help="leave the TSDB snapshot out (series.jsonl only; much smaller)")
    show = sub.add_parser("view", help="open a bundle in a throwaway Prometheus")
    show.add_argument("bundle")
    sub.add_parser("purge", help="remove the collected metrics")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the exit status (0 done, 1 failed, 2 refused or invalid)."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "view":
            return view(Path(args.bundle))
        if args.command == "purge":
            return purge()
        now = datetime.now(UTC)
        target = Path(args.path) if args.path else default_target(now)
        result = export_bundle(Prometheus(), run_compose, target, since=parse_since(args.since), with_snapshot=not args.no_snapshot, now=now)
    except ScrubError as exc:
        print(f"demo-metrics: refused: {exc}", file=sys.stderr)
        return 2
    except MetricsError as exc:
        print(f"demo-metrics: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {target} ({result['bytes'] / 1_000_000:.1f} MB, {result['series']['written']} series).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
