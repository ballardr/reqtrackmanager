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
  write the bundle (and an archive with `--archive`); always tear the stack down (success, failure, Ctrl-C, watchdog abort).
- After every scenario, read the backend's per-route database statement counts and per-process memory
  (`queries.csv`, `processes.csv`); with `--profiling cpu`, sample the backend with py-spy during the highest-load
  run of each scenario (`profiles/*.svg`); with `--profiling heap`, run one worker under memray and report what it
  still held at the end (`heap.csv`).
- Profile the database: the perf stack's PostgreSQL loads `pg_stat_statements`; for each scenario the runner resets
  it, polls client connection counts while the load runs, and afterwards keeps the costliest statements
  (`pgstat.csv`), what the database did (`pgdb.csv`: connection peak, cache hit rate, temp files, deadlocks) and
  the planner's scans for the worst few (`plans.csv`), with the server's memory settings and the pool ceiling in
  `run.json`.

Design decisions:
- It has no option that names a database, API URL, project or compose file: it can only create and destroy its own
  `reqtrack-perf` project, through `lib.compose.PerfDocker`, which validates every command. Credentials are
  generated per run and never read from the environment or a `.env`.
- `--plan` prints exactly what a run would create and will not touch, and starts nothing.
- Images: pulled when a published image for this exact commit has the host's architecture and the tree is clean,
  otherwise built from the working tree (recorded in `run.json`, because a local build changes a Pi's profile).
- A bundle from a shared host (the default; `--dedicated` says otherwise) is flagged: latency is not comparable
  with a dedicated host's, memory per service still is.
- Profiling modes use the `profile` image target (memray, py-spy; `docker-compose.profile.yml`), always built from
  the working tree. Their latency is not comparable, so the run says so in `run.json`; the stack is still isolated.
- Python 3.9+, standard library only, so it runs on a bare Raspberry Pi.

Dependencies: Docker with the Compose plugin (2.24 or newer, for `!reset`), Python 3.9+, git.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from perf.lib import bundle, catalog, compose, hostinfo, pgprofile, resources, sampler  # noqa: E402

COMPOSE_FILES = (REPO_ROOT / "docker-compose.yml", REPO_ROOT / "perf" / "docker-compose.perf.yml")
PROFILE_COMPOSE_FILE = REPO_ROOT / "docker-compose.profile.yml"
PROFILE_IMAGE = "reqtrack-perf-backend:profile"
PROFILING_MODES = ("none", "cpu", "heap")
QUERY_FLUSH_SECONDS = 2.5
"""Longer than the backend's flush interval, so a scenario's last requests are in the files before they are read."""
CPU_SAMPLE_HZ = 100
HEAP_STOP_SECONDS = 180
SOURCE_PATH_REPLACEMENTS = (
    ("/usr/local/lib/python3.12/site-packages/", "site-packages/"), ("/usr/local/lib/python3.12/", "stdlib/"), ("/app/", ""),
)
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


APP_DEFAULT_POOL_SIZE = 5
APP_DEFAULT_MAX_OVERFLOW = 10
"""The application's pool defaults (`Settings.db_pool_size`, `db_max_overflow`)."""
PERF_MAX_CONNECTIONS = 100
"""PostgreSQL's `max_connections` in the perf stack (its default)."""
DEDICATED_MAX_LOAD_PER_CORE = 4.0
"""Load limit on a dedicated host: nothing else runs there, so load is mostly this run's own threads."""


@dataclass
class Options:
    """The parsed command line.

    Attributes:
        label: Host label (validated).
        mode: `quick` (T0 and T1, one repeat, no soak) or `full`.
        tiers: Dataset tiers to run, in order.
        breadth / density / seed: Dataset shape (see `datasets/profiles.yaml`).
        repeats: Repeats of each scenario run (variance).
        workers: `BACKEND_WORKERS` for the stack, or None to choose from the budget (the default; at most 4).
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
        archive: Also write a `.tar.gz` of each bundle beside it, inside the results directory.
        watch_url: A read-only health URL to poll and abort on (production's `/health`).
        worker_sweep: Backend worker counts to run one after another, each as its own run (`--workers-sweep`), or None.
        malloc_arena_max / limit_max_requests: Backend memory experiments: glibc's `MALLOC_ARENA_MAX`, and uvicorn's
            `--limit-max-requests` (a worker is replaced after that many requests); None leaves the application's default.
        pg_shared_buffers / pg_work_mem: PostgreSQL's `shared_buffers` and `work_mem` for the perf stack's database (for
            example `512MB`, `16MB`), or None for PostgreSQL's defaults (128MB, 4MB).
        db_pool_size / db_max_overflow: Per-worker database pool (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`); None for the
            application's defaults (5 and 10).
        capacity_users: Simulated-user levels of the `capacity` scenario, or None for the catalogue's.
        capacity_tier: The tier the `capacity` scenario runs at, or None for T2.
        max_load_per_core: Host load average per core above which (for a sustained period) the run stops; None for
            the default (1.5, or `DEDICATED_MAX_LOAD_PER_CORE` on a dedicated host).
        scenarios: Explicit scenario names, or None for the mode's set.
        profiling: `none`, `cpu` (py-spy flamegraphs) or `heap` (one worker under memray; one tier).
    """

    label: str
    mode: str = "quick"
    tiers: list = field(default_factory=list)
    breadth: str = "single"
    density: str = "typical"
    seed: int = 1
    repeats: Optional[int] = None
    workers: Optional[int] = None
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
    archive: bool = False
    watch_url: Optional[str] = None
    max_load_per_core: Optional[float] = None
    capacity_users: Optional[tuple] = None
    capacity_tier: Optional[str] = None
    pg_shared_buffers: Optional[str] = None
    pg_work_mem: Optional[str] = None
    malloc_arena_max: Optional[int] = None
    limit_max_requests: Optional[int] = None
    db_pool_size: Optional[int] = None
    db_max_overflow: Optional[int] = None
    worker_sweep: Optional[tuple] = None
    scenarios: Optional[list] = None
    profiling: str = "none"


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
    parser.add_argument(
        "--workers", default="auto",
        help="BACKEND_WORKERS: a number, or auto (default) for the most the CPU and memory budget supports, up to 4, the production default",
    )
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
    parser.add_argument("--archive", action="store_true", help="also write a .tar.gz of the bundle beside it in the results directory (off by default: the bundle directory is what you copy)")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help="where dataset snapshots are kept (default ~/.cache/reqtrack-perf)")
    parser.add_argument(
        "--profiling", default="none", choices=PROFILING_MODES,
        help="cpu: py-spy flamegraph per scenario; heap: one worker under memray, one tier (both build the profile image; latency is not comparable)",
    )
    parser.add_argument(
        "--max-load-per-core", type=float, default=None,
        help="stop the run when the host's 1-minute load average per core stays above this for about 30 seconds (default 1.5, or 4 "
             "with --dedicated, where there is no neighbour to protect and the load is mostly the run's own). "
             "The load counts every runnable thread on the host, including this stack's own, and a container held back by its CPU cap "
             "still counts, so a busy server may need a higher value; --watch-url is the direct check that production is unaffected",
    )
    parser.add_argument(
        "--workers-sweep", help="comma-separated backend worker counts (for example 2,4,6) to run one after another, each as its own run "
                                "with the same pool, so only the worker count varies; stops at the first run that fails or aborts",
    )
    parser.add_argument("--pg-shared-buffers", help="PostgreSQL shared_buffers for the perf stack's database, for example 512MB (default 128MB); must fit the database's memory cap")
    parser.add_argument("--pg-work-mem", help="PostgreSQL work_mem for the perf stack's database, for example 16MB (default 4MB)")
    parser.add_argument("--db-pool-size", type=int, help="DB_POOL_SIZE for the backend (default 5); lower it to run many workers within PostgreSQL's connection limit")
    parser.add_argument("--db-max-overflow", type=int, help="DB_MAX_OVERFLOW for the backend (default 10)")
    parser.add_argument(
        "--capacity-tier", choices=catalog.TIER_ORDER,
        help="the dataset tier the capacity scenario runs at (default T2, 1,000 requirements per project); the tier must also be in --tiers",
    )
    parser.add_argument(
        "--capacity-users", help="comma-separated simulated-user levels for the capacity scenario (default 16,32,64,128,256 in full mode, "
                                 "16,64 in quick); it runs at T2 only and is a heavy scenario (--allow-heavy or --dedicated)",
    )
    parser.add_argument("--malloc-arena-max", type=int, help="glibc MALLOC_ARENA_MAX for the backend (1-64), to test whether worker memory is allocator retention")
    parser.add_argument("--limit-max-requests", type=int, help="replace each backend worker after this many requests (uvicorn --limit-max-requests, 100-1000000)")
    parser.add_argument("--watch-url", help="a health URL (production's /health) to poll with GET; the run aborts if it slows or fails")
    args = parser.parse_args(argv)
    for flag, value in (("--pg-shared-buffers", args.pg_shared_buffers), ("--pg-work-mem", args.pg_work_mem)):
        if value is not None and not re.fullmatch(r"[1-9][0-9]{0,5}(MB|GB)", value):
            parser.error(f"{flag} takes a size such as 512MB or 2GB")
    for flag, value, low, high in (("--malloc-arena-max", args.malloc_arena_max, 1, 64), ("--limit-max-requests", args.limit_max_requests, 100, 1_000_000)):
        if value is not None and not low <= value <= high:
            parser.error(f"{flag} must be between {low} and {high}")
    for flag, value, low in (("--db-pool-size", args.db_pool_size, 1), ("--db-max-overflow", args.db_max_overflow, 0)):
        if value is not None and not low <= value <= 200:
            parser.error(f"{flag} must be between {low} and 200")
    if args.capacity_tier:
        run_tiers = args.tiers.split(",") if args.tiers else list(catalog.QUICK_TIERS if not args.full else catalog.TIER_ORDER)
        if args.capacity_tier not in run_tiers:
            parser.error(f"--capacity-tier {args.capacity_tier} is not among the tiers this run covers ({','.join(run_tiers)}); add it to --tiers")
    worker_sweep = None
    if args.workers_sweep:
        try:
            worker_sweep = tuple(sorted({int(part) for part in args.workers_sweep.split(",")}))
        except ValueError:
            parser.error("--workers-sweep takes whole numbers separated by commas")
        if len(worker_sweep) < 2 or min(worker_sweep) < 1 or max(worker_sweep) > 64:
            parser.error("--workers-sweep needs at least two distinct worker counts between 1 and 64")
        if args.workers != "auto" or args.profiling == "heap":
            parser.error("--workers-sweep chooses the worker counts: do not combine it with --workers or --profiling heap")
    capacity_users = None
    if args.capacity_users:
        try:
            capacity_users = tuple(int(part) for part in args.capacity_users.split(","))
        except ValueError:
            parser.error("--capacity-users takes whole numbers separated by commas")
        if not capacity_users or min(capacity_users) < 1 or max(capacity_users) > 1000:
            parser.error("--capacity-users levels must be between 1 and 1000")
    if args.workers != "auto" and not (args.workers.isdigit() and int(args.workers) >= 1):
        parser.error("--workers must be a positive number or 'auto'")
    if args.profiling == "heap" and (not args.tiers or len(args.tiers.split(",")) != 1):
        parser.error("--profiling heap needs exactly one tier (--tiers T1): the capture covers one backend start")
    if args.profiling == "heap" and args.workers not in ("auto", "1"):
        parser.error("--profiling heap runs one worker; omit --workers or use 1")
    if args.profiling != "none" and args.images == "pull":
        parser.error("--profiling builds the profile image from the working tree; it cannot use --images pull")
    if args.quick and args.full:
        parser.error("choose --quick or --full, not both")
    if not args.label and not args.cleanup:
        parser.error("a host label is required")
    return Options(
        label=args.label or "cleanup", mode="full" if args.full else "quick", tiers=args.tiers.split(",") if args.tiers else [],
        breadth=args.breadth, density=args.density, seed=args.seed, repeats=args.repeats, workers=1 if args.profiling == "heap" else (None if args.workers == "auto" else int(args.workers)), max_cpus=args.max_cpus,
        max_mem=args.max_mem, dedicated=args.dedicated, allow_heavy=args.allow_heavy or args.dedicated, soak_minutes=args.soak_minutes,
        plan=args.plan, cleanup=args.cleanup, images=args.images, storage=args.storage, keep=args.keep, out=args.out,
        cache_dir=args.cache_dir, archive=args.archive, watch_url=args.watch_url, max_load_per_core=args.max_load_per_core, capacity_users=capacity_users, capacity_tier=args.capacity_tier, pg_shared_buffers=args.pg_shared_buffers, pg_work_mem=args.pg_work_mem, malloc_arena_max=args.malloc_arena_max, limit_max_requests=args.limit_max_requests, db_pool_size=args.db_pool_size, db_max_overflow=args.db_max_overflow, worker_sweep=worker_sweep, scenarios=args.scenarios.split(",") if args.scenarios else None, profiling=args.profiling,
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
    profiling: str = "none", db_pool: tuple = (None, None), pg: tuple = (None, None), memory: tuple = (None, None),
) -> dict:
    """The perf stack's environment: fresh throwaway credentials, images, caps and worker count. Nothing is read
    from the operator's environment or any `.env`.

    Args:
        caps: The resource limits.
        workers: `BACKEND_WORKERS`.
        backend_image / loadgen_image: Image references (perf-only names, or a pulled published tag).
        generate: Source of random secrets (replaced in tests).
        profiling: The profiling mode; `heap` starts the backend as one worker under memray.
        db_pool: `(DB_POOL_SIZE, DB_MAX_OVERFLOW)`; None leaves the application's default.
        pg: `(shared_buffers, work_mem)` for the database; None leaves PostgreSQL's default.
        memory: `(MALLOC_ARENA_MAX, limit-max-requests)` for the backend; None leaves the default.

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
    for name, value in zip(("DB_POOL_SIZE", "DB_MAX_OVERFLOW"), db_pool):
        if value is not None:
            env[name] = str(value)
    for name, value in zip(("PERF_PG_SHARED_BUFFERS", "PERF_PG_WORK_MEM"), pg):
        if value is not None:
            env[name] = value
    for name, value in zip(("PERF_MALLOC_ARENA_MAX", "PERF_LIMIT_MAX_REQUESTS"), memory):
        if value is not None:
            env[name] = str(value)
    if profiling == "heap":
        env["PROFILE_MEMRAY"] = "1"
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
        self.workers = options.workers or resources.DEFAULT_WORKERS
        self.caps = None
        self.results_directory: Optional[Path] = None
        self.latency: list = []
        self.process_rows: list = []
        self.profile_files: dict = {}
        self.heap_rows: Optional[list] = None
        self.heap_totals: dict = {}
        self.suspects: dict = {}
        self._queries_before: dict = {}
        self._query_totals: dict = {}
        self.pg_enabled = False
        self.pg_settings: dict = {}
        self.db_pool: dict = {}
        self.pgstat_rows: list = []
        self.pgdb_rows: list = []
        self.plan_rows: list = []
        self._pg_before: dict = {}
        self._pg_poller: Optional[pgprofile.ConnectionPoller] = None
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
        worker_text = f"{caps.workers}, chosen from the budget" if caps.workers_auto else str(caps.workers)
        lines = [
            f"Plan for host label '{self.options.label}' ({self.options.mode} mode)",
            f"  Compose project   : {compose.PROJECT} (files: docker-compose.yml + perf/docker-compose.perf.yml" + (" + docker-compose.profile.yml" if self.options.profiling != "none" else "") + "; no published ports)",
            f"  Services          : db, storage, backend (workers={worker_text}), plus a load generator container per scenario",
            f"  Images            : {image_source}",
            f"  Database pool     : {self.options.db_pool_size if self.options.db_pool_size is not None else APP_DEFAULT_POOL_SIZE} + "
            f"{self.options.db_max_overflow if self.options.db_max_overflow is not None else APP_DEFAULT_MAX_OVERFLOW} per worker (default 5 + 10); each worker admits that many requests at once",
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
        if self.options.profiling != "none":
            what = ("py-spy samples the backend at the highest load of each scenario" if self.options.profiling == "cpu"
                    else "one backend worker runs under memray (slow); its live heap is reported at the end")
            lines.append(f"  Profiling         : {self.options.profiling}: {what}; adds SYS_PTRACE inside the perf backend container only; latency is not comparable")
        if self.options.watch_url:
            lines.append("  Watch URL         : polled with GET only; the run aborts if it slows or fails")
        return lines

    # docker plumbing ------------------------------------------------------

    def compose_files(self) -> tuple:
        """The compose files this run merges: the isolated stack, plus the profile override in a profiling mode."""
        return COMPOSE_FILES + ((PROFILE_COMPOSE_FILE,) if self.options.profiling != "none" else ())

    def _docker_for_cleanup(self) -> compose.PerfDocker:
        return compose.PerfDocker(self.compose_files(), None, REPO_ROOT, runner=self._runner)

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
        if self.options.profiling != "none":
            return PROFILE_IMAGE, "built"
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
        self.pg_prepare()
        return manifest, {"snapshot_used": used, "generation_seconds": round(generation, 1), "startup_seconds": round(startup, 1)}

    def database_bytes(self) -> int:
        """The database's size in bytes."""
        done = self._exec("db", "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", f"select pg_database_size('{DB_NAME}')")
        return int(done.out.strip()) if done.ok and done.out.strip().isdigit() else 0


    # PostgreSQL profiling ---------------------------------------------------

    def _psql(self, sql: str, timeout: float = 300) -> compose.Result:
        """Runs SQL in the perf database (statements are sent on standard input, never on a command line)."""
        return self._exec("db", "psql", "-U", DB_USER, "-d", DB_NAME, "-X", "-tA", "-v", "ON_ERROR_STOP=1", "-f", "-", input=sql, timeout=timeout)

    def _read_connections(self) -> Optional[tuple]:
        done = self._psql(pgprofile.CONNECTIONS_SQL, timeout=30)
        return pgprofile.parse_connections(done.out) if done.ok else None

    def pg_prepare(self) -> None:
        """Loads `pg_stat_statements`, refreshes planner statistics and records the server's settings (once per run).

        `ANALYZE` stands in for the autovacuum a restored or bulk-loaded database would get within a minute in
        real use; without it the planner's estimates (and so `plans.csv`) describe an empty database. A database
        that cannot load the extension (an old override) is noted once and the PostgreSQL files stay empty.
        """
        done = self._psql(pgprofile.SETUP_SQL)
        self.pg_enabled = done.ok
        if not done.ok:
            if "pg_stat_statements" not in self._noted:
                self._noted.add("pg_stat_statements")
                self.notes.append("pg_stat_statements could not be loaded: pgstat.csv, pgdb.csv and plans.csv are empty")
            return
        if self.pg_settings:
            return
        settings = pgprofile.parse_json(self._psql(pgprofile.SETTINGS_SQL, timeout=30).out)
        if isinstance(settings, dict):
            self.pg_settings = settings
        pool = self._backend_python_code("from app.config import get_settings as g; s = g(); print(s.db_pool_size, s.db_max_overflow)")
        sizes = pool.out.split() if pool.ok else []
        if len(sizes) == 2 and all(part.isdigit() for part in sizes):
            size, overflow = int(sizes[0]), int(sizes[1])
            self.db_pool = {"pool_size": size, "max_overflow": overflow, "connection_ceiling": pgprofile.connection_ceiling(self.workers, size, overflow)}

    def _backend_python_code(self, code: str) -> compose.Result:
        return self._exec("backend", "python", "-c", code, timeout=120)

    def pg_begin(self) -> None:
        """Zeroes the statement totals and starts polling connections, at the start of a scenario."""
        if not self.pg_enabled:
            return
        self._psql(pgprofile.RESET_SQL, timeout=60)
        before = pgprofile.parse_json(self._psql(pgprofile.DATABASE_STATS_SQL, timeout=60).out)
        self._pg_before = before if isinstance(before, dict) else {}
        self._pg_poller = pgprofile.ConnectionPoller(self._read_connections)
        self._pg_poller.start()

    def pg_end(self, tier: str, scenario: str) -> None:
        """Keeps what the database did during the scenario: costliest statements, its own counters, the worst plans."""
        poller, self._pg_poller = self._pg_poller, None
        if not self.pg_enabled or poller is None:
            return
        poller.stop()
        time.sleep(QUERY_FLUSH_SECONDS)
        after = pgprofile.parse_json(self._psql(pgprofile.DATABASE_STATS_SQL, timeout=60).out)
        if isinstance(after, dict) and self._pg_before:
            self.pgdb_rows.append(pgprofile.database_row(tier, scenario, self._pg_before, after, poller.peak, poller.idle_in_transaction_peak))
        statements = pgprofile.parse_json(self._psql(pgprofile.TOP_STATEMENTS_SQL, timeout=120).out)
        if not isinstance(statements, list):
            return
        self.pgstat_rows.extend(pgprofile.statement_rows(tier, scenario, statements))
        planned = 0
        for item in statements:
            if planned >= pgprofile.PLANNED_STATEMENTS:
                break
            sql = pgprofile.explain_sql(item.get("query", ""))
            if not sql:
                continue
            planned += 1
            done = self._psql(sql, timeout=120)
            rows = pgprofile.plan_rows(tier, scenario, planned, pgprofile.parse_json(done.out)) if done.ok else []
            self.plan_rows.extend(rows)

    # profiling ------------------------------------------------------------

    def snapshot(self) -> Optional[dict]:
        """The backend's per-process memory and per-route statement totals, or None when the image cannot say.

        An image built before profile mode existed has no `scripts/profile_tools.py`; the run then has no
        `queries.csv` or `processes.csv` rows and says so once.
        """
        done = self._exec("backend", "python", "scripts/profile_tools.py", "snapshot", timeout=120)
        if done.ok and done.out.strip().startswith("{"):
            return json.loads(done.out)
        if "snapshot" not in self._noted:
            self._noted.add("snapshot")
            self.notes.append("the backend image has no profiling tools (built before profile mode): queries.csv and processes.csv are empty")
        return None

    def record_snapshot(self, tier: str, scenario: str, repeat: int, *, wait: bool = True) -> None:
        """Records process memory and the statements run since the previous snapshot, against this scenario.

        Args:
            tier / scenario / repeat: What just ran (`idle` and repeat 0 for the start of a tier).
            wait: Let the backend's files catch up first (not needed before any load has run).
        """
        if wait:
            time.sleep(QUERY_FLUSH_SECONDS)
        snap = self.snapshot()
        if snap is None:
            return
        for process in snap["processes"]:
            self.process_rows.append({"tier": tier, "scenario": scenario, "repeat": repeat, **process})
        if scenario != "idle":  # the start-of-tier reading is a baseline: what came before it is dataset setup, not a scenario
            totals = self._query_totals.setdefault((tier, scenario), {})
            for route, now in snap["queries"].items():
                before = self._queries_before.get(route, {"requests": 0, "queries": 0, "db_ms": 0.0, "repeat_count": 0})
                requests = now["requests"] - before["requests"]
                if requests <= 0:
                    continue
                entry = totals.setdefault(route, {"requests": 0, "queries": 0, "db_ms": 0.0})
                entry["requests"] += requests
                entry["queries"] += now["queries"] - before["queries"]
                entry["db_ms"] += now["db_ms"] - before["db_ms"]
                # The backend keeps the worst repeat since it started, so only a higher count belongs to this scenario.
                if now["repeat_count"] > before["repeat_count"] and now["repeat_count"] > self.suspects.get(route, {}).get("count", 0):
                    self.suspects[route] = {"statement": now["repeat_statement"], "count": now["repeat_count"]}
        self._queries_before = snap["queries"]

    def query_rows(self) -> list:
        """`queries.csv` rows: mean statements and database milliseconds per request, by tier, scenario and route."""
        rows = []
        for (tier, scenario), routes in self._query_totals.items():
            for route, entry in sorted(routes.items()):
                rows.append({
                    "tier": tier, "scenario": scenario, "request": route, "requests": entry["requests"],
                    "queries_per_request": round(entry["queries"] / entry["requests"], 2), "db_ms_per_request": round(entry["db_ms"] / entry["requests"], 2),
                })
        return rows

    def cpu_profile_seconds(self, params: dict) -> int:
        """How long py-spy samples for a scenario run: its warm-up and measured period, longer for a slow, closed-loop scenario."""
        measured = max(params["measure_seconds"], 60 if params["min_requests"] else 0)
        return int(min(600, params["warmup_seconds"] + measured))

    def start_cpu_profile(self, tier: str, scenario: str, params: dict) -> tuple:
        """Starts py-spy on the backend's process tree in the background.

        py-spy runs as root inside the container: a non-root `exec` process does not inherit the added `SYS_PTRACE`
        capability, and the kernel's ptrace scope would refuse it otherwise.

        Returns:
            `(thread, file name)`; join the thread when the load has finished.
        """
        name = f"cpu-{tier.lower()}-{scenario}-u{params['users']}.svg"
        seconds = self.cpu_profile_seconds(params)

        def sample() -> None:
            self.docker.compose(
                "exec", "-T", "-u", "root", "backend", "py-spy", "record", "--pid", "1", "--subprocesses", "--nonblocking", "--rate", str(CPU_SAMPLE_HZ),
                "--duration", str(seconds), "--format", "flamegraph", "--output", f"/profile/{name}", timeout=seconds + 180,
            )

        thread = threading.Thread(target=sample, daemon=True)
        thread.start()
        return thread, name

    def finish_cpu_profile(self, thread: threading.Thread, name: str, params: dict) -> None:
        """Waits for py-spy, copies its flamegraph out and keeps it with the source paths shortened."""
        thread.join(timeout=self.cpu_profile_seconds(params) + 200)
        destination = self.work / name
        copied = self.docker.compose("cp", f"backend:/profile/{name}", str(destination), timeout=120)
        if not copied.ok or not destination.exists():
            self.notes.append(f"no CPU profile for {name}: py-spy produced nothing (see the plan output for the ptrace requirement)")
            return
        text = destination.read_text(errors="replace")
        for old, new in SOURCE_PATH_REPLACEMENTS:
            text = text.replace(old, new)
        self.profile_files[name] = text

    def finish_heap(self) -> None:
        """Stops the backend so memray finalises its capture, then summarises what the worker still held.

        Heap rows are `package` (by source area) and `location` (by line); the HTML flamegraph is left in the
        profile volume until teardown, since only summarised numbers are kept.
        """
        stopped = self.docker.compose("stop", "-t", str(HEAP_STOP_SECONDS), "backend", timeout=HEAP_STOP_SECONDS + 120)
        if not stopped.ok:
            self.notes.append("the backend did not stop cleanly; no heap profile")
            return
        done = self.docker.compose(
            "run", "--rm", "--no-deps", "-T", "backend", "python", "scripts/profile_tools.py", "--dir", "/profile", "heap", "/profile/heap.bin", timeout=1800,
        )
        if not done.ok or not done.out.strip().startswith("{"):
            self.notes.append("no heap profile: memray's capture could not be read")
            return
        result = json.loads(done.out)
        self.heap_totals = {"heap_live_mib": result["live_mib"], "heap_peak_mib": result["peak_mib"]}
        self.heap_rows = (
            [{"kind": "package", "name": e["name"], "mib": e["mib"], "allocations": e["allocations"]} for e in result["by_package"]]
            + [{"kind": "location", "name": e["name"], "mib": e["mib"], "allocations": e["allocations"]} for e in result["by_location"]]
        )

    def report_suspects(self) -> None:
        """Prints the routes whose requests repeat one statement most (N+1 suspects). Parameterised text only."""
        worst = sorted(self.suspects.items(), key=lambda item: -item[1]["count"])[:5]
        for route, found in worst:
            if found["count"] >= 10:
                self.say(f"  N+1 suspect {route}: one request ran the same statement {found['count']} times: {found['statement'][:160]}")

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
                    self.notes.append(f"backend {kind} by the end of {scenario} at {tier} (restarts {restarts}); its memory cap may be too small for {self.workers} workers")

    def run_scenarios(self, tier: str, manifest: dict, names: list) -> None:
        """Runs every scenario at the tier, `repeats` times, recording latency and sampling resources."""
        per_project = self.summary["tiers"][tier]
        soak_minutes = self.options.soak_minutes if self.options.soak_minutes is not None else 30
        for name in names:
            all_params = catalog.parameters(name, self.options.mode, per_project, tier, self.options.capacity_users, self.options.capacity_tier)
            levels = [p["users"] for p in all_params]
            self.pg_begin()
            climb_ended = False
            for params in all_params:
                if climb_ended:
                    break
                if name == "soak":
                    params = dict(params, measure_seconds=soak_minutes * 60, warmup_seconds=120)
                fixed_repeats = catalog.CATALOG[name].repeats
                for repeat in range(1, (1 if name == "soak" else fixed_repeats or self.repeats()) + 1):
                    self.say(f"  {tier} {name} users={params['users']} repeat={repeat}")
                    self.sampler.tag(tier=tier, scenario=name, repeat=repeat, users=params["users"])
                    cpu = None
                    if self.options.profiling == "cpu" and repeat == 1 and params["users"] == levels[-1]:
                        cpu = self.start_cpu_profile(tier, name, params)
                    summary = self.run_loadgen(manifest, name, params)
                    if cpu:
                        self.finish_cpu_profile(*cpu, params)
                    for row in summary["requests"]:
                        self.latency.append({
                            "tier": tier, "scenario": name, "repeat": repeat, "users": params["users"], "request": row["name"],
                            "count": row["count"], "failures": row["failures"], "throttled": row["throttled"], "p50_ms": row["p50_ms"],
                            "p95_ms": row["p95_ms"], "p99_ms": row["p99_ms"], "mean_ms": row["mean_ms"], "max_ms": row["max_ms"],
                            "rps": row["rps"], "bytes_mean": row["bytes_mean"],
                        })
                    self.check_backend_health(tier, name)
                    self.record_snapshot(tier, name, repeat)
                    if catalog.is_capacity(name):
                        climb_ended = self.capacity_step_ends(tier, params["users"], summary, name)
                        if not climb_ended:
                            self.settle_backend()
            self.pg_end(tier, name)

    def settle_backend(self, limit_seconds: int = 120) -> None:
        """Waits until the backend is idle again (CPU under 10% twice running) before the next capacity level.

        Requests the load generator abandoned when a level ended are still queued in the backend; starting the next
        level behind them would measure the last level's backlog.
        """
        quiet, started = 0, time.monotonic()
        while quiet < 2 and time.monotonic() - started < limit_seconds:
            rows = [r for r in self.sampler.poll_once() if r["service"] == "backend"]
            quiet = quiet + 1 if rows and rows[0]["cpu_percent"] < 10 else 0
            time.sleep(3)
        if quiet < 2:
            self.notes.append(f"the backend was still busy {limit_seconds}s after a capacity level ended; the next level started behind its backlog")

    def capacity_step_ends(self, tier: str, users: int, summary: dict, scenario: str = "capacity") -> bool:
        """Notes one capacity level and says whether the stack is past what it can serve, so higher levels are skipped.

        A level fails the stack when more than `CAPACITY_MAX_FAILURE_RATE` of its requests fail or it delivers under
        `CAPACITY_MIN_DELIVERED` of the offered rate. A saturated load generator is noted too, so a ceiling it caused is
        not read as the backend's.

        Args:
            tier: The tier.
            users: Simulated connections at this level.
            summary: The load generator's summary for the level.
            scenario: The capacity scenario (`capacity` or `capacity_mixed`).

        Returns:
            True when higher levels should not run.
        """
        total = summary["total"]
        count, failures = total["count"], total["failures"]
        offered = users * catalog.CAPACITY_REQUESTS_PER_SECOND
        delivered = (total["rps"] or 0) / offered if offered else 0.0
        failure_rate = failures / count if count else 1.0
        stalled = count == 0
        kinds = summary.get("failure_kinds") or {}
        rows = [r for r in self.sampler.rows if r.get("scenario") == scenario and r.get("users") == users and r.get("tier") == tier]

        def mean_cpu(service: str) -> float:
            values = [r["cpu_percent"] for r in rows if r["service"] == service]
            return sum(values) / len(values) if values else 0.0

        loadgen_cap = self.caps.per_service.get("loadgen", {}).get("cpus") if self.caps else None
        loadgen_cpu = mean_cpu("loadgen")
        saturated = bool(loadgen_cap) and loadgen_cpu >= 0.85 * 100 * float(loadgen_cap)
        line = (f"capacity {tier} {users} connections: offered {offered:.0f} req/s, delivered {delivered * 100:.0f}%, "
                f"{'NO REQUEST COMPLETED, ' if stalled else ''}failures {failure_rate * 100:.1f}%"
                f"{' (' + ', '.join(f'{k}: {v}' for k, v in sorted(kinds.items())) + ')' if kinds else ''}, backend CPU {mean_cpu('backend'):.0f}%, load generator CPU {loadgen_cpu:.0f}%")
        self.say("  " + line)
        stop = failure_rate > catalog.CAPACITY_MAX_FAILURE_RATE or delivered < catalog.CAPACITY_MIN_DELIVERED
        self.notes.append(line + (" (load generator saturated: the ceiling may be its own)" if saturated else "") + ("; stopped here" if stop else ""))
        return stop

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
        self.check_connection_budget(caps)
        self.check_shared_buffers(caps)
        largest = max(self.total_requirements(t) for t in self.tiers())
        self.options.cache_dir.mkdir(parents=True, exist_ok=True)
        reasons = resources.preflight_headroom(
            caps, total_requirements=largest, disk_path=self.options.cache_dir, available=self._available_reader(host),
            thresholds=self.thresholds(),
        )
        if reasons:
            raise RunError("not enough headroom on this host: " + "; ".join(reasons), EX_USAGE)

    def check_connection_budget(self, caps: resources.Caps) -> None:
        """Refuses a worker count and pool whose connections cannot fit PostgreSQL's limit.

        With more connections possible than the server allows, a loaded run fails with connection errors that read as an
        application fault; the operator lowers the pool instead.

        Raises:
            RunError: If `workers x (pool + overflow + 2)` exceeds the usable connections (100 less 3 reserved).
        """
        size = self.options.db_pool_size if self.options.db_pool_size is not None else APP_DEFAULT_POOL_SIZE
        overflow = self.options.db_max_overflow if self.options.db_max_overflow is not None else APP_DEFAULT_MAX_OVERFLOW
        ceiling = pgprofile.connection_ceiling(caps.workers, size, overflow)
        usable = PERF_MAX_CONNECTIONS - pgprofile.RESERVED_CONNECTIONS
        if ceiling > usable:
            room = usable // caps.workers - 2
            raise RunError(
                f"{caps.workers} workers x ({size} + {overflow} + 2) = {ceiling} database connections, more than the {usable} PostgreSQL allows; "
                f"lower the pool, for example --db-pool-size {max(1, room // 3)} --db-max-overflow {max(0, room - max(1, room // 3))}", EX_USAGE,
            )

    def check_shared_buffers(self, caps: resources.Caps) -> None:
        """Refuses a `shared_buffers` the database's memory cap cannot hold (it is allocated up front, and the server also
        needs memory for connections and sorts), which would end the run in an out-of-memory kill.

        Raises:
            RunError: If `shared_buffers` is more than half of the database container's memory limit.
        """
        value = self.options.pg_shared_buffers
        if not value:
            return
        buffers_mib = int(value[:-2]) * (1024 if value.endswith("GB") else 1)
        limit_mib = int(str(caps.per_service["db"]["mem"]).rstrip("m"))
        if buffers_mib * 2 > limit_mib:
            raise RunError(
                f"--pg-shared-buffers {value} is more than half of the database's {limit_mib} MiB memory cap; "
                f"use at most {limit_mib // 2} MiB or raise --max-mem", EX_USAGE,
            )

    def thresholds(self) -> resources.Thresholds:
        """The host-pressure limits for this run (the defaults, with the operator's load limit)."""
        limit = self.options.max_load_per_core
        if limit is None:
            limit = DEDICATED_MAX_LOAD_PER_CORE if self.options.dedicated else resources.Thresholds().max_load_per_core
        return resources.Thresholds(max_load_per_core=limit)

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
        self.workers = caps.workers
        self.caps = caps
        git = git_state(run=self._runner)
        backend_image, image_source = self.choose_images(host, git)
        for line in self.plan_lines(host, caps, f"backend {image_source} ({backend_image.split(':')[0].split('/')[-1]}), load generator built locally"):
            self.say(line)
        if options.plan:
            return 0
        self.preflight(host, caps)

        self.work = Path(tempfile.mkdtemp(prefix=f"{compose.PROJECT}-"))
        self.work.chmod(0o700)
        self.env = stack_environment(caps=caps, workers=caps.workers, backend_image=backend_image, loadgen_image="reqtrack-perf-loadgen:build", generate=self._generate, profiling=options.profiling, db_pool=(options.db_pool_size, options.db_max_overflow), pg=(options.pg_shared_buffers, options.pg_work_mem), memory=(options.malloc_arena_max, options.limit_max_requests))
        env_file = self.work / "perf.env"
        env_file.write_text(render_env_file(self.env))
        env_file.chmod(0o600)
        self.docker = compose.PerfDocker(self.compose_files(), env_file, REPO_ROOT, secrets=[self.env[k] for k in SECRET_KEYS], runner=self._runner)
        self.sampler = sampler.Sampler(self.docker)
        self.watchdog = resources.Watchdog(
            self.thresholds(), options.cache_dir, watch_url=options.watch_url, on_trip=self._on_watchdog,
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
                self.record_snapshot(tier, "idle", 0, wait=False)
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
            if options.profiling == "heap" and status == 0:
                self.finish_heap()
            self.report_suspects()
            if not options.keep:
                self.teardown()
        written = self.write_results(host, git, caps, image_source, started, tiers, names)
        self.results_directory = written
        if written:
            self.say(f"results: {written}")
        return status

    def _dataset_entry(self, tier: str, manifest: dict, details: dict) -> dict:
        return dataset_entry(tier, manifest, self.database_bytes(), details["generation_seconds"])

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
        """Writes the bundle (checked for anything identifying as it is written) and, with `--archive`, a `.tar.gz` beside it
        in the results directory; returns the bundle directory, or None when nothing was measured."""
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
        if self.options.profiling != "none":
            self.notes.append(f"profiling run ({self.options.profiling}): the profiler slows the backend, so latency and throughput are not comparable with an unprofiled run; memory and query counts are")
        if caps.workers_auto and self.options.mode == "full":
            self.notes.append(f"workers chosen automatically ({caps.workers}); not comparable with a run at a different worker count")
        host_doc = dict(host)
        if self.sampler.throttle_flags_seen:
            host_doc["throttle_flags_seen"] = sorted(self.sampler.throttle_flags_seen)
        run_doc = {
            "schema_version": bundle.RUN_SCHEMA_VERSION, "host_label": self.options.label, "commit": git["commit"],
            "date": started.strftime("%Y-%m-%d"), "mode": self.options.mode, "tiers": tiers, "breadth": self.options.breadth,
            "density": self.options.density, "seed": self.options.seed, "profiles_version": self.summary["version"], "scenarios": names,
            "repeats": self.repeats(), "workers": caps.workers, "workers_auto": caps.workers_auto, "image_source": image_source, "caps": caps.as_dict(),
            "shared_host": not self.options.dedicated, "non_publishable": bool(reasons), "non_publishable_reasons": reasons,
            "aborted": self.aborted, "snapshot_used": [d["snapshot_used"] for d in details],
            "startup_seconds": [d["startup_seconds"] for d in details], "profiling": self.options.profiling, "notes": self.notes,
            **({"postgres": self.pg_settings} if self.pg_settings else {}), **({"db_pool": self.db_pool} if self.db_pool else {}),
            **({"backend_memory": {k: v for k, v in (("malloc_arena_max", self.options.malloc_arena_max), ("limit_max_requests", self.options.limit_max_requests)) if v is not None}}
               if self.options.malloc_arena_max is not None or self.options.limit_max_requests is not None else {}),
            **self.heap_totals,
        }
        directory = bundle.unused_bundle_dir(
            bundle.bundle_dir(self.options.out, self.options.label, run_doc["date"], git["commit"] or "0" * 7)
        )
        samples = [row for row in self.sampler.rows if "scenario" in row]
        bundle.write_bundle(
            directory, host=host_doc, run=run_doc, datasets=self.datasets, samples=samples, latency=self.latency, queries=self.query_rows(),
            pgstat=self.pgstat_rows, pgdb=self.pgdb_rows, plans=self.plan_rows, processes=self.process_rows, heap=self.heap_rows, profiles=self.profile_files,
        )
        self.say(f"bundle: {directory}")
        if self.options.archive:
            self.say(f"archive: {bundle.make_archive(directory)}")
        return directory


def dataset_entry(tier: str, manifest: dict, database_bytes: int, generation_seconds: float) -> dict:
    """The `dataset.json` entry for one tier: the generated dataset's spec, row counts, link statistics and size.

    Every key must be in `lib.scrub.DATASET_ENTRY_KEYS`, or the bundle fails its anonymisation check; a test builds
    this from a real generated manifest and writes it, so a key added here without the allowlist is caught in CI.
    """
    return {
        "tier": tier, "spec": manifest["spec"], "rows": manifest["rows"],
        "link_degree_histogram": manifest["link_degree_histogram"], "link_pairs": manifest.get("link_pairs", {}),
        "integrity_problems": manifest["integrity_problems"], "database_bytes": database_bytes,
        "generation_seconds": generation_seconds,
    }


def sweep_pool(options: Options) -> Options:
    """The options with one database pool for every run of a worker sweep: the application's default if the largest
    count fits PostgreSQL's connections with it, else the largest pool that does, so only the worker count varies.

    Returns:
        `options` unchanged when the operator chose a pool or the default fits, else a copy with the pool set.
    """
    if options.db_pool_size is not None or options.db_max_overflow is not None:
        return options
    largest = max(options.worker_sweep)
    usable = PERF_MAX_CONNECTIONS - pgprofile.RESERVED_CONNECTIONS
    if pgprofile.connection_ceiling(largest, APP_DEFAULT_POOL_SIZE, APP_DEFAULT_MAX_OVERFLOW) <= usable:
        return options
    room = usable // largest - 2
    size = max(1, room // 3)
    return dataclasses.replace(options, db_pool_size=size, db_max_overflow=max(0, room - size))


def run_sweep(options: Options) -> int:
    """Runs the profile once per worker count, in order, each as its own run and bundle.

    Stops at the first run that fails or aborts (a host under pressure should not be asked for the next one) and
    prints where the bundles are and how to compare them.

    Returns:
        0 when every run finished, else the first non-zero status.
    """
    options = sweep_pool(options)
    results = []
    for count in options.worker_sweep:
        print(f"=== worker sweep: {count} workers (of {', '.join(str(n) for n in options.worker_sweep)}) ===", flush=True)
        run = ProfileRun(dataclasses.replace(options, workers=count, worker_sweep=None))
        try:
            status = run.execute()
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            status = exc.code
        if run.results_directory:
            results.append(run.results_directory)
        if status != 0:
            print(f"worker sweep stopped after {count} workers (exit {status})", file=sys.stderr)
            break
    if results and not options.plan:
        print("compare the runs: python3 perf/analyse.py --workers " + " ".join(str(d) for d in results))
    return status if results or options.plan else (status or EX_USAGE)


def main(argv: Optional[list] = None) -> int:
    """Entry point; returns the process exit status."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if options.worker_sweep:
            return run_sweep(options)
        return ProfileRun(options).execute()
    except RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (hostinfo.HostInfoError, resources.ResourceError, bundle.BundleError, compose.UnsafeCommand) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EX_USAGE


if __name__ == "__main__":
    sys.exit(main())
