"""Tests for the demonstration usage-metrics collection and bundle (`scripts/demo_metrics.py`, `scripts/demo.sh`).

The exporter is tested against a fixture Prometheus (a small HTTP server speaking the three API calls it uses) and a
fake command runner, so no Docker is needed. `demo.sh` is run with a fake `docker` on the path to see which Compose
profile and commands it uses. Skipped when the repository root is not visible (the backend container mounts only
backend/).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import tarfile
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "demo_metrics.py"
DEMO_SH = ROOT / "scripts" / "demo.sh"
COMPOSE = ROOT / "tests" / "container" / "docker-compose.yml"
PROM_CONFIG = ROOT / "observability" / "prometheus.demo.yml"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="repository checkout not available")


def _load():
    spec = importlib.util.spec_from_file_location("demo_metrics", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load() if SCRIPT.is_file() else None
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
SEEDED_STRINGS = ("DemoDemo123!", "demo.admin@example.com", "Solstice Robotics", "s3cret-db-password")


class FakePrometheus:
    """A loopback HTTP server holding a fixed set of series and answering the exporter's three API calls."""

    def __init__(self, series: list[dict]) -> None:
        self.series = series
        self.queries: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D102
                return

            def _send(self, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802, D102
                url = urlparse(self.path)
                if url.path == "/api/v1/label/__name__/values":
                    self._send({"status": "success", "data": sorted({s["metric"]["__name__"] for s in outer.series})})
                elif url.path == "/api/v1/query_range":
                    q = {k: v[0] for k, v in parse_qs(url.query).items()}
                    outer.queries.append(q)
                    name = re.search(r'__name__="([^"]+)"', q["query"]).group(1)
                    start, end, step = float(q["start"]), float(q["end"]), int(q["step"])
                    result = []
                    for item in outer.series:
                        if item["metric"]["__name__"] != name:
                            continue
                        points, t = [], start
                        while t <= end:
                            points.append([t, str(item["value"](t))])
                            t += step
                        result.append({"metric": item["metric"], "values": points})
                    self._send({"status": "success", "data": {"resultType": "matrix", "result": result}})
                else:
                    self.send_error(404)

            def do_POST(self):  # noqa: N802, D102
                self._send({"status": "success", "data": {"name": "20261109T120000Z-abc"}})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return tool.Prometheus(f"http://127.0.0.1:{self.server.server_port}")

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _series(name: str, value=lambda t: 1.0, **labels) -> dict:
    return {"metric": {"__name__": name, **labels}, "value": value}


def _runner(calls: list[list[str]]):
    def run(command: list[str], optional: bool = False) -> str:
        calls.append(command)
        if "cp" in command:
            target = Path(command[-1])
            target.mkdir(parents=True)
            (target / "01BLOCK").mkdir()
            (target / "01BLOCK" / "meta.json").write_text("{}")
            return ""
        if command[-1] == "scripts/demo_table_counts.py":
            return json.dumps({"requirements": 129, "users": 4})
        if command[-1].startswith("/demo/status/"):
            return (
                '{"event":"reset_started","at":"2026-11-09T00:00:00Z"}\n'
                '{"event":"reset_finished","at":"2026-11-09T00:06:00Z","succeeded":true}\nnot json\n'
                '{"event":"reset_started","at":"2026-10-01T00:00:00Z"}\n'
            )
        if command[-1] == "APP_VERSION":
            return "1.2.3\n"
        if command[-1] == "CLARITY_PROJECT_ID":
            return "abcdefghij\n"
        return ""

    return run


def _export(tmp_path: Path, series: list[dict], since: str = "7d", snapshot: bool = True, environment: dict | None = None):
    calls: list[list[str]] = []
    target = tmp_path / "bundle.tar.gz"
    with FakePrometheus(series) as prom:
        result = tool.export_bundle(
            prom, _runner(calls), target, since=tool.parse_since(since), with_snapshot=snapshot, now=NOW,
            environment=environment or {"DEMO_RESET_AT": "00:00", "DEMO_RESET_TZ": "UTC"},
        )
    return target, result, calls


def _extract(archive: Path, into: Path) -> Path:
    with tarfile.open(archive) as handle:
        handle.extractall(into, filter="data")
    [folder] = list(into.iterdir())
    return folder


GOOD = [
    _series(
        "http_requests_total", lambda t: t / 100, method="GET", path="/api/v1/projects/{project_id}", status_code="200",
        job="reqtrackmanager-backend", instance="backend:8000",
    ),
    _series("http_requests_total", method="OPTIONS", path="unmatched", status_code="200"),
    _series("db_statements_total", lambda t: 0.0, operation="select"),
    _series("login_attempts_total", result="success"),
    _series("db_pool_connections", state="idle", pid="12"),
    _series("http_request_duration_seconds_bucket", method="GET", path="/api/v1/auth/me", le="+Inf"),
    _series("requirements_created_total"),
]


# ---- the bundle ---------------------------------------------------------------------------------------------


def test_the_bundle_holds_a_snapshot_the_series_a_manifest_and_a_readme(tmp_path):
    archive, _, calls = _export(tmp_path, GOOD)
    folder = _extract(archive, tmp_path / "out")
    assert {p.name for p in folder.iterdir()} == {"README.txt", "manifest.json", "series.jsonl", "snapshot"}
    assert (folder / "snapshot" / "01BLOCK" / "meta.json").is_file()
    lines = [json.loads(line) for line in (folder / "series.jsonl").read_text().splitlines()]
    assert all(set(line) == {"labels", "values"} for line in lines)
    names = {line["labels"]["__name__"] for line in lines}
    assert "http_requests_total" in names and "requirements_created_total" in names
    assert any(c[-2:] == ["rm", "-rf"] or "rm" in c for c in calls), "the snapshot is removed from the container after the copy"
    assert "docker run" in (folder / "README.txt").read_text() and "http_requests_total" in (folder / "README.txt").read_text()


def test_the_manifest_gives_version_range_resets_schedule_and_counts_but_no_content(tmp_path):
    archive, result, _ = _export(tmp_path, GOOD, environment={"DEMO_RESET_AT": "09:00", "DEMO_RESET_TZ": "Australia/Sydney"})
    manifest = json.loads((_extract(archive, tmp_path / "out") / "manifest.json").read_text())
    assert manifest == {**{k: v for k, v in result.items() if k != "bytes"}}
    assert manifest["bundle_format"] == 1 and manifest["application_version"] == "1.2.3"
    assert manifest["range"] == {"start": "2026-11-02T12:00:00Z", "end": "2026-11-09T12:00:00Z", "step_seconds": tool.choose_step(timedelta(days=7))}
    assert manifest["table_row_counts"] == {"requirements": 129, "users": 4}
    assert manifest["session_recording_enabled"] is True
    # A reset before the range start and an unreadable line are left out; the cycle inside the range is kept.
    assert [(e["event"], e["at"]) for e in manifest["resets"]] == [
        ("reset_started", "2026-11-09T00:00:00Z"), ("reset_finished", "2026-11-09T00:06:00Z"),
    ]
    assert manifest["reset_schedule"] == {"at": "09:00", "timezone": "Australia/Sydney", "next_utc": "2026-11-09T22:00:00Z"}
    assert manifest["series"] == {"written": 6, "omitted_constant_zero": 1}


def test_since_narrows_the_range_and_the_series(tmp_path):
    wide, _, _ = _export(tmp_path / "a", GOOD, since="7d")
    narrow, _, _ = _export(tmp_path / "b", GOOD, since="1d")

    def first(path: Path) -> list[float]:
        folder = _extract(path, path.parent / "x")
        row = next(json.loads(line) for line in (folder / "series.jsonl").read_text().splitlines() if '"login_attempts_total"' in line)
        return [row["values"][0][0], row["values"][-1][0]]

    assert first(narrow)[0] > first(wide)[0] and first(narrow)[0] >= (NOW - timedelta(days=1)).timestamp()


def test_a_snapshot_can_be_left_out(tmp_path):
    archive, _, calls = _export(tmp_path, GOOD, snapshot=False)
    assert not (_extract(archive, tmp_path / "out") / "snapshot").exists()
    assert not any("cp" in c for c in calls)


def test_a_thirty_day_bundle_stays_small(tmp_path):
    many = [_series("http_requests_total", lambda t: t / 7, method="GET", path=f"/api/v1/route{n}/{{id}}", status_code="200") for n in range(100)]
    archive, _, _ = _export(tmp_path, many, since="30d", snapshot=False)
    lines = [json.loads(line) for line in (_extract(archive, tmp_path / "out") / "series.jsonl").read_text().splitlines()]
    assert len(lines) == 100 and all(len(line["values"]) <= tool.MAX_POINTS + tool.WINDOW_POINTS // 100 for line in lines)
    assert archive.stat().st_size < 5_000_000


def test_windows_do_not_duplicate_points_across_a_long_range(tmp_path):
    archive, _, _ = _export(tmp_path, [GOOD[0]], since="30d", snapshot=False)
    values = json.loads((_extract(archive, tmp_path / "out") / "series.jsonl").read_text().splitlines()[0])["values"]
    stamps = [v[0] for v in values]
    assert stamps == sorted(set(stamps))


# ---- the scrub check -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("labels", [
    {"__name__": "x_total", "email": "a@example.com"},
    {"__name__": "x_total", "path": "/api/v1/projects/0b7f3a52-6c1e-4f43-9a52-2f0c9a6a1e11"},
    {"__name__": "x_total", "path": "/api/v1/search?q=secret"},
    {"__name__": "x_total", "method": "GET", "status_code": "twenty"},
    {"__name__": "x_total", "operation": "drop table"},
])
def test_a_series_with_a_forbidden_label_name_or_value_refuses_the_bundle_naming_only_the_label(tmp_path, labels):
    series = GOOD + [{"metric": labels, "value": lambda t: 1.0}]
    with pytest.raises(tool.ScrubError) as raised:
        _export(tmp_path, series)
    assert not (tmp_path / "bundle.tar.gz").exists()
    message = str(raised.value)
    assert "a@example.com" not in message and "secret" not in message and "0b7f3a52" not in message


def test_the_allow_list_covers_every_label_the_application_defines():
    from prometheus_client import Counter, Gauge, Histogram

    from app import metrics

    defined = {name for value in vars(metrics).values() if isinstance(value, Counter | Gauge | Histogram) for name in value._labelnames}
    defined |= {"le", "pid", "job", "instance", "__name__"}
    assert defined <= set(tool.LABEL_RULES)


# ---- nothing beyond metrics ----------------------------------------------------------------------------------


def test_no_sign_in_detail_title_address_or_environment_value_is_in_the_archive(tmp_path):
    env = {
        "DEMO_RESET_AT": "00:00", "DEMO_RESET_TZ": "UTC", "DATABASE_URL": "postgresql://u:s3cret-db-password@db/x",
        "DEMO_CLARITY_PROJECT_ID": "abcdefghij",
    }
    archive, _, _ = _export(tmp_path, GOOD, environment=env)
    folder = _extract(archive, tmp_path / "out")
    text = "\n".join(p.read_text(errors="ignore") for p in folder.rglob("*") if p.is_file())
    for seeded in (*SEEDED_STRINGS, "abcdefghij"):
        assert seeded not in text
    assert "@" not in json.dumps(json.loads((folder / "manifest.json").read_text()))


# ---- pure helpers --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "seconds"), [("90m", 5400), ("7d", 604800), ("2w", 1209600), ("30s", 30)])
def test_a_duration_is_a_number_and_a_unit(text, seconds):
    assert tool.parse_since(text).total_seconds() == seconds


@pytest.mark.parametrize("text", ["", "7", "d", "0d", "-1d", "7 days", "1.5d"])
def test_an_unreadable_duration_is_refused(text):
    with pytest.raises(tool.MetricsError):
        tool.parse_since(text)


def test_the_step_grows_with_the_range():
    assert tool.choose_step(timedelta(hours=1)) == 60
    assert tool.choose_step(timedelta(days=30)) % 60 == 0
    assert timedelta(days=30).total_seconds() / tool.choose_step(timedelta(days=30)) <= tool.MAX_POINTS


@pytest.mark.parametrize(("at", "zone", "now", "expected"), [
    ("09:00", "Australia/Sydney", datetime(2026, 11, 9, 12, 0, tzinfo=UTC), "2026-11-09T22:00:00Z"),  # 09:00 at UTC+11 after the start of summer time
    ("09:00", "Australia/Sydney", datetime(2026, 6, 1, 12, 0, tzinfo=UTC), "2026-06-01T23:00:00Z"),  # the same wall-clock time at UTC+10
    ("23:00", "America/Los_Angeles", datetime(2026, 1, 10, 6, 0, tzinfo=UTC), "2026-01-10T07:00:00Z"),  # 23:00 at UTC-8
    ("09:00", "Australia/Sydney", datetime(2026, 3, 29, 12, 0, tzinfo=UTC), "2026-03-29T22:00:00Z"),  # a week before the change back
    ("09:00", "Australia/Sydney", datetime(2026, 4, 12, 12, 0, tzinfo=UTC), "2026-04-12T23:00:00Z"),  # a week after it
])
def test_the_next_reset_keeps_its_wall_clock_time_in_its_zone(at, zone, now, expected):
    assert tool.resolve_next_reset(at, zone, now)["next_utc"] == expected


def test_an_unusable_reset_schedule_is_refused():
    with pytest.raises(tool.MetricsError):
        tool.resolve_next_reset("nine", "UTC", NOW)
    with pytest.raises(tool.MetricsError):
        tool.resolve_next_reset("09:00", "Nowhere/Land", NOW)


# ---- the demonstration stack ---------------------------------------------------------------------------------


class _ComposeLoader(yaml.SafeLoader):
    """Reads the Compose file, whose `!reset` and `!override` tags are Compose's own."""


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_multi_constructor(_tag, lambda loader, suffix, node: None)


def _compose() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_ComposeLoader)  # noqa: S506  (a safe loader subclass)


def test_prometheus_is_a_demonstration_only_service_on_loopback_with_a_persistent_volume():
    compose = _compose()
    service = compose["services"]["prometheus"]
    assert service["profiles"] == ["demo-metrics"], "a plain `up` (tests, Playwright) never starts it"
    assert all(port.startswith("127.0.0.1:") for port in service["ports"])
    assert "--web.listen-address=[::]:9090" in service["command"]
    assert "--storage.tsdb.retention.time=30d" in service["command"]
    assert "127.0.0.1" in " ".join(service["healthcheck"]["test"]) and "localhost" not in " ".join(service["healthcheck"]["test"])
    assert "reqtrack_demo_metrics:/prometheus" in service["volumes"]
    assert "reqtrack_demo_metrics" in compose["volumes"]
    users = [
        name for name, other in compose["services"].items()
        if any(str(v).startswith("reqtrack_demo_metrics:") for v in other.get("volumes", []))
    ]
    assert users == ["prometheus"]


def test_the_demonstration_prometheus_scrapes_the_backend_only_with_no_alert_rules():
    config = yaml.safe_load(PROM_CONFIG.read_text())
    assert [job["job_name"] for job in config["scrape_configs"]] == ["reqtrackmanager-backend"]
    assert config["scrape_configs"][0]["static_configs"] == [{"targets": ["backend:8000"]}]
    assert "rule_files" not in config


def test_the_reset_command_never_touches_the_metrics_volume():
    source = (ROOT / "backend" / "scripts" / "demo_setup.py").read_text() + (ROOT / "backend" / "app" / "services" / "demo_setup.py").read_text()
    assert "reqtrack_demo_metrics" not in source and "docker" not in source.lower().replace("docker compose", "")


# ---- scripts/demo.sh -----------------------------------------------------------------------------------------


@pytest.fixture
def fake_docker(tmp_path):
    """Puts a `docker` on the path that records its arguments and answers the few calls the commands make."""
    log = tmp_path / "docker.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "docker"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        '  *"config --format json"*) echo \'{"name":"container"}\' ;;\n'
        '  *"volume ls"*) echo "container_reqtrack_demo_metrics" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    script.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DEMO_PROMETHEUS_URL": "http://127.0.0.1:1"}
    return log, env


def _demo(env, *args):
    return subprocess.run(["bash", str(DEMO_SH), *args], capture_output=True, text=True, env=env, timeout=60, check=False)


def test_the_demonstration_starts_prometheus_by_default_and_not_with_no_metrics(fake_docker):
    log, env = fake_docker
    assert _demo(env).returncode == 0
    up = next(line for line in log.read_text().splitlines() if " up " in f" {line} " and "demo-scheduler" not in line)
    assert "--profile demo-metrics" in up
    log.write_text("")
    assert _demo(env, "--no-metrics").returncode == 0
    up = next(line for line in log.read_text().splitlines() if " up " in f" {line} " and "demo-scheduler" not in line)
    assert "demo-metrics" not in up
    assert "--no-metrics" not in " ".join(log.read_text().splitlines()[-1:]), "the option is not passed on to the seed command"


def test_exporting_starts_nothing_and_reports_an_unreachable_prometheus(fake_docker, tmp_path):
    log, env = fake_docker
    done = _demo(env, "--export-metrics", str(tmp_path / "x.tar.gz"))
    assert done.returncode == 1 and "Prometheus" in done.stderr
    assert not (tmp_path / "x.tar.gz").exists()
    assert not log.exists() or " up " not in log.read_text()


def test_purging_stops_the_service_and_removes_only_the_metrics_volume(fake_docker):
    log, env = fake_docker
    assert _demo(env, "--purge-metrics").returncode == 0
    calls = log.read_text().splitlines()
    assert any("rm -sf prometheus" in call for call in calls)
    assert [c for c in calls if c.startswith("volume rm")] == ["volume rm container_reqtrack_demo_metrics"]
    assert any("label=com.docker.compose.volume=reqtrack_demo_metrics" in c for c in calls)


def test_a_reset_alone_removes_no_volume(fake_docker):
    log, env = fake_docker
    assert _demo(env, "--reset").returncode == 0
    text = log.read_text()
    assert "volume rm" not in text and " down" not in text and " rm " not in text
    assert "--reset" in text

