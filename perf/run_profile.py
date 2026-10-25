#!/usr/bin/env python3
"""
Module: perf.run_profile

The portable performance runner: one command per host produces a self-describing, anonymised results bundle.
Run it through `perf/run_profile.sh <host-label> [--quick|--full] ...`.

Responsibilities:
- Check the host (Docker and Compose, free disk, load, memory, headroom), choose resource caps, and refuse to start
  if anything outside the perf project shares its name (`reqtrack-perf`).
- Bring up an isolated stack (database, object storage, backend), restore the requested dataset tier from a
  snapshot or generate it (and snapshot it), set this run's throwaway passwords, and run each scenario at each
  tier the requested number of times with the load generator while sampling container memory and CPU.
- Write the bundle under `perf/results/<host-label>/<date>-<commit>/`, check it for anything identifying, and
  create the archive; always tear the stack down (success, failure, Ctrl-C, watchdog abort).

Design decisions:
- It has no option that names a database, API URL, project or compose file: it can only create and destroy its own
  `reqtrack-perf` project, through `lib.compose.PerfDocker`, which validates every command. Credentials are
  generated per run and never read from the environment or a `.env`.
- `--plan` prints exactly what a run would create and will not touch, and starts nothing.
- Images: pulled when a published image for this exact commit has the host's architecture and the tree is clean,
  otherwise built from the working tree (recorded in `run.json`, because a local build changes a Pi's profile).
- A bundle from a shared host (the default; `--dedicated` says otherwise) is flagged: latency is not comparable
  with a dedicated host's, memory per service still is.
- Python 3.9+, standard library only, so it runs on a bare Raspberry Pi.

Dependencies: Docker with the Compose plugin (2.24 or newer, for `!reset`), Python 3.9+, git.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from perf.lib import bundle, catalog, compose, hostinfo, resources, sampler  # noqa: E402

COMPOSE_FILES = (REPO_ROOT / "docker-compose.yml", REPO_ROOT / "perf" / "docker-compose.perf.yml")
PROFILES_FILE = REPO_ROOT / "perf" / "datasets" / "profiles.yaml"
RESULTS_ROOT = REPO_ROOT / "perf" / "results"
DEFAULT_CACHE = Path.home() / ".cache" / "reqtrack-perf"
GHCR_IMAGE_PREFIX = "ghcr.io/ballardr/reqtrackmanager"
MIN_COMPOSE = (2, 24)
DB_NAME = "reqtrack"
DB_USER = "reqtrack"
EX_USAGE = 2
EX_ABORTED = 3


class RunError(Exception):
    """A step failed; the message is safe to print.

    Attributes:
        code: The process exit status to use.
    """

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


class Interrupted(Exception):
    """The operator pressed Ctrl-C or the process was asked to stop."""


@dataclass
class Options:
    """The parsed command line.

    Attributes:
        label: Host label (validated).
        mode: `quick` (T0 and T1, one repeat, no soak) or `full`.
        tiers: Dataset tiers to run, in order.
        breadth / density / seed: Dataset shape (see `datasets/profiles.yaml`).
        repeats: Repeats of each scenario run (variance).
        workers: `BACKEND_WORKERS` for the stack.
        max_cpus / max_mem: The stack's CPU and memory budget (None: conservative defaults).
        dedicated: The host runs nothing else, so caps default to nearly everything.
        allow_heavy: Run heavy scenarios on a shared host.
        soak_minutes: Soak length in minutes (full mode; 0 disables it).
        plan / cleanup: Print the plan only / remove leftovers of a crashed run only.
        images: `auto`, `pull` or `build`.
        storage: Storage class override.
        keep: Leave the stack running afterwards (inspection).
        out: Results root.
        cache_dir: Where dataset snapshots live (outside the repository).
        watch_url: A read-only health URL to poll and abort on (production's `/health`).
        scenarios: Explicit scenario names, or None for the mode's set.
    """

    label: str
    mode: str = "quick"
    tiers: list = field(default_factory=list)
    breadth: str = "single"
    density: str = "typical"
    seed: int = 1
    repeats: Optional[int] = None
    workers: int = 4
    max_cpus: Optional[float] = None
    max_mem: Optional[float] = None
    dedicated: bool = False
    allow_heavy: bool = False
    soak_minutes: Optional[int] = None
    plan: bool = False
    cleanup: bool = False
    images: str = "auto"
    storage: Optional[str] = None
    keep: bool = False
    out: Path = RESULTS_ROOT
    cache_dir: Path = DEFAULT_CACHE
    watch_url: Optional[str] = None
    scenarios: Optional[list] = None


# --- pure helpers ----------------------------------------------------------------------------------------


def read_profiles_summary(text: str) -> dict:
    """Reads what the runner needs from `profiles.yaml` without a YAML library.

    Only the flat `version`, `tiers` and `breadth` entries are read (the generator validates the whole file with
    PyYAML inside the stack); a file that does not match this shape fails here, before anything starts.

    Args:
        text: The file's contents.

    Returns:
        `{"version": int, "tiers": {name: requirements}, "projects": {breadth: projects per organisation},
        "organisations": {breadth: organisations}}`.

    Raises:
        RunError: If the tiers or breadth blocks are missing.
    """
    version = re.search(r"^version:\s*(\d+)", text, re.M)
    tiers = {m.group(1): int(m.group(2)) for m in re.finditer(r"^  (T\d+):\s*(\d+)", text, re.M)}
    block = text.split("\nbreadth:", 1)[1] if "\nbreadth:" in text else ""
    projects: dict = {}
    organisations: dict = {}
    for match in re.finditer(r"^  ([\w-]+):\s*\{(.*)\}\s*$", block, re.M):
        name, inner = match.group(1), match.group(2)
        orgs = re.search(r"organisations:\s*(\d+)", inner)
        flat = re.search(r"projects_per_org:\s*(\d+)", inner)
        nest = re.search(r"nesting:\s*\{depth:\s*(\d+),\s*fanout:\s*(\d+)\}", inner)
        organisations[name] = int(orgs.group(1)) if orgs else 1
        if nest:
            depth, fanout = int(nest.group(1)), int(nest.group(2))
            projects[name] = sum(fanout**level for level in range(depth))
        elif flat:
            projects[name] = int(flat.group(1))
    if not version or not tiers or not projects:
        raise RunError("datasets/profiles.yaml does not have the expected version, tiers and breadth entries", EX_USAGE)
    return {"version": int(version.group(1)), "tiers": tiers, "projects": projects, "organisations": organisations}


def parse_args(argv: list) -> Options:
    """Parses the command line (see `--help`)."""
    parser = argparse.ArgumentParser(prog="run_profile.sh", description="Run the performance profile on this host and write an anonymised results bundle.")
    parser.add_argument("label", nargs="?", help="generic host label, for example mac-docker-desktop, linux-vm-4c8g or rpi5-8g")
    parser.add_argument("--quick", action="store_true", help="T0 and T1, one repeat, no soak (default)")
    parser.add_argument("--full", action="store_true", help="all tiers, repeats and the soak")
    parser.add_argument("--tiers", help="comma-separated tiers (default: the mode's)")
    parser.add_argument("--breadth", default="single")
    parser.add_argument("--density", default="typical", choices=["sparse", "typical", "dense"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--workers", type=int, default=4, help="BACKEND_WORKERS (default 4, the production default)")
    parser.add_argument("--max-cpus", type=float, help="CPU budget for the whole stack (default: half the cores)")
    parser.add_argument("--max-mem", type=float, help="memory budget in GiB for the whole stack (default: a quarter of Docker's memory)")
    parser.add_argument("--dedicated", action="store_true", help="this host runs nothing else: use nearly all of it, and run heavy scenarios")
    parser.add_argument("--allow-heavy", action="store_true", help="run heavy scenarios (reports, bundles, soak) on a shared host")
    parser.add_argument("--soak-minutes", type=int, help="soak length (full mode; default 30; 0 disables)")
    parser.add_argument("--scenarios", help="comma-separated scenario names (default: the mode's)")
    parser.add_argument("--plan", action="store_true", help="print what would be created and what will not be touched, then exit")
    parser.add_argument("--cleanup", action="store_true", help="remove leftovers of a crashed run (the reqtrack-perf project only), then exit")
    parser.add_argument("--images", choices=["auto", "pull", "build"], default="auto")
    parser.add_argument("--storage", choices=["ssd", "nvme", "hdd", "sd-card", "network"], help="storage class (otherwise guessed)")
    parser.add_argument("--keep", action="store_true", help="leave the stack running afterwards")
    parser.add_argument("--out", type=Path, default=RESULTS_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help="where dataset snapshots are kept (default ~/.cache/reqtrack-perf)")
    parser.add_argument("--watch-url", help="a health URL (production's /health) to poll with GET; the run aborts if it slows or fails")
    args = parser.parse_args(argv)
    if args.quick and args.full:
        parser.error("choose --quick or --full, not both")
    if not args.label and not args.cleanup:
        parser.error("a host label is required")
    return Options(
        label=args.label or "cleanup", mode="full" if args.full else "quick", tiers=args.tiers.split(",") if args.tiers else [],
        breadth=args.breadth, density=args.density, seed=args.seed, repeats=args.repeats, workers=args.workers, max_cpus=args.max_cpus,
        max_mem=args.max_mem, dedicated=args.dedicated, allow_heavy=args.allow_heavy or args.dedicated, soak_minutes=args.soak_minutes,
        plan=args.plan, cleanup=args.cleanup, images=args.images, storage=args.storage, keep=args.keep, out=args.out,
        cache_dir=args.cache_dir, watch_url=args.watch_url, scenarios=args.scenarios.split(",") if args.scenarios else None,
    )


def render_env_file(env: dict) -> str:
    """Renders an environment as the env file Compose reads (a value with a newline, quote or `$` is refused)."""
    lines = []
    for key, value in sorted(env.items()):
        if any(c in str(value) for c in "\n\r\"'$"):
            raise RunError(f"{key} holds a character the env file cannot carry safely", EX_USAGE)
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def stack_environment(
    *, caps: resources.Caps, workers: int, backend_image: str, loadgen_image: str, generate: Callable[[], str] = lambda: secrets.token_urlsafe(24),
) -> dict:
    """The perf stack's environment: fresh throwaway credentials, images, caps and worker count. Nothing is read
    from the operator's environment or any `.env`.

    Args:
        caps: The resource limits.
        workers: `BACKEND_WORKERS`.
        backend_image / loadgen_image: Image references (perf-only names, or a pulled published tag).
        generate: Source of random secrets (replaced in tests).

    Returns:
        The variables for the env file; `SECRET_KEYS` names those to mask.
    """
    storage_secret = generate()
    env = {
        "POSTGRES_PASSWORD": generate(), "JWT_SECRET": generate(), "APP_SECRET_ENCRYPTION_KEY": generate(),
        "SERVER_ADMIN_EMAIL": "admin@example.com", "SERVER_ADMIN_PASSWORD": generate(),
        "STORAGE_SECRET_KEY": storage_secret, "STORAGE_ROOT_PASSWORD": storage_secret, "STORAGE_ACCESS_KEY": "perf",
        "SMTP_HOST": "mail-sink.invalid", "BACKEND_WORKERS": str(workers), "IMAGE_TAG": "perf", "GHCR_IMAGE_PREFIX": GHCR_IMAGE_PREFIX,
        "PERF_USER_PASSWORD": generate(), "PERF_BACKEND_IMAGE": backend_image, "PERF_LOADGEN_IMAGE": loadgen_image,
    }
    env.update(caps.env())
    return env


SECRET_KEYS = ("POSTGRES_PASSWORD", "JWT_SECRET", "APP_SECRET_ENCRYPTION_KEY", "SERVER_ADMIN_PASSWORD", "STORAGE_SECRET_KEY", "STORAGE_ROOT_PASSWORD", "PERF_USER_PASSWORD")


def git_state(repo: Path = REPO_ROOT, run=subprocess.run) -> dict:
    """The commit and whether results from it may be published.

    Returns:
        `{"commit", "dirty", "on_remote"}`. Only the hash is ever recorded; never a branch name, author or diff.
    """
    def out(*args: str) -> str:
        done = run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
        return done.stdout.strip() if done.returncode == 0 else ""

    commit = out("rev-parse", "HEAD")
    return {"commit": commit, "dirty": bool(out("status", "--porcelain")), "on_remote": bool(out("branch", "-r", "--contains", "HEAD"))}


def parse_compose_version(version: str) -> tuple:
    """`(major, minor)` from a Compose version string such as `2.27.1` or `v5.5.1`; `(0, 0)` if unreadable."""
    match = re.match(r"v?(\d+)\.(\d+)", version)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


# --- the run ---------------------------------------------------------------------------------------------


class ProfileRun:
    """One run of the profile.

    Args:
        options: The parsed command line.
        say: Progress sink.
        runner: `subprocess.run`-compatible callable passed to the Docker wrapper (replaced in tests).
        generate: Source of random secrets.
        now: Clock for the bundle date (UTC).
    """

    def __init__(
        self, options: Options, say: Callable[[str], None] = lambda line: print(line, flush=True), runner=subprocess.run,
        generate: Callable[[], str] = lambda: secrets.token_urlsafe(24), now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.options = options
        self.say = say
        self._runner = runner
        self._generate = generate
        self._now = now
        self.summary = read_profiles_summary(PROFILES_FILE.read_text())
        self.work: Optional[Path] = None
        self.docker: Optional[compose.PerfDocker] = None
        self.watchdog: Optional[resources.Watchdog] = None
        self.sampler: Optional[sampler.Sampler] = None
        self.aborted: Optional[str] = None
        self.notes: list = []
        self._noted: set = set()
        self.latency: list = []
        self.datasets: list = []
        self.dataset_details: list = []
        self.env: dict = {}

    # planning -------------------------------------------------------------

    def tiers(self) -> list:
        """The tiers to run, validated against the profiles file and ordered."""
        chosen = self.options.tiers or list(catalog.QUICK_TIERS if self.options.mode == "quick" else catalog.TIER_ORDER)
        unknown = [t for t in chosen if t not in self.summary["tiers"]]
        if unknown:
            raise RunError(f"unknown tier {unknown[0]!r}; defined: {', '.join(sorted(self.summary['tiers']))}", EX_USAGE)
        if self.options.breadth not in self.summary["projects"]:
            raise RunError(f"unknown breadth profile {self.options.breadth!r}; defined: {', '.join(sorted(self.summary['projects']))}", EX_USAGE)
        return sorted(chosen, key=catalog.TIER_ORDER.index)

    def total_requirements(self, tier: str) -> int:
        """Requirements a tier holds across every project of the breadth profile."""
        breadth = self.options.breadth
        return self.summary["tiers"][tier] * self.summary["projects"][breadth] * self.summary["organisations"][breadth]

    def scenario_names(self) -> list:
        """The scenarios to run."""
        if self.options.scenarios:
            unknown = [s for s in self.options.scenarios if s not in catalog.CATALOG]
            if unknown:
                raise RunError(f"unknown scenario {unknown[0]!r}; defined: {', '.join(catalog.CATALOG)}", EX_USAGE)
            return list(self.options.scenarios)
        nested = "nested" in self.options.breadth
        soak = self.options.mode == "full" and (self.options.soak_minutes is None or self.options.soak_minutes > 0)
        return catalog.scenarios_for(self.options.mode, allow_heavy=self.options.allow_heavy, nested=nested, soak=soak)

    def repeats(self) -> int:
        """Repeats per scenario run (3 in full mode, 1 in quick, unless overridden)."""
        return self.options.repeats or (3 if self.options.mode == "full" else 1)

    def plan_lines(self, host: dict, caps: resources.Caps, image_source: str) -> list:
        """What a run would create and what it will not touch, as printable lines."""
        tiers = self.tiers()
        largest = max(self.total_requirements(t) for t in tiers)
        sizes = self.summary["tiers"]
        tier_text = ", ".join(f"{t} ({sizes[t]} requirements per project, {self.total_requirements(t)} in all)" for t in tiers)
        lines = [
            f"Plan for host label '{self.options.label}' ({self.options.mode} mode)",
            f"  Compose project   : {compose.PROJECT} (files: docker-compose.yml + perf/docker-compose.perf.yml; no published ports)",
            f"  Services          : db, storage, backend (workers={self.options.workers}), plus a load generator container per scenario",
            f"  Images            : {image_source}",
            f"  Caps              : {caps.cpus:g} CPUs, {caps.memory_gib:.1f} GiB memory, no swap (backend {caps.per_service['backend']['mem']}, db {caps.per_service['db']['mem']})",
            f"  Host              : {host['arch']}, {host['docker_cores']} cores and {host['docker_ram_gib']} GiB visible to Docker",
            f"  Tiers             : {tier_text}",
            f"  Dataset           : breadth {self.options.breadth}, link density {self.options.density}, seed {self.options.seed}",
            f"  Scenarios         : {', '.join(self.scenario_names())} x {self.repeats()} repeat(s)",
            f"  Disk              : about {resources.estimate_disk_gib(largest):.1f} GiB (images, database, snapshot in {self.options.cache_dir})",
            f"  Results           : {self.options.out / self.options.label}/<date>-<commit>/",
            "  Will create       : containers, volumes and a network named reqtrack-perf-*; a 0700 temp directory with throwaway credentials; snapshots in the cache directory",
            "  Will NOT touch    : any other container, volume, network or image; any .env, secret, port or database of another stack; no docker prune",
            "  Shared host       : " + ("no (--dedicated)" if self.options.dedicated else "yes: bundle is flagged shared-host; latency is not comparable with a dedicated host"),
        ]
        if self.options.watch_url:
            lines.append("  Watch URL         : polled with GET only; the run aborts if it slows or fails")
        return lines

    # docker plumbing ------------------------------------------------------

    def _docker_for_cleanup(self) -> compose.PerfDocker:
        return compose.PerfDocker(COMPOSE_FILES, None, REPO_ROOT, runner=self._runner)

    def _require(self, result: compose.Result, what: str) -> compose.Result:
        if not result.ok:
            tail = " | ".join((result.err or result.out).strip().splitlines()[-6:])
            raise RunError(f"{what} failed (exit {result.code}): {tail}")
        return result

    def _exec(self, service: str, *command: str, timeout: float = 3600, show_stderr: bool = False, **options) -> compose.Result:
        return self.docker.compose("exec", "-T", service, *command, timeout=timeout, show_stderr=show_stderr, **options)

    def _backend_python(self, script: str, *args: str, timeout: float = 14400, show_stderr: bool = False) -> compose.Result:
        return self._exec("backend", "python", f"/perf/{script}", *args, timeout=timeout, show_stderr=show_stderr)

    def _wait_backend(self, timeout: float = 3600) -> float:
        started = time.monotonic()
        self._require(self.docker.compose("up", "-d", "--wait", "--wait-timeout", str(int(timeout)), "backend", timeout=timeout + 120), "starting the backend")
        return time.monotonic() - started

    def _reset_stack(self) -> None:
        """Removes the project's containers and volumes so each tier starts from an empty database."""
        self.docker.compose("down", "-v", "--remove-orphans", profiles=("loadgen",), timeout=600)
        self.docker.remove_leftovers()
        self._require(self.docker.compose("up", "-d", "--wait", "db", "storage", timeout=900), "starting the database and storage")

    # images ---------------------------------------------------------------

    def choose_images(self, host: dict, git: dict) -> tuple:
        """Decides whether to pull a published backend image or build from the working tree.

        Returns:
            `(backend image reference, source)` with `source` `pulled` or `built`.
        """
        built = ("reqtrack-perf-backend:build", "built")
        if self.options.images == "build":
            return built
        published = f"{GHCR_IMAGE_PREFIX}-backend:{git['commit']}"
        usable = False
        if git["commit"] and not git["dirty"]:
            probe = self.docker.docker("buildx", "imagetools", "inspect", published, timeout=60) if self.docker else None
            usable = bool(probe and probe.ok and re.search(rf"Platform:\s*linux/{host['arch']}\b", probe.out))
        if usable:
            return published, "pulled"
        if self.options.images == "pull":
            raise RunError(f"no published backend image for this commit with architecture {host['arch']} (or the tree has uncommitted changes); use --images build")
        return built

    # datasets -------------------------------------------------------------

    def snapshot_paths(self, key: str) -> tuple:
        """The dump and manifest paths for a snapshot key."""
        return self.options.cache_dir / f"{key}.dump", self.options.cache_dir / f"{key}.manifest.json"

    def dataset_args(self, tier: str) -> list:
        """The generator's arguments for a tier."""
        o = self.options
        return ["--tier", tier, "--breadth", o.breadth, "--density", o.density, "--seed", str(o.seed)]

    def snapshot_key(self, tier: str) -> str:
        """The snapshot key for a tier on this image's schema (asked of the backend image; no database needed)."""
        done = self.docker.compose(
            "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "backend", "/perf/generate_dataset.py", "--key-only", *self.dataset_args(tier),
            timeout=600,
        )
        self._require(done, "computing the dataset snapshot key")
        key = done.out.strip().splitlines()[-1]
        if not re.match(r"^[A-Za-z0-9_.-]+$", key):
            raise RunError("the dataset snapshot key has an unexpected form")
        return key

    def restore_snapshot(self, dump: Path) -> None:
        """Loads a snapshot into the empty database."""
        self.say(f"  restoring dataset snapshot ({dump.stat().st_size / 2**20:.0f} MiB)")
        self._require(
            self._exec("db", "pg_restore", "-U", DB_USER, "-d", DB_NAME, "--no-owner", "--exit-on-error", stdin_path=dump, timeout=14400),
            "restoring the dataset snapshot",
        )

    def make_snapshot(self, dump: Path) -> None:
        """Dumps the generated database for reuse (written through a temp name, then renamed)."""
        dump.parent.mkdir(parents=True, exist_ok=True)
        partial = dump.with_suffix(".partial")
        self._require(self._exec("db", "pg_dump", "-U", DB_USER, "-Fc", DB_NAME, stdout_path=partial, timeout=14400), "snapshotting the dataset")
        partial.replace(dump)

    def prepare_dataset(self, tier: str) -> tuple:
        """Gets the tier's data into a running stack.

        Returns:
            `(manifest, details)` where details has `snapshot_used`, `generation_seconds` and `startup_seconds`.
        """
        key = self.snapshot_key(tier)
        dump, manifest_path = self.snapshot_paths(key)
        self._reset_stack()
        if dump.exists() and manifest_path.exists():
            self.restore_snapshot(dump)
            startup = self._wait_backend()
            manifest = json.loads(manifest_path.read_text())
            generation = 0.0
            used = True
        else:
            self.say(f"  no snapshot for {key}: generating {tier}")
            startup = self._wait_backend()
            started = time.monotonic()
            done = self._backend_python("generate_dataset.py", *self.dataset_args(tier), show_stderr=True)
            generation = time.monotonic() - started
            if not done.out.strip().startswith("{"):
                raise RunError(f"generating {tier} failed (exit {done.code}); see the output above")
            manifest = json.loads(done.out)
            if manifest["integrity_problems"]:
                raise RunError("the generated dataset failed its integrity check: " + "; ".join(manifest["integrity_problems"]))
            self.say("  snapshotting the dataset")
            self.make_snapshot(dump)
            manifest_path.write_text(json.dumps(manifest))
            used = False
        self._require(self._backend_python("prepare_run.py", timeout=900), "setting this run's passwords")
        return manifest, {"snapshot_used": used, "generation_seconds": round(generation, 1), "startup_seconds": round(startup, 1)}

    def database_bytes(self) -> int:
        """The database's size in bytes."""
        done = self._exec("db", "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", f"select pg_database_size('{DB_NAME}')")
        return int(done.out.strip()) if done.ok and done.out.strip().isdigit() else 0

    # scenarios ------------------------------------------------------------

    def run_loadgen(self, manifest: dict, scenario: str, params: dict) -> dict:
        """Runs the load generator once and returns its JSON summary."""
        request = {
            "scenario": scenario, "users": params["users"], "duration_s": params["measure_seconds"], "warmup_s": params["warmup_seconds"],
            "min_requests": params["min_requests"], "max_seconds": params["max_seconds"], "manifest": manifest,
        }
        budget = params["warmup_seconds"] + max(params["measure_seconds"], params["max_seconds"] if params["min_requests"] else 0) + 300
        done = self.docker.compose("run", "--rm", "-T", "loadgen", profiles=("loadgen",), input=json.dumps(request), timeout=budget)
        if self.aborted:
            raise RunError(f"aborted: {self.aborted}", EX_ABORTED)
        if not done.ok or not done.out.strip().startswith("{"):
            raise RunError(f"the {scenario} run failed (exit {done.code}): " + " | ".join(done.err.strip().splitlines()[-4:]))
        return json.loads(done.out)

    def check_backend_health(self, tier: str, scenario: str) -> None:
        """Notes an out-of-memory kill or restart of the backend (a finding, not an error), once per kind and tier.

        Docker keeps `OOMKilled` set once any process of the container was killed for memory, so later scenarios would
        repeat the same note; the first scenario to see it is the one recorded.
        """
        done = self.docker.docker("inspect", "-f", "{{.State.OOMKilled}} {{.RestartCount}}", f"{compose.PROJECT}-backend-1")
        if done.ok:
            oom, restarts = (done.out.split() + ["false", "0"])[:2]
            for kind, seen in (("OOM-killed", oom == "true"), ("restarted", restarts not in ("0", ""))):
                if seen and (tier, kind) not in self._noted:
                    self._noted.add((tier, kind))
                    self.notes.append(f"backend {kind} by the end of {scenario} at {tier} (restarts {restarts}); its memory cap may be too small for {self.options.workers} workers")

    def run_scenarios(self, tier: str, manifest: dict, names: list) -> None:
        """Runs every scenario at the tier, `repeats` times, recording latency and sampling resources."""
        per_project = self.summary["tiers"][tier]
        soak_minutes = self.options.soak_minutes if self.options.soak_minutes is not None else 30
        for name in names:
            for params in catalog.parameters(name, self.options.mode, per_project):
                if name == "soak":
                    params = dict(params, measure_seconds=soak_minutes * 60, warmup_seconds=120)
                for repeat in range(1, (1 if name == "soak" else self.repeats()) + 1):
                    self.say(f"  {tier} {name} users={params['users']} repeat={repeat}")
                    self.sampler.tag(tier=tier, scenario=name, repeat=repeat)
                    summary = self.run_loadgen(manifest, name, params)
                    for row in summary["requests"]:
                        self.latency.append({
                            "tier": tier, "scenario": name, "repeat": repeat, "users": params["users"], "request": row["name"],
                            "count": row["count"], "failures": row["failures"], "throttled": row["throttled"], "p50_ms": row["p50_ms"],
                            "p95_ms": row["p95_ms"], "p99_ms": row["p99_ms"], "mean_ms": row["mean_ms"], "max_ms": row["max_ms"],
                            "rps": row["rps"], "bytes_mean": row["bytes_mean"],
                        })
                    self.check_backend_health(tier, name)

    # the run --------------------------------------------------------------

    def preflight(self, host: dict, caps: resources.Caps) -> None:
        """Refuses to start unless the host can take the run safely."""
        if parse_compose_version(host["compose_version"]) < MIN_COMPOSE:
            raise RunError(f"Docker Compose {MIN_COMPOSE[0]}.{MIN_COMPOSE[1]} or newer is required (found {host['compose_version']}); the perf override uses !reset", EX_USAGE)
        if sys.version_info < (3, 9):
            raise RunError("Python 3.9 or newer is required", EX_USAGE)
        foreign = self.docker.foreign_resources()
        if foreign:
            raise RunError(f"{foreign[0]} shares the name prefix '{compose.PROJECT}' but is not part of the perf project; refusing to start", EX_USAGE)
        existing = self.docker.project_resources()
        if any(existing.values()):
            raise RunError(f"a {compose.PROJECT} project already exists (a crashed run?); run with --cleanup to remove it", EX_USAGE)
        largest = max(self.total_requirements(t) for t in self.tiers())
        self.options.cache_dir.mkdir(parents=True, exist_ok=True)
        reasons = resources.preflight_headroom(
            caps, total_requirements=largest, disk_path=self.options.cache_dir, available=self._available_reader(host),
        )
        if reasons:
            raise RunError("not enough headroom on this host: " + "; ".join(reasons), EX_USAGE)

    def _available_reader(self, host: dict) -> Callable[[], Optional[float]]:
        """Memory still free for new work: inside the VM on Docker Desktop (shared by every container), else the host's."""
        if host["docker_vm"]:
            return lambda: (host["docker_ram_gib"] - used) if (used := sampler.total_container_memory_gib(self.docker)) is not None else None
        return resources.available_memory_gib

    def execute(self) -> int:
        """Runs the profile and returns the process exit status."""
        options = self.options
        if not options.cleanup:
            hostinfo.validate_label(options.label)
        self.docker = self._docker_for_cleanup()
        if options.cleanup:
            removed = self.docker.remove_leftovers()
            self.say(f"removed {len(removed)} {compose.PROJECT} resource(s)" if removed else f"no {compose.PROJECT} resources found")
            return 0
        host = hostinfo.collect(storage=options.storage, run=self._runner)
        caps = resources.plan_caps(host["docker_cores"], host["docker_ram_gib"], max_cpus=options.max_cpus, max_mem_gib=options.max_mem, dedicated=options.dedicated, docker_vm=host["docker_vm"], workers=options.workers)
        git = git_state(run=self._runner)
        backend_image, image_source = self.choose_images(host, git)
        for line in self.plan_lines(host, caps, f"backend {image_source} ({backend_image.split(':')[0].split('/')[-1]}), load generator built locally"):
            self.say(line)
        if options.plan:
            return 0
        self.preflight(host, caps)

        self.work = Path(tempfile.mkdtemp(prefix=f"{compose.PROJECT}-"))
        self.work.chmod(0o700)
        self.env = stack_environment(caps=caps, workers=options.workers, backend_image=backend_image, loadgen_image="reqtrack-perf-loadgen:build", generate=self._generate)
        env_file = self.work / "perf.env"
        env_file.write_text(render_env_file(self.env))
        env_file.chmod(0o600)
        self.docker = compose.PerfDocker(COMPOSE_FILES, env_file, REPO_ROOT, secrets=[self.env[k] for k in SECRET_KEYS], runner=self._runner)
        self.sampler = sampler.Sampler(self.docker)
        self.watchdog = resources.Watchdog(
            resources.Thresholds(), options.cache_dir, watch_url=options.watch_url, on_trip=self._on_watchdog,
            readers={"available": self._available_reader(host)},
        )
        started = self._now()
        tiers, names = self.tiers(), self.scenario_names()
        previous = {sig: signal.signal(sig, self._on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
        status = 0
        try:
            self.say("building images")
            builds = ["loadgen"] + (["backend"] if image_source == "built" else [])
            self._require(self.docker.compose("build", *builds, profiles=("loadgen",), timeout=3600, show_stderr=True), "building images")
            if image_source == "pulled":
                self._require(self.docker.compose("pull", "backend", timeout=1800, show_stderr=True), "pulling the backend image")
            self.watchdog.start()
            self.sampler.start()
            for tier in tiers:
                self.say(f"tier {tier}")
                manifest, details = self.prepare_dataset(tier)
                self.datasets.append(self._dataset_entry(tier, manifest, details))
                self.dataset_details.append(details)
                self.run_scenarios(tier, manifest, names)
        except Interrupted:
            self.aborted = self.aborted or "interrupted"
            status = EX_ABORTED
            self.say("interrupted: tearing down")
        except RunError as exc:
            if self.aborted:
                status = EX_ABORTED
            else:
                self.say(f"error: {exc}")
                status = exc.code
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.watchdog.stop()
            self.sampler.stop()
            if not options.keep:
                self.teardown()
        written = self.write_results(host, git, caps, image_source, started, tiers, names)
        if written:
            self.say(f"results: {written}")
        return status

    def _dataset_entry(self, tier: str, manifest: dict, details: dict) -> dict:
        return {
            "tier": tier, "spec": manifest["spec"], "rows": manifest["rows"], "link_degree_histogram": manifest["link_degree_histogram"],
            "integrity_problems": manifest["integrity_problems"], "database_bytes": self.database_bytes(),
            "generation_seconds": details["generation_seconds"],
        }

    def _on_signal(self, _signum, _frame) -> None:
        raise Interrupted()

    def _on_watchdog(self, reason: str) -> None:
        """Stops the load the moment the host is under pressure (runs on the watchdog's thread)."""
        self.aborted = f"host-pressure: {reason}"
        self.say(f"watchdog: {reason}; stopping the run")
        self.docker.remove_leftovers()

    def teardown(self) -> None:
        """Removes the stack and the throwaway credentials, whatever happened."""
        try:
            self.docker.compose("down", "-v", "--remove-orphans", profiles=("loadgen",), timeout=600)
            self.docker.remove_leftovers()
        finally:
            if self.work and self.work.exists():
                shutil.rmtree(self.work, ignore_errors=True)

    def write_results(self, host: dict, git: dict, caps: resources.Caps, image_source: str, started: datetime, tiers: list, names: list) -> Optional[Path]:
        """Writes the bundle and archive; returns the bundle directory, or None when nothing was measured."""
        if not self.latency and not self.datasets:
            return None
        reasons = []
        if git["dirty"]:
            reasons.append("uncommitted changes")
        if not git["on_remote"]:
            reasons.append("commit is not on a remote branch")
        if self.aborted:
            reasons.append("aborted")
        details = self.dataset_details
        host_doc = dict(host)
        if self.sampler.throttle_flags_seen:
            host_doc["throttle_flags_seen"] = sorted(self.sampler.throttle_flags_seen)
        run_doc = {
            "schema_version": bundle.RUN_SCHEMA_VERSION, "host_label": self.options.label, "commit": git["commit"],
            "date": started.strftime("%Y-%m-%d"), "mode": self.options.mode, "tiers": tiers, "breadth": self.options.breadth,
            "density": self.options.density, "seed": self.options.seed, "profiles_version": self.summary["version"], "scenarios": names,
            "repeats": self.repeats(), "workers": self.options.workers, "image_source": image_source, "caps": caps.as_dict(),
            "shared_host": not self.options.dedicated, "non_publishable": bool(reasons), "non_publishable_reasons": reasons,
            "aborted": self.aborted, "snapshot_used": [d["snapshot_used"] for d in details],
            "startup_seconds": [d["startup_seconds"] for d in details], "notes": self.notes,
        }
        directory = bundle.bundle_dir(self.options.out, self.options.label, run_doc["date"], git["commit"] or "0" * 7)
        samples = [row for row in self.sampler.rows if "scenario" in row]
        bundle.write_bundle(directory, host=host_doc, run=run_doc, datasets=self.datasets, samples=samples, latency=self.latency)
        archive = bundle.make_archive(directory, self.options.cache_dir / f"{directory.name}.tar.gz")
        self.say(f"archive: {archive}")
        return directory


def main(argv: Optional[list] = None) -> int:
    """Entry point; returns the process exit status."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return ProfileRun(options).execute()
    except RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (hostinfo.HostInfoError, resources.ResourceError, bundle.BundleError, compose.UnsafeCommand) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EX_USAGE


if __name__ == "__main__":
    sys.exit(main())
