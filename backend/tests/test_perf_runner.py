"""Tests for the performance runner (`perf/`): the safety properties that let it run on a host that also serves
production, and the anonymisation of what it writes.

Covered: every Docker command it can emit is scoped to the `reqtrack-perf` project (prune, image removal and
foreign resources are refused), the environment Docker sees is scrubbed, the runner has no option that names a
database, API or compose file, credentials and caps are generated per run, host information is allowlisted and
generic, the bundle checker fails on each kind of identifying content, the archive carries no owner or time,
the scenario catalogue matches the load generator, and the headroom preflight and watchdog trip as stated.

The runner drives `docker compose`; these tests replace the process runner with a scripted fake, so they need no
Docker. The real thing is exercised end to end by running `perf/run_profile.sh`. The `perf/` directory sits next
to `backend/` (or is mounted at `/perf` in the backup-image test run); the tests skip when it is absent.
"""

from __future__ import annotations

import ast
import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

_PERF = Path(__file__).resolve().parents[2] / "perf"
if not (_PERF / "run_profile.py").is_file():
    pytest.skip("perf/ is not available in this environment", allow_module_level=True)
sys.path.insert(0, str(_PERF.parent))

from perf import run_profile  # noqa: E402
from perf.lib import bundle, catalog, compose, hostinfo, resources, sampler, scrub  # noqa: E402

COMPOSE_FILES = [str(p) for p in run_profile.COMPOSE_FILES]


def _docker(runner=None, environ=None, secrets=()):
    return compose.PerfDocker(
        run_profile.COMPOSE_FILES, Path("/tmp/perf.env"), run_profile.REPO_ROOT, secrets=secrets, runner=runner or _fake(), environ=environ or {}
    )


def _fake(stdout: str = "", code: int = 0, calls: list | None = None):
    def run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, code, stdout, "")

    return run


# --- the command builder ---------------------------------------------------------------------------------


def test_every_compose_command_carries_the_perf_project_and_only_the_runners_files():
    docker = _docker()
    for args in (
        ("up", "-d", "db"),
        ("down", "-v", "--remove-orphans"),
        ("exec", "-T", "db", "psql"),
        ("run", "--rm", "loadgen"),
        ("build", "backend"),
        ("pull", "backend"),
    ):
        argv = docker.compose_argv(*args, profiles=("loadgen",))
        assert argv[:4] == ["docker", "compose", "-p", "reqtrack-perf"]
        compose.validate_argv(argv, COMPOSE_FILES + ["/tmp/perf.env"])


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "system", "prune", "-f"],
        ["docker", "volume", "prune", "-f"],
        ["docker", "image", "prune", "-a"],
        ["docker", "compose", "-p", "reqtrack-perf", "down", "--rmi", "all"],
        ["docker", "compose", "-p", "other", "up", "-d"],
        ["docker", "compose", "up", "-d"],
        ["docker", "compose", "-p", "reqtrack-perf", "-p", "other", "up"],
        ["docker", "compose", "-p", "reqtrack-perf", "-f", "/etc/production/docker-compose.yml", "up"],
        ["docker", "compose", "-p", "reqtrack-perf", "--env-file", "/srv/prod/.env", "up"],
        ["docker", "compose", "-p", "reqtrack-perf", "--context", "x", "up"],
        ["docker", "compose", "-p", "reqtrack-perf", "rm", "-f"],
        ["docker", "rm", "-f", "reqtrack-db-1"],
        ["docker", "rm", "-f", "reqtrack-perf-db-1", "production-db-1"],
        ["docker", "volume", "rm", "reqtrack_db_data"],
        ["docker", "network", "rm", "reqtrack_default"],
        ["docker", "stop", "backend"],
        ["docker", "run", "--rm", "alpine"],
        ["docker", "exec", "reqtrack-perf-db-1", "sh"],
        ["docker", "rmi", "reqtrack-perf-backend"],
        ["sh", "-c", "docker rm -f x"],
    ],
)
def test_commands_that_could_reach_outside_the_perf_project_are_refused(argv):
    with pytest.raises(compose.UnsafeCommand):
        compose.validate_argv(argv, COMPOSE_FILES + ["/tmp/perf.env"])


def test_destructive_commands_on_perf_resources_are_allowed():
    compose.validate_argv(["docker", "rm", "-f", "-v", "reqtrack-perf-db-1", "reqtrack-perf-storage-1"])
    compose.validate_argv(["docker", "volume", "rm", "reqtrack-perf_reqtrack_db_data"])
    compose.validate_argv(["docker", "network", "rm", "reqtrack-perf_default"])


def test_the_runner_refuses_to_execute_an_unsafe_command_and_never_calls_the_process():
    calls: list = []
    docker = _docker(runner=_fake(calls=calls))
    with pytest.raises(compose.UnsafeCommand):
        docker.docker("system", "prune", "-f")
    assert calls == []


def test_docker_runs_with_a_scrubbed_environment():
    calls: list = []
    leaked = {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "COMPOSE_FILE": "/prod/compose.yml",
        "COMPOSE_PROJECT_NAME": "prod",
        "POSTGRES_PASSWORD": "prod-secret",
        "JWT_SECRET": "prod-jwt",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "AWS_SECRET_ACCESS_KEY": "x",
    }
    docker = _docker(runner=_fake(calls=calls), environ=leaked)
    docker.docker("info")
    env = calls[0][1]["env"]
    assert set(env) == {"PATH", "HOME", "DOCKER_HOST"}


def test_secrets_are_masked_in_what_a_command_returns():
    docker = _docker(runner=_fake(stdout="the password is sup3r-secret-value"), secrets=["sup3r-secret-value"])
    assert "sup3r-secret-value" not in docker.docker("info").out


def test_leftover_removal_names_only_labelled_perf_resources():
    calls: list = []

    def run(argv, **kwargs):
        calls.append(argv)
        listing = {"ps": "reqtrack-perf-db-1\n", "volume": "reqtrack-perf_vol\n", "network": "reqtrack-perf_default\n"}
        return subprocess.CompletedProcess(argv, 0, listing.get(argv[1], "") if argv[1] != "rm" else "", "")

    docker = _docker(runner=run)
    removed = docker.remove_leftovers()
    assert removed == ["reqtrack-perf-db-1", "reqtrack-perf_default", "reqtrack-perf_vol"]
    destructive = [a for a in calls if a[1] in ("rm",) or a[1:3] in (["volume", "rm"], ["network", "rm"])]
    targets = [t for a in destructive for t in a[1:] if not t.startswith("-") and t not in ("rm", "network", "volume")]
    assert targets and all(t.startswith("reqtrack-perf") for t in targets)
    assert not any("prune" in a for a in calls)


def test_a_resource_with_the_perf_prefix_but_another_project_label_is_reported_as_foreign():
    def run(argv, **kwargs):
        out = {"ps": "reqtrack-perf-db-1|reqtrack-perf\nreqtrack-perf-thing-1|someone-else\n"}.get(argv[1], "")
        return subprocess.CompletedProcess(argv, 0, out, "")

    assert _docker(runner=run).foreign_resources() == ["container reqtrack-perf-thing-1"]


# --- the runner's command line and stack definition ------------------------------------------------------


def test_the_runner_has_no_option_that_names_a_database_api_project_or_file():
    parser_source = (_PERF / "run_profile.py").read_text()
    options = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', parser_source))
    forbidden = {
        "--database",
        "--database-url",
        "--db",
        "--url",
        "--api-url",
        "--target",
        "--host",
        "--project",
        "--compose-file",
        "--file",
        "--env-file",
        "--port",
    }
    assert not options & forbidden
    assert "--watch-url" in options  # the one URL: polled with GET only, no credentials
    assert "database_url" not in parser_source.lower().replace("database_bytes", "")
    assert "os.environ" not in parser_source  # credentials are never read from the operator's environment


def test_the_load_generator_can_only_reach_the_stacks_backend():
    source = (_PERF / "loadgen" / "run.py").read_text()
    assert 'TARGET = "http://backend:8000"' in source
    assert not re.findall(r"add_argument|sys\.argv|os\.environ\[?\.?get?\(?['\"](?:URL|HOST|TARGET)", source)


def test_credentials_are_generated_per_run_and_distinct():
    caps = resources.plan_caps(8, 16, max_mem_gib=5)
    counter = iter(range(1000))
    first = run_profile.stack_environment(
        caps=caps,
        workers=4,
        backend_image="reqtrack-perf-backend:build",
        loadgen_image="reqtrack-perf-loadgen:build",
        generate=lambda: f"s{next(counter)}",
    )
    second = run_profile.stack_environment(caps=caps, workers=4, backend_image="x", loadgen_image="y", generate=lambda: f"s{next(counter)}")
    secrets_first = [first[k] for k in run_profile.SECRET_KEYS]
    assert (
        len(
            {
                first["POSTGRES_PASSWORD"],
                first["JWT_SECRET"],
                first["APP_SECRET_ENCRYPTION_KEY"],
                first["SERVER_ADMIN_PASSWORD"],
                first["PERF_USER_PASSWORD"],
            }
        )
        == 5
    )
    assert not set(secrets_first) & {second[k] for k in run_profile.SECRET_KEYS if k != "STORAGE_ROOT_PASSWORD"}
    assert first["SMTP_HOST"].endswith(".invalid")
    assert first["BACKEND_WORKERS"] == "4"


def test_generated_credentials_are_random_by_default():
    caps = resources.plan_caps(8, 16, max_mem_gib=5)
    a = run_profile.stack_environment(caps=caps, workers=4, backend_image="a", loadgen_image="b")
    b = run_profile.stack_environment(caps=caps, workers=4, backend_image="a", loadgen_image="b")
    assert a["POSTGRES_PASSWORD"] != b["POSTGRES_PASSWORD"] and len(a["JWT_SECRET"]) >= 24


def test_env_file_refuses_a_value_that_could_break_out():
    assert "A=b" in run_profile.render_env_file({"A": "b"})
    for bad in ("a\nb", 'a"b', "a'b", "a$b"):
        with pytest.raises(run_profile.RunError):
            run_profile.render_env_file({"A": bad})


def test_the_compose_override_publishes_nothing_names_nothing_and_uses_perf_only_images():
    text = (_PERF / "docker-compose.perf.yml").read_text()
    assert re.search(r"backend:\n(?:.*\n)*?\s+ports: !reset \[\]", text)
    assert "container_name: !reset null" in text
    assert not re.search(r"^\s+container_name: (?!!reset)", text, re.M)
    assert not re.search(r"^\s+ports:\s*\n\s+-", text, re.M)
    assert "ghcr.io" not in text and "reqtrack-perf-backend" in text and "reqtrack-perf-loadgen" in text
    assert "EMAIL_DELIVERY: disabled" in text and 'PERF_STACK: "1"' in text
    for service in ("db", "storage", "backend", "loadgen"):
        assert re.search(rf"^  {service}:\n(?:(?!^  \w).*\n)*?\s+memswap_limit:", text, re.M), f"{service} has no swap cap"


def test_caps_env_matches_the_variables_the_override_reads():
    text = (_PERF / "docker-compose.perf.yml").read_text()
    wanted = set(re.findall(r"\$\{(PERF_[A-Z_]+)", text))
    provided = set(resources.plan_caps(8, 16, max_mem_gib=5).env()) | {"PERF_USER_PASSWORD", "PERF_BACKEND_IMAGE", "PERF_LOADGEN_IMAGE"}
    assert wanted <= provided


# --- caps, headroom and the watchdog ---------------------------------------------------------------------


def test_default_caps_are_a_fraction_of_the_host_and_dedicated_raises_them():
    shared = resources.plan_caps(8, 32)
    dedicated = resources.plan_caps(8, 32, dedicated=True)
    assert shared.cpus == 4 and shared.memory_gib == 8
    assert dedicated.cpus == 8 and dedicated.memory_gib > shared.memory_gib
    assert resources.plan_caps(12, 12, docker_vm=True).memory_gib == 6
    total = sum(int(v["mem"].rstrip("m")) for v in shared.per_service.values())
    assert total <= shared.memory_gib * 1024


def test_the_backends_cap_covers_its_workers_or_the_budget_is_refused():
    caps = resources.plan_caps(8, 32, workers=4)
    backend_mib = int(caps.per_service["backend"]["mem"].rstrip("m"))
    assert backend_mib >= resources.backend_floor_gib(4) * 1024
    assert resources.minimum_budget_gib(4) > resources.minimum_budget_gib(2)
    with pytest.raises(resources.ResourceError, match="4 backend workers"):
        resources.plan_caps(8, 32, max_mem_gib=3, workers=4)
    assert resources.plan_caps(8, 32, max_mem_gib=3.2, workers=2).memory_gib == 3.2


def test_workers_are_chosen_from_the_budget_up_to_the_production_default():
    assert resources.auto_workers(cpus=8, memory_gib=16) == 4  # never beyond the default
    assert resources.auto_workers(cpus=2, memory_gib=16) == 2  # limited by CPUs
    assert resources.auto_workers(cpus=8, memory_gib=3.2) == 2  # limited by memory
    assert resources.auto_workers(cpus=8, memory_gib=resources.minimum_budget_gib(1)) == 1
    with pytest.raises(resources.ResourceError, match="even with one backend worker"):
        resources.auto_workers(cpus=8, memory_gib=2.0)


def test_every_chosen_worker_count_fits_its_own_budget():
    for memory in (3.1, 3.6, 4.1, 5, 8, 32):
        for cpus in (1, 2, 4, 8):
            caps = resources.plan_caps(16, 64, max_cpus=cpus, max_mem_gib=memory)
            assert caps.workers_auto and 1 <= caps.workers <= 4
            assert int(caps.per_service["backend"]["mem"].rstrip("m")) >= resources.backend_floor_gib(caps.workers) * 1024 - 1


def test_a_named_worker_count_the_backends_share_cannot_hold_is_refused():
    with pytest.raises(resources.ResourceError, match="workers need"):
        resources.plan_caps(16, 64, max_mem_gib=4.1, workers=4)  # the other services take a share, leaving under 2.5 GiB


def test_a_named_worker_count_is_kept_and_not_marked_automatic():
    caps = resources.plan_caps(16, 64, max_mem_gib=8, workers=3)
    assert caps.workers == 3 and not caps.workers_auto
    assert resources.plan_caps(16, 64, max_mem_gib=8).workers == 4


def test_the_workers_option_accepts_a_number_or_auto_and_defaults_to_auto():
    assert run_profile.parse_args(["x-host-label"]).workers is None
    assert run_profile.parse_args(["x-host-label", "--workers", "auto"]).workers is None
    assert run_profile.parse_args(["x-host-label", "--workers", "2"]).workers == 2
    for bad in ("0", "-1", "two"):
        with pytest.raises(SystemExit):
            run_profile.parse_args(["x-host-label", "--workers", bad])


def test_caps_refuse_a_budget_the_stack_cannot_run_in_or_the_host_cannot_give():
    with pytest.raises(resources.ResourceError, match="below"):
        resources.plan_caps(8, 8)
    with pytest.raises(resources.ResourceError, match="more than"):
        resources.plan_caps(4, 8, max_cpus=16)
    with pytest.raises(resources.ResourceError, match="more than"):
        resources.plan_caps(4, 8, max_mem_gib=64)


def test_headroom_preflight_names_each_shortfall():
    caps = resources.plan_caps(8, 16, max_mem_gib=5, max_cpus=4)
    ok = dict(load=lambda: 0.1, available=lambda: 12.0, swap=lambda: 0.0, free_disk=lambda p: 100.0)
    assert resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **ok) == []
    busy = resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **{**ok, "load": lambda: 3.0})
    low_memory = resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **{**ok, "available": lambda: 4.5})
    swapping = resources.preflight_headroom(
        caps, total_requirements=1000, disk_path=Path("/"), **{**ok, "swap": lambda: 3.0, "available": lambda: 8.0},
    )
    full = resources.preflight_headroom(caps, total_requirements=20000, disk_path=Path("/"), **{**ok, "free_disk": lambda p: 8.0})
    assert "busy" in busy[0] and "memory" in low_memory[0] and "swap" in swapping[0] and "disk" in full[0]


def test_existing_swap_is_accepted_when_memory_after_the_caps_could_absorb_it():
    """A long-running server holds idle pages in swap; that alone is not pressure. 2 GiB of swap, 21 GiB available."""
    caps = resources.plan_caps(8, 32, max_mem_gib=7, max_cpus=4)
    ok = dict(load=lambda: 0.1, available=lambda: 21.0, swap=lambda: 2.0, free_disk=lambda p: 100.0)
    assert resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **ok) == []
    tight = resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **{**ok, "available": lambda: 9.0})
    assert tight and "swap" in tight[0]


def test_watchdog_trips_on_each_pressure_signal_and_calls_back_once():
    base = {"load": lambda: 0.1, "available": lambda: 8.0, "swap": lambda: 0.0, "free_disk": lambda p: 50.0}
    tripped: list = []
    for name, reader, text in (
        ("available", lambda: 0.2, "memory"),
        ("free_disk", lambda p: 1.0, "disk"),
    ):
        dog = resources.Watchdog(resources.Thresholds(), Path("/"), readers={**base, name: reader}, on_trip=tripped.append)
        assert text in dog.check_once() and dog.tripped
    healthy = resources.Watchdog(resources.Thresholds(), Path("/"), readers=base)
    assert healthy.check_once() is None and not healthy.tripped


def test_watchdog_trips_on_sustained_load_not_on_a_spike():
    load = [3.0]
    readers = {"load": lambda: load[0], "available": lambda: 20.0, "swap": lambda: 0.0, "free_disk": lambda p: 50.0}
    dog = resources.Watchdog(resources.Thresholds(load_samples=3), Path("/"), readers=readers)
    assert dog.check_once() is None and dog.check_once() is None
    load[0] = 0.5
    assert dog.check_once() is None, "a spike that ends resets the count"
    load[0] = 3.0
    assert dog.check_once() is None and dog.check_once() is None
    assert "stayed above" in dog.check_once() and dog.tripped
    # The operator's limit is respected.
    relaxed = resources.Watchdog(resources.Thresholds(max_load_per_core=4.0, load_samples=1), Path("/"), readers=readers)
    assert relaxed.check_once() is None


def test_watchdog_trips_on_swap_growth_not_on_swap_already_in_use():
    swap = [2.0]
    readers = {"load": lambda: 0.1, "available": lambda: 20.0, "swap": lambda: swap[0], "free_disk": lambda p: 50.0}
    dog = resources.Watchdog(resources.Thresholds(), Path("/"), readers=readers)
    assert dog.check_once() is None, "2 GiB already in swap when sampling began is the baseline, not pressure"
    swap[0] = 2.1
    assert dog.check_once() is None, "growth inside the allowance"
    swap[0] = 2.6
    assert "grew" in dog.check_once() and dog.tripped
    # The baseline can be given up front (the runner takes it when sampling starts).
    started = resources.Watchdog(resources.Thresholds(), Path("/"), readers={**readers, "swap": lambda: 5.0}, swap_baseline=1.0)
    assert "grew" in started.check_once()


def test_watchdog_aborts_after_consecutive_slow_probes_of_the_watched_url():
    answers = iter([(True, 0.1), (False, 1.0), (True, 9.0), (True, 9.0), (True, 9.0)])
    base = {"load": lambda: 0.1, "available": lambda: 8.0, "swap": lambda: 0.0, "free_disk": lambda p: 50.0, "probe": lambda: next(answers)}
    dog = resources.Watchdog(resources.Thresholds(), Path("/"), watch_url="http://watched.invalid/health", readers=base)
    results = [dog.check_once() for _ in range(5)]
    assert results[:4] == [None, None, None, "the watched health URL was slow or failing 3 times in a row"] or results[3] is not None


# --- host information ------------------------------------------------------------------------------------


def _docker_info_runner(os_name="Ubuntu 24.04.1 LTS", arch="aarch64"):
    def run(argv, **kwargs):
        if argv[:3] == ["docker", "info", "--format"]:
            return subprocess.CompletedProcess(argv, 0, f"8|16777216000|{os_name}|29.8.1|{arch}\n", "")
        if argv[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(argv, 0, "v5.5.1\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "")

    return run


def test_host_information_is_generic_and_contains_no_identifying_output():
    document = hostinfo.collect(storage="ssd", run=_docker_info_runner())
    assert document["arch"] == "arm64" and document["os"] == "ubuntu-24" and document["compose_version"] == "5.5.1"
    assert document["docker_ram_gib"] == 15.6 and document["storage"] == "ssd"
    text = json.dumps(document)
    for identifying in (socket_name() if (socket_name := lambda: __import__("socket").gethostname()) else "",):
        assert identifying.lower() not in text.lower() or len(identifying) < 3
    assert set(document) <= scrub.ALLOWED_FILES["host.json"]


def test_host_information_never_copies_raw_tool_output():
    leaking = "Docker Desktop 192.168.1.5 jane-macbook /Users/someone"

    def run(argv, **kwargs):
        if argv[:3] == ["docker", "info", "--format"]:
            return subprocess.CompletedProcess(argv, 0, f"8|16777216000|{leaking}|29.8.1|x86_64\n", "")
        return subprocess.CompletedProcess(argv, 0, "v5.5.1\n", "")

    document = hostinfo.collect(storage="ssd", run=run)
    text = json.dumps(document)
    assert "someone" not in text and "192.168" not in text and "jane" not in text
    assert document["os"] == "docker-desktop"


def test_docker_output_with_an_unexpected_shape_is_refused_rather_than_guessed_at():
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "8|1|serial: 1000abcd|AA:BB:CC:DD:EE:FF|extra|x86_64\n", "")

    with pytest.raises(hostinfo.HostInfoError, match="unexpected shape"):
        hostinfo.collect(storage="ssd", run=run)


def test_a_value_that_is_not_a_short_generic_token_is_refused():
    with pytest.raises(hostinfo.HostInfoError):
        hostinfo.collect(
            storage="ssd",
            run=lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, "8|16777216000|Ubuntu 24.04|29.8.1 /home/someone/x|x86_64\n" if argv[:2] == ["docker", "info"] else "v1.0.0\n", ""
            ),
        )


@pytest.mark.parametrize(("machine", "expected"), [("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64"), ("riscv64", "other")])
def test_architecture_names(machine, expected):
    assert hostinfo.normalise_arch(machine) == expected


def test_cpu_family_is_reduced_to_a_generic_name():
    assert hostinfo.cpu_family(brand="Apple M3 Max") == "apple"
    assert hostinfo.cpu_family("model name : Intel(R) Xeon(R) CPU E5-2680") == "intel"
    assert hostinfo.cpu_family("CPU part\t: 0xd0b\nSerial\t\t: 10000000abcdef12") == "arm-cortex-a76"
    assert "10000000" not in hostinfo.cpu_family("CPU part\t: 0xd0b\nSerial\t\t: 10000000abcdef12")


def test_host_label_rules():
    assert hostinfo.validate_label("rpi5-8g") == "rpi5-8g"
    for bad in ("RPI5", "ab", "has space", "-leading", "x" * 40, "a_b_c"):
        with pytest.raises(hostinfo.HostInfoError):
            hostinfo.validate_label(bad)
    import socket

    name = socket.gethostname().split(".")[0].lower()
    if len(name) >= 3 and re.match(r"^[a-z0-9-]+$", name):
        with pytest.raises(hostinfo.HostInfoError, match="hostname"):
            hostinfo.validate_label(f"{name}-lab")


# --- the anonymisation check -----------------------------------------------------------------------------


def _clean_bundle(directory: Path) -> Path:
    host = hostinfo.collect(storage="ssd", run=_docker_info_runner())
    run = {
        "schema_version": 1,
        "host_label": "linux-vm-4c8g",
        "commit": "a" * 40,
        "date": "2026-10-25",
        "mode": "quick",
        "tiers": ["T0"],
        "scenarios": ["browse"],
        "notes": [],
    }
    dataset = {
        "tier": "T0",
        "spec": {"tier": "T0"},
        "rows": {"requirements": 30},
        "link_degree_histogram": {"max": 7},
        "integrity_problems": [],
        "database_bytes": 1,
        "generation_seconds": 1.0,
    }
    latency = [
        {
            "tier": "T0",
            "scenario": "browse",
            "repeat": 1,
            "users": 4,
            "request": "GET /projects",
            "count": 10,
            "failures": 0,
            "throttled": 0,
            "p50_ms": 5,
            "p95_ms": 9,
            "p99_ms": 12,
            "mean_ms": 6,
            "max_ms": 13,
            "rps": 2.0,
            "bytes_mean": 100,
        }
    ]
    samples = [
        {
            "tier": "T0",
            "scenario": "browse",
            "repeat": 1,
            "service": "backend",
            "t_seconds": 1.0,
            "mem_mib": 400.0,
            "mem_limit_mib": 2000.0,
            "cpu_percent": 3.0,
        }
    ]
    bundle.write_bundle(directory, host=host, run=run, datasets=[dataset], samples=samples, latency=latency)
    return directory


def test_a_clean_bundle_passes_and_every_file_is_on_the_allowlist(tmp_path):
    directory = _clean_bundle(tmp_path / "linux-vm-4c8g" / "2026-10-25-aaaaaaaa")
    assert scrub.scan_tree(directory, identities=["someoneelse"]) == []
    assert {p.name for p in directory.iterdir()} <= set(scrub.ALLOWED_FILES)


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        ("/Users/jane/git/x", "home-directory"),
        ("/home/pi/x", "home-directory"),
        ("aa:bb:cc:dd:ee:ff", "MAC"),
        ("10.1.2.3", "IPv4"),
        ("fe80:0:0:0:1:2:3:4", "IPv6"),
        ("2001:db8::1", "IPv6"),
        ("jane@example.com", "email"),
        ("Serial : 100000001234abcd", "serial"),
        ("0123456789abcdef0123456789abcdef", "hex id"),
        ("ghp_" + "a" * 30, "GitHub"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ", "JWT"),
        ("AKIAABCDEFGHIJKLMNOP", "AWS"),
        ("Authorization: Bearer abcdefghijklmnop1234", "bearer"),
        ("-----BEGIN PRIVATE KEY-----", "private key"),
        ("password=hunter2hunter2", "password"),
        ("my-laptop-name", "hostname"),
    ],
)
def test_each_kind_of_identifying_content_fails_the_check(tmp_path, content, rule):
    directory = _clean_bundle(tmp_path / "b")
    run_file = directory / "run.json"
    document = json.loads(run_file.read_text())
    document["notes"] = [content]
    run_file.write_text(json.dumps(document))
    findings = scrub.scan_tree(directory, identities=["my-laptop-name"])
    assert findings, f"{content!r} was not caught"
    assert all(content not in str(f) for f in findings), "a finding must not echo the matched text"


def test_a_time_a_version_and_a_commit_are_not_mistaken_for_identifiers(tmp_path):
    directory = _clean_bundle(tmp_path / "b")
    document = json.loads((directory / "run.json").read_text())
    document["notes"] = ["started 12:30:45", "docker 29.8.1", "python 3.12", "commit " + "a" * 40]
    (directory / "run.json").write_text(json.dumps(document))
    assert scrub.scan_tree(directory, identities=[]) == []


def test_a_file_or_field_outside_the_allowlist_fails(tmp_path):
    directory = _clean_bundle(tmp_path / "b")
    (directory / "notes.txt").write_text("hi")
    (directory / "link").symlink_to(directory / "run.json")
    document = json.loads((directory / "host.json").read_text())
    document["hostname"] = "x"
    (directory / "host.json").write_text(json.dumps(document))
    rules = " ".join(str(f) for f in scrub.scan_tree(directory, identities=[]))
    assert "not on the allowlist" in rules and "symbolic link" in rules and "outside the allowlist" in rules


def test_the_writer_refuses_a_field_outside_the_allowlist(tmp_path):
    with pytest.raises(bundle.BundleError, match="allowlist"):
        bundle.write_bundle(tmp_path / "b", host={"schema_version": 1, "hostname": "x"}, run={}, datasets=[], samples=[], latency=[])


def test_the_writer_refuses_a_bundle_that_fails_the_check(tmp_path):
    host = hostinfo.collect(storage="ssd", run=_docker_info_runner())
    with pytest.raises(bundle.BundleError, match="anonymisation"):
        bundle.write_bundle(tmp_path / "b", host=host, run={"schema_version": 1, "notes": ["/Users/someone/x"]}, datasets=[], samples=[], latency=[])


def test_the_archive_carries_no_owner_or_time_and_is_reproducible(tmp_path):
    directory = _clean_bundle(tmp_path / "linux-vm-4c8g" / "2026-10-25-aaaaaaaa")
    first = bundle.make_archive(directory, tmp_path / "one.tar.gz")
    (directory / "run.json").touch()
    second = bundle.make_archive(directory, tmp_path / "two.tar.gz")
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(first.read_bytes()))) as tar:
        members = tar.getmembers()
        assert members and all(m.uid == 0 and m.gid == 0 and m.uname == "" and m.gname == "" and m.mtime == 0 for m in members)
        assert [m.name for m in members] == sorted(m.name for m in members)


def test_the_archive_is_refused_for_a_dirty_bundle(tmp_path):
    directory = _clean_bundle(tmp_path / "b")
    (directory / "extra.txt").write_text("x")
    with pytest.raises(bundle.BundleError, match="refusing"):
        bundle.make_archive(directory, tmp_path / "x.tar.gz")


def test_committed_results_pass_the_check():
    results = _PERF / "results"
    assert scrub.scan_tree(results) == []


# --- catalogue, sampler and profile reading --------------------------------------------------------------


def test_the_catalogue_names_exactly_the_scenarios_the_load_generator_defines():
    tree = ast.parse((_PERF / "loadgen" / "scenarios.py").read_text())
    defined = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SCENARIOS":
            defined = {key.value for key in node.value.keys}
    assert defined == set(catalog.CATALOG)


def test_quick_mode_is_short_and_full_mode_adds_the_heavy_ones_and_the_soak():
    quick = catalog.scenarios_for("quick", allow_heavy=False, nested=False, soak=False)
    assert "soak" not in quick and not any(catalog.CATALOG[n].heavy for n in quick)
    full = catalog.scenarios_for("full", allow_heavy=True, nested=True, soak=True)
    assert {"report_pdf", "bundle_import", "project_scope", "soak"} <= set(full)
    assert "report_pdf" not in catalog.scenarios_for("full", allow_heavy=False, nested=False, soak=True)
    assert "project_scope" not in catalog.scenarios_for("full", allow_heavy=True, nested=False, soak=False)


def test_the_csv_import_preview_is_skipped_above_the_endpoints_row_limit():
    assert catalog.parameters("import_preview", "full", 5000)
    assert catalog.parameters("import_preview", "full", 5001) == []
    assert catalog.parameters("browse", "quick", 20000)[0]["users"] == 4


def test_docker_stats_lines_are_parsed_to_services_and_mebibytes():
    row = sampler.parse_stats_line("reqtrack-perf-backend-1|1.5GiB / 3GiB|123.4%")
    assert row == {"service": "backend", "mem_mib": 1536.0, "mem_limit_mib": 3072.0, "cpu_percent": 123.4}
    assert sampler.parse_stats_line("reqtrack-perf-loadgen-run-1a2b3c|200MiB / 1GiB|5.0%")["service"] == "loadgen"
    assert sampler.parse_stats_line("production-db-1|1GiB / 2GiB|1%") is None
    assert sampler.parse_stats_line("garbage") is None


def test_the_sampler_tags_rows_with_seconds_since_the_scenario_and_never_a_container_name():
    clock = iter([0.0, 5.0, 12.0, 20.0, 30.0])

    def run(argv, **kwargs):
        if argv[1] == "ps":
            return subprocess.CompletedProcess(argv, 0, "reqtrack-perf-backend-1\n", "")
        return subprocess.CompletedProcess(argv, 0, "reqtrack-perf-backend-1|400MiB / 3GiB|10%\n", "")

    taker = sampler.Sampler(_docker(runner=run), clock=lambda: next(clock), flags=lambda: "0x50005")
    taker.tag(tier="T1", scenario="browse", repeat=1)
    rows = taker.poll_once()
    assert rows[0]["t_seconds"] == 12.0 - 5.0 and rows[0]["tier"] == "T1" and "name" not in rows[0]
    assert taker.throttle_flags_seen == {"0x50005"}


def test_the_profile_summary_read_without_yaml_matches_the_yaml_file():
    yaml = pytest.importorskip("yaml")
    text = (_PERF / "datasets" / "profiles.yaml").read_text()
    summary = run_profile.read_profiles_summary(text)
    document = yaml.safe_load(text)
    assert summary["tiers"] == document["tiers"] and summary["version"] == document["version"]
    for name, shape in document["breadth"].items():
        nesting = shape.get("nesting")
        expected = sum(nesting["fanout"] ** level for level in range(nesting["depth"])) if nesting else shape["projects_per_org"]
        assert summary["projects"][name] == expected and summary["organisations"][name] == shape["organisations"]


def test_compose_version_comparison():
    assert run_profile.parse_compose_version("v5.5.1") >= run_profile.MIN_COMPOSE
    assert run_profile.parse_compose_version("2.23.3") < run_profile.MIN_COMPOSE
    assert run_profile.parse_compose_version("garbage") == (0, 0)


def test_git_state_reports_only_a_hash_and_two_flags():
    def run(argv, **kwargs):
        out = {"rev-parse": "a" * 40, "status": " M x.py", "branch": ""}[argv[1]]
        return subprocess.CompletedProcess(argv, 0, out + "\n", "")

    assert run_profile.git_state(run=run) == {"commit": "a" * 40, "dirty": True, "on_remote": False}


def test_plan_prints_what_is_created_and_not_touched_and_starts_nothing():
    calls: list = []
    printed: list = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["docker", "info", "--format"]:
            return subprocess.CompletedProcess(argv, 0, "8|16777216000|Ubuntu 24.04.1 LTS|29.8.1|x86_64\n", "")
        if argv[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(argv, 0, "v5.5.1\n", "")
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, {"rev-parse": "a" * 40, "status": "", "branch": ""}[argv[1]] + "\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "")

    options = run_profile.parse_args(["rpi5-8g", "--plan", "--max-mem", "6", "--tiers", "T1"])
    status = run_profile.ProfileRun(options, say=printed.append, runner=run).execute()
    text = "\n".join(printed)
    assert status == 0
    assert "reqtrack-perf" in text and "Will NOT touch" in text and "no docker prune" in text
    assert not any(a[:2] == ["docker", "compose"] and a[-1:] != ["version"] and "--short" not in a for a in calls)
    assert not any(a[1] in ("rm", "stop", "kill") for a in calls if a[0] == "docker")


def test_cleanup_removes_only_the_perf_project():
    calls: list = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "ps":
            return subprocess.CompletedProcess(argv, 0, "reqtrack-perf-db-1\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    printed: list = []
    status = run_profile.ProfileRun(run_profile.parse_args(["--cleanup"]), say=printed.append, runner=run).execute()
    assert status == 0 and "removed 1" in printed[0]
    assert ["docker", "rm", "-f", "-v", "reqtrack-perf-db-1"] in calls


# --- analysis --------------------------------------------------------------------------------------------


def _analyse():
    import importlib.util

    spec = importlib.util.spec_from_file_location("perf_analyse", _PERF / "analyse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _latency_rows(request: str, p95_by_tier: dict, users: int = 4) -> list:
    return [
        {"tier": t, "scenario": "browse", "repeat": "1", "users": str(users), "request": request, "p95_ms": str(v), "failures": "0"}
        for t, v in p95_by_tier.items()
    ]


SIZES = {"T0": 30, "T1": 100, "T2": 1000, "T3": 5000}


def test_scaling_shape_is_classified_from_the_log_log_slope():
    analyse = _analyse()
    flat = analyse.slope([(n, 50.0) for n in SIZES.values()])
    linear = analyse.slope([(n, n * 0.5) for n in SIZES.values()])
    quadratic = analyse.slope([(n, n * n * 0.001) for n in SIZES.values()])
    assert abs(flat) < 0.05 and abs(linear - 1) < 0.05 and abs(quadratic - 2) < 0.05
    assert [analyse.classify(v) for v in (flat, linear, quadratic, None)] == ["flat", "linear", "superlinear", "insufficient data"]
    assert analyse.slope([(30, 5.0), (100, 6.0)]) is None


def test_a_fixed_size_page_that_grows_with_the_data_is_a_finding_even_under_budget():
    analyse = _analyse()
    budgets = {
        "flat_slope": 0.25,
        "superlinear_slope": 1.3,
        "fixed_size_page_max_slope": 0.35,
        "classes": {"interactive": {"p95_ms": 300}},
        "rules": [{"match": "GET ", "class": "interactive"}],
    }
    rows = _latency_rows("GET /projects/{id}/requirements (page of 50)", {"T0": 10, "T1": 20, "T2": 120, "T3": 280}) + _latency_rows(
        "GET /projects/{id}/requirements (unpaged)", {"T0": 10, "T1": 30, "T2": 300, "T3": 1500}
    )
    table = analyse.scaling_table(rows, SIZES, budgets)
    by_request = {r["request"]: r for r in table}
    assert by_request["GET /projects/{id}/requirements (page of 50)"]["finding"].startswith("returns a fixed-size page")
    assert (
        by_request["GET /projects/{id}/requirements (unpaged)"]["label"] == "linear"
        and by_request["GET /projects/{id}/requirements (unpaged)"]["finding"] is None
    )


def test_budget_findings_apply_each_classs_limit_and_tiers():
    analyse = _analyse()
    budgets = {
        "classes": {"interactive": {"p95_ms": 300}, "list": {"p95_ms": 1000, "tiers": ["T0", "T1", "T2"]}},
        "rules": [{"match": "(unpaged)", "class": "list"}, {"match": "GET ", "class": "interactive"}],
    }
    table = analyse.scaling_table(
        _latency_rows("GET a (unpaged)", {"T0": 5, "T2": 1500, "T3": 9000}) + _latency_rows("GET b", {"T0": 5, "T2": 400}), SIZES, budgets
    )
    found = {(f["request"], f["tier"]) for f in analyse.budget_findings(table, budgets)}
    assert found == {("GET a (unpaged)", "T2"), ("GET b", "T2")}  # T3 is outside the list class's tiers


def test_memory_peaks_and_the_soak_growth_after_warm_up():
    analyse = _analyse()
    samples = [
        {"tier": "T1", "scenario": "soak", "service": "backend", "t_seconds": str(t), "mem_mib": str(500 + (t * 0.1 if t > 100 else t * 5))}
        for t in range(0, 600, 10)
    ]
    samples.append({"tier": "T1", "scenario": "browse", "service": "db", "t_seconds": "1", "mem_mib": "300"})
    assert analyse.memory_peaks(samples)[("T1", "db")] == 300.0
    growth = analyse.memory_slope_mib_per_hour(samples, "T1")
    assert growth is not None and abs(growth - 360.0) < 5  # 0.1 MiB/s after warm-up
    assert analyse.memory_slope_mib_per_hour(samples[:5], "T1") is None


def test_budgets_file_parses_and_names_known_classes():
    yaml = pytest.importorskip("yaml")
    budgets = yaml.safe_load((_PERF / "budgets.yaml").read_text())
    assert {rule["class"] for rule in budgets["rules"]} <= set(budgets["classes"])
    assert budgets["classes"]["interactive"]["p95_ms"] == 300 and budgets["classes"]["heavy"]["p95_ms"] == 30000


# --- backend profiling: statements per request, process memory, CPU and heap modes -------------------------


def _profile_run(printed=None, **argv_extra):
    options = run_profile.parse_args(["rpi5-8g", "--plan", "--tiers", "T1", *argv_extra.get("argv", [])])
    return run_profile.ProfileRun(options, say=(printed.append if printed is not None else (lambda line: None)))


class _SnapshotDocker:
    """Answers the runner's `profile_tools.py snapshot` exec with scripted readings, one per call."""

    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.calls: list = []

    def compose(self, *args, **options):
        self.calls.append(args)
        return compose.Result(0, json.dumps(next(self.snapshots)), "")


def _route(requests, queries, db_ms=0.0, repeat_statement="", repeat_count=0):
    return {
        "requests": requests,
        "queries": queries,
        "db_ms": db_ms,
        "max_queries": 0,
        "repeat_statement": repeat_statement,
        "repeat_count": repeat_count,
    }


def _worker(index, private, shared=30.0):
    return {
        "role": "worker",
        "index": index,
        "rss_mib": private + shared,
        "pss_mib": private + shared / 2,
        "private_mib": private,
        "shared_mib": shared,
    }


def test_each_scenario_is_credited_only_with_the_statements_run_since_the_previous_snapshot(monkeypatch):
    monkeypatch.setattr(run_profile, "QUERY_FLUSH_SECONDS", 0)
    run = _profile_run()
    run.docker = _SnapshotDocker(
        [
            {"processes": [_worker(1, 400.0)], "queries": {"POST /login": _route(2, 4)}},
            {"processes": [_worker(1, 410.0)], "queries": {"POST /login": _route(2, 4), "GET /items": _route(10, 30, 50.0, "select 1", 3)}},
            {"processes": [_worker(1, 415.0)], "queries": {"POST /login": _route(2, 4), "GET /items": _route(14, 50, 90.0, "select 1", 5)}},
        ]
    )
    run.record_snapshot("T1", "idle", 0, wait=False)
    run.record_snapshot("T1", "browse", 1)
    run.record_snapshot("T1", "edit", 1)
    rows = {(r["scenario"], r["request"]): r for r in run.query_rows()}
    assert set(rows) == {("browse", "GET /items"), ("edit", "GET /items")}, "login ran before browse and is not browse's"
    assert rows[("browse", "GET /items")]["queries_per_request"] == 3.0 and rows[("browse", "GET /items")]["db_ms_per_request"] == 5.0
    assert rows[("edit", "GET /items")]["requests"] == 4 and rows[("edit", "GET /items")]["queries_per_request"] == 5.0
    assert [(r["scenario"], r["private_mib"]) for r in run.process_rows] == [("idle", 400.0), ("browse", 410.0), ("edit", 415.0)]
    assert run.suspects["GET /items"] == {"statement": "select 1", "count": 5}


def test_an_image_without_profiling_tools_gives_empty_results_and_one_note(monkeypatch):
    class Failing:
        def compose(self, *args, **options):
            return compose.Result(1, "", "No such file")

    monkeypatch.setattr(run_profile, "QUERY_FLUSH_SECONDS", 0)
    run = _profile_run()
    run.docker = Failing()
    for scenario in ("idle", "browse"):
        run.record_snapshot("T1", scenario, 1, wait=False)
    assert run.query_rows() == [] and run.process_rows == []
    assert len([n for n in run.notes if "profiling tools" in n]) == 1


def test_profiling_modes_merge_the_profile_override_and_only_then():
    assert _profile_run().compose_files() == run_profile.COMPOSE_FILES
    files = _profile_run(argv=["--profiling", "cpu"]).compose_files()
    assert files == run_profile.COMPOSE_FILES + (run_profile.PROFILE_COMPOSE_FILE,)
    docker = compose.PerfDocker(files, Path("/tmp/perf.env"), run_profile.REPO_ROOT, runner=_fake(), environ={})
    compose.validate_argv(docker.compose_argv("exec", "-T", "-u", "root", "backend", "py-spy", "record"), [str(f) for f in files] + ["/tmp/perf.env"])
    with pytest.raises(compose.UnsafeCommand):  # the profile file is only allowed when this run named it
        compose.validate_argv(docker.compose_argv("up"), COMPOSE_FILES + ["/tmp/perf.env"])


def test_a_profiling_run_always_builds_the_profile_image_and_says_it_changes_latency():
    printed: list = []
    run = _profile_run(printed, argv=["--profiling", "cpu"])
    image, source = run.choose_images({"arch": "amd64"}, {"commit": "a" * 40, "dirty": False})
    assert (image, source) == (run_profile.PROFILE_IMAGE, "built")
    plan = "\n".join(
        run.plan_lines({"arch": "amd64", "docker_cores": 8, "docker_ram_gib": 16}, resources.plan_caps(8, 16, max_mem_gib=5), "backend built")
    )
    assert "Profiling         : cpu" in plan and "latency is not comparable" in plan and "docker-compose.profile.yml" in plan


@pytest.mark.parametrize(
    "argv",
    [
        ["--profiling", "heap"],  # no tier named
        ["--profiling", "heap", "--tiers", "T0,T1"],  # a capture covers one backend start
        ["--profiling", "heap", "--tiers", "T1", "--workers", "4"],
        ["--profiling", "cpu", "--images", "pull"],  # a published image has no profilers
    ],
)
def test_profiling_options_that_cannot_work_are_refused(argv):
    with pytest.raises(SystemExit):
        run_profile.parse_args(["rpi5-8g", *argv])


def test_heap_mode_runs_one_worker_and_asks_the_backend_to_start_under_memray():
    options = run_profile.parse_args(["rpi5-8g", "--profiling", "heap", "--tiers", "T1"])
    assert options.workers == 1
    caps = resources.plan_caps(8, 16, max_mem_gib=5, workers=1)
    heap = run_profile.stack_environment(caps=caps, workers=1, backend_image="x", loadgen_image="y", profiling="heap")
    plain = run_profile.stack_environment(caps=caps, workers=1, backend_image="x", loadgen_image="y")
    assert heap["PROFILE_MEMRAY"] == "1" and "PROFILE_MEMRAY" not in plain


def test_the_perf_override_turns_profile_mode_on_without_a_port_or_endpoint():
    text = (_PERF / "docker-compose.perf.yml").read_text()
    assert 'PROFILE_MODE: "true"' in text and "PROFILE_OUTPUT_DIR: /tmp/profile" in text


def test_a_profiling_bundle_with_every_new_file_passes_the_check_and_a_leaky_flamegraph_does_not(tmp_path):
    directory = tmp_path / "linux-vm-4c8g" / "2026-10-25-aaaaaaaa"
    bundle.write_bundle(
        directory,
        host=hostinfo.collect(storage="ssd", run=_docker_info_runner()),
        run={
            "schema_version": 1,
            "host_label": "linux-vm-4c8g",
            "commit": "a" * 40,
            "date": "2026-10-25",
            "mode": "quick",
            "tiers": ["T1"],
            "scenarios": ["browse"],
            "notes": [],
            "profiling": "heap",
            "heap_live_mib": 301.5,
            "heap_peak_mib": 340.2,
        },
        datasets=[],
        samples=[],
        latency=[],
        queries=[
            {
                "tier": "T1",
                "scenario": "browse",
                "request": "GET /api/v1/projects/{project_id}/requirements",
                "requests": 40,
                "queries_per_request": 3.5,
                "db_ms_per_request": 4.2,
            }
        ],
        processes=[
            {
                "tier": "T1",
                "scenario": "idle",
                "repeat": 0,
                "role": "worker",
                "index": 1,
                "rss_mib": 450.0,
                "pss_mib": 430.0,
                "private_mib": 415.0,
                "shared_mib": 35.0,
            }
        ],
        heap=[{"kind": "package", "name": "site-packages/pydantic", "mib": 80.5, "allocations": 1000}],
        profiles={"cpu-t1-browse-u4.svg": "<svg><title>get (site-packages/fastapi/routing.py:290)</title></svg>"},
    )
    assert scrub.scan_tree(directory, identities=["someoneelse"]) == []
    assert (directory / "profiles" / "cpu-t1-browse-u4.svg").is_file() and (directory / "heap.csv").is_file()
    for bad in ("<svg><title>run (/Users/jane/x.py:1)</title></svg>", "<svg>password=hunter2hunter2</svg>"):
        (directory / "profiles" / "cpu-t1-browse-u4.svg").write_text(bad)
        assert scrub.scan_tree(directory, identities=["someoneelse"])
    with pytest.raises(bundle.BundleError):
        bundle.write_bundle(
            tmp_path / "x",
            host=hostinfo.collect(storage="ssd", run=_docker_info_runner()),
            run={},
            datasets=[],
            samples=[],
            latency=[],
            profiles={"../escape.svg": "<svg/>"},
        )


def test_source_paths_in_a_flamegraph_are_shortened_before_it_is_kept(tmp_path):
    run = _profile_run()
    run.work = tmp_path

    class Docker:
        def compose(self, *args, **options):
            if args[0] == "cp":
                Path(args[2]).write_text(
                    "<svg><title>serve (/app/app/main.py:10)</title>"
                    "<title>x (/usr/local/lib/python3.12/site-packages/starlette/routing.py:5)</title></svg>"
                )
            return compose.Result(0, "", "")

    run.docker = Docker()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    run.finish_cpu_profile(thread, "cpu-t1-browse-u4.svg", {"warmup_seconds": 0, "measure_seconds": 1, "min_requests": 0})
    text = run.profile_files["cpu-t1-browse-u4.svg"]
    assert "(app/main.py:10)" in text and "(site-packages/starlette/routing.py:5)" in text and "/usr/local" not in text and "/app/" not in text


def test_the_heap_summary_becomes_package_and_location_rows_and_run_totals():
    run = _profile_run()

    class Docker:
        def compose(self, *args, **options):
            if args[0] == "stop":
                return compose.Result(0, "", "")
            return compose.Result(
                0,
                json.dumps(
                    {
                        "live_mib": 301.5,
                        "peak_mib": 340.2,
                        "by_package": [{"name": "site-packages/pydantic", "mib": 80.5, "allocations": 1000}],
                        "by_location": [{"name": "pydantic/main.py:40 build", "mib": 12.0, "allocations": 50}],
                    }
                ),
                "",
            )

    run.docker = Docker()
    run.finish_heap()
    assert run.heap_totals == {"heap_live_mib": 301.5, "heap_peak_mib": 340.2}
    assert [(r["kind"], r["name"]) for r in run.heap_rows] == [("package", "site-packages/pydantic"), ("location", "pydantic/main.py:40 build")]


def test_a_route_whose_statements_grow_with_the_data_is_an_n_plus_one_suspect():
    analyse = _analyse()
    rows = [
        {"scenario": "browse", "request": request, "tier": tier, "queries_per_request": str(value)}
        for request, values in (
            ("GET /requirements (paged)", {"T0": 4, "T1": 4, "T2": 4, "T3": 4.05}),
            ("GET /requirements", {"T0": 6, "T1": 14, "T2": 104, "T3": 504}),
        )
        for tier, value in values.items()
    ]
    found = {r["request"]: r for r in analyse.query_scaling(rows, SIZES, {})}
    assert found["GET /requirements (paged)"]["label"] == "flat" and found["GET /requirements (paged)"]["finding"] is None
    assert found["GET /requirements"]["label"] in ("linear", "superlinear") and "N+1" in found["GET /requirements"]["finding"]
    assert analyse.query_scaling(rows[:2], SIZES, {})[0]["label"] == "insufficient data"


def test_worker_memory_reports_private_and_shared_per_worker_from_the_heaviest_reading():
    analyse = _analyse()

    def row(scenario, index, private, pss, role="worker"):
        return {
            "tier": "T1",
            "scenario": scenario,
            "repeat": "1",
            "role": role,
            "index": str(index),
            "rss_mib": str(private + 30),
            "pss_mib": str(pss),
            "private_mib": str(private),
            "shared_mib": "30",
        }

    rows = [
        row("idle", 1, 380, 395),
        row("idle", 2, 380, 395),
        row("browse", 1, 400, 415),
        row("browse", 2, 410, 425),
        row("browse", 1, 2, 3, role="parent"),
    ]
    assert analyse.worker_memory(rows) == {
        "T1": {"workers": 2, "private_mib_per_worker": 405.0, "shared_mib_per_worker": 30.0, "pss_total_mib": 843.0}
    }


def test_recorded_caps_are_rounded_so_a_float_tail_is_not_mistaken_for_a_serial_number(tmp_path):
    caps = resources.plan_caps(12, 7.7, max_mem_gib=3.2, workers=2).as_dict()
    assert "000000000000" not in json.dumps(caps)
    (tmp_path / "run.json").write_text(json.dumps({"caps": caps}, indent=2))
    assert not [f for f in scrub.scan_file(tmp_path / "run.json", tmp_path, []) if "serial" in f.rule]


# --- PostgreSQL profiling: statement totals, connections, settings and plans --------------------------------


def _pg():
    from perf.lib import pgprofile

    return pgprofile


def test_only_the_perf_stack_loads_pg_stat_statements():
    root = _PERF.parent
    assert "shared_preload_libraries=pg_stat_statements" in (_PERF / "docker-compose.perf.yml").read_text()
    for name in ("docker-compose.yml", "docker-compose.profile.yml", "tests/container/docker-compose.yml"):
        assert "pg_stat_statements" not in (root / name).read_text(), f"{name} must not load the extension"


def test_the_statement_list_keeps_only_dml_collapses_whitespace_and_cuts_long_text():
    rows = _pg().statement_rows(
        "T1",
        "browse",
        [
            {
                "calls": 10,
                "total_ms": 5.5,
                "mean_ms": 0.55,
                "row_count": 40,
                "read_blocks": 1,
                "temp_blocks": 0,
                "query": "SELECT a\n   FROM t WHERE id = $1",
            },
            {
                "calls": 1,
                "total_ms": 1.0,
                "mean_ms": 1.0,
                "row_count": 0,
                "read_blocks": 0,
                "temp_blocks": 0,
                "query": "ALTER ROLE reqtrack PASSWORD 'hunter2hunter2'",
            },
            {"calls": 1, "total_ms": 1.0, "mean_ms": 1.0, "row_count": 0, "read_blocks": 0, "temp_blocks": 0, "query": "select " + "x, " * 300},
        ],
    )
    assert rows[0]["query"] == "SELECT a FROM t WHERE id = $1" and rows[1]["query"].startswith("select x, x, x")
    assert _pg().collapse("where a = $1::uuid and b = $2::numeric(10, 2) and c = any($3::text[])") == "where a = $1 and b = $2 and c = any($3)"
    assert rows[0]["rows"] == 40 and len(rows[1]["query"]) == _pg().QUERY_LIMIT and rows[1]["query"].endswith("…")


def test_the_database_row_reports_hit_rate_temp_spill_and_deadlocks_for_the_scenario_only():
    before = {"blks_hit": 1000, "blks_read": 10, "temp_files": 2, "temp_bytes": 1 * 2**20, "deadlocks": 0}
    after = {"blks_hit": 1990, "blks_read": 20, "temp_files": 5, "temp_bytes": 7 * 2**20, "deadlocks": 1}
    row = _pg().database_row("T2", "list_unpaged", before, after, 41, 3)
    assert row == {
        "tier": "T2",
        "scenario": "list_unpaged",
        "connections_peak": 41,
        "idle_in_transaction_peak": 3,
        "cache_hit_percent": 99.0,
        "temp_files": 3,
        "temp_mib": 6.0,
        "deadlocks": 1,
    }
    assert _pg().database_row("T0", "idle", before, before, 0, 0)["cache_hit_percent"] == "", "no block activity: no rate"


@pytest.mark.parametrize(
    "query,planned",
    [
        ("select * from t where id = $1", True),
        ("with x as (select 1) select * from x", True),
        ("update t set a = $1 where id = $2", True),
        ("select 1; drop table t", False),
        ("drop table t", False),
        ("select * from t where a = E'\\x41'", False),
        ("create role r password 'x'", False),
    ],
)
def test_only_a_single_dml_statement_is_planned_and_never_executed(query, planned):
    sql = _pg().explain_sql(query)
    assert bool(sql) is planned
    if planned:
        assert sql.startswith("EXPLAIN (GENERIC_PLAN, FORMAT JSON) ") and "ANALYZE" not in sql


def test_plan_rows_list_each_scan_without_filter_text():
    plan = [
        {
            "Plan": {
                "Node Type": "Nested Loop",
                "Total Cost": 123.456,
                "Plans": [
                    {"Node Type": "Seq Scan", "Relation Name": "requirements", "Plan Rows": 5000, "Filter": "(project_id = $1)"},
                    {"Node Type": "Index Scan", "Relation Name": "projects", "Index Name": "projects_pkey", "Plan Rows": 1},
                ],
            }
        }
    ]
    rows = _pg().plan_rows("T2", "browse", 1, plan)
    assert [(r["node"], r["relation"], r["index"], r["filtered"], r["est_rows"]) for r in rows] == [
        ("Seq Scan", "requirements", "", "yes", 5000),
        ("Index Scan", "projects", "projects_pkey", "no", 1),
    ]
    assert all(r["plan_cost"] == 123.5 for r in rows) and "$1" not in json.dumps(rows)
    assert _pg().plan_rows("T2", "browse", 1, {"not": "a plan"}) == []


def test_the_connection_ceiling_is_workers_times_pool_plus_overflow_plus_two_dedicated():
    pgprofile = _pg()
    assert pgprofile.connection_ceiling(4, 5, 10) == 68
    assert pgprofile.connection_ceiling(4, 5, 10, replicas=2) == 136
    assert pgprofile.connection_ceiling(1, 2, 0) == 4


def test_the_default_pool_keeps_the_default_four_workers_inside_postgres_default_max_connections():
    from app.config import Settings

    settings = Settings()
    ceiling = _pg().connection_ceiling(resources.DEFAULT_WORKERS, settings.db_pool_size, settings.db_max_overflow)
    assert ceiling <= 100 - _pg().RESERVED_CONNECTIONS, "documented formula: workers x (pool + overflow + 2) under max_connections"


def test_the_engine_pool_is_sized_from_the_pool_settings():
    from app import database
    from app.config import get_settings

    settings = get_settings()
    assert database.engine.pool.size() == settings.db_pool_size and database.engine.pool._max_overflow == settings.db_max_overflow
    assert (settings.db_pool_size, settings.db_max_overflow) == (5, 10), "defaults unchanged unless the environment sets them"


def test_the_connection_poller_keeps_the_highest_reading_and_ignores_a_failed_one():
    readings = iter([(3, 0), None, (9, 2), (5, 1)])
    poller = _pg().ConnectionPoller(lambda: next(readings), interval=0)
    for _ in range(4):
        poller.sample()
    assert (poller.peak, poller.idle_in_transaction_peak, poller.readings) == (9, 2, 3)
    assert _pg().parse_connections("12 3\n") == (12, 3) and _pg().parse_connections("garbage") is None


def test_a_bundle_with_the_database_files_passes_the_check_and_a_leaked_literal_does_not(tmp_path):
    directory = tmp_path / "linux-vm-4c8g" / "2026-10-25-aaaaaaaa"
    statement = (
        "SELECT requirements.id::uuid, requirements.created_at::timestamptz FROM requirements "
        "WHERE requirements.project_id = $1::uuid AND requirements.title ILIKE $2 ORDER BY requirements.unique_code LIMIT $3 OFFSET $4"
    )
    bundle.write_bundle(
        directory,
        host=hostinfo.collect(storage="ssd", run=_docker_info_runner()),
        run={
            "schema_version": 1,
            "host_label": "linux-vm-4c8g",
            "commit": "a" * 40,
            "date": "2026-10-25",
            "notes": [],
            "postgres": {"max_connections": "100", "shared_buffers": "128MB", "work_mem": "4MB"},
            "db_pool": {"pool_size": 5, "max_overflow": 10, "connection_ceiling": 68},
        },
        datasets=[],
        samples=[],
        latency=[],
        pgstat=_pg().statement_rows(
            "T1", "browse", [{"calls": 9, "total_ms": 4.0, "mean_ms": 0.4, "row_count": 9, "read_blocks": 0, "temp_blocks": 0, "query": statement}]
        ),
        pgdb=[_pg().database_row("T1", "browse", {}, {"blks_hit": 9, "blks_read": 1}, 12, 0)],
        plans=_pg().plan_rows(
            "T1", "browse", 1, [{"Plan": {"Node Type": "Seq Scan", "Relation Name": "requirements", "Plan Rows": 100, "Filter": "x"}}]
        ),
    )
    assert scrub.scan_tree(directory, identities=["someoneelse"]) == []
    leaked = directory / "pgstat.csv"
    leaked.write_text(leaked.read_text() + "T1,browse,1,1,1,1,0,0,\"select * from users where email = 'jane@example.com'\"\n")
    assert scrub.scan_tree(directory, identities=["someoneelse"])


class _PsqlDocker:
    """Answers the runner's `psql` execs by SQL text and records every statement it was sent."""

    def __init__(self, answers, fail=()):
        self.answers = answers
        self.fail = fail
        self.sent: list = []

    def compose(self, *args, **options):
        if "psql" not in args:
            return compose.Result(0, "", "")
        sql = options.get("input", "")
        self.sent.append(sql)
        if any(token in sql for token in self.fail):
            return compose.Result(1, "", "boom")
        for token, out in self.answers.items():
            if token in sql:
                return compose.Result(0, out, "")
        return compose.Result(0, "", "")


def test_a_scenarios_database_results_cover_statements_counters_and_plans_for_dml_only(monkeypatch):
    monkeypatch.setattr(run_profile, "QUERY_FLUSH_SECONDS", 0)
    statements = [
        {
            "calls": 50,
            "total_ms": 90.0,
            "mean_ms": 1.8,
            "row_count": 500,
            "read_blocks": 0,
            "temp_blocks": 0,
            "query": "select * from requirements where project_id = $1",
        },
        {"calls": 2, "total_ms": 5.0, "mean_ms": 2.5, "row_count": 2, "read_blocks": 0, "temp_blocks": 0, "query": "SET search_path = x"},
        {"calls": 5, "total_ms": 4.0, "mean_ms": 0.8, "row_count": 5, "read_blocks": 0, "temp_blocks": 0, "query": "select 1; select 2"},
    ]
    plan = [
        {"Plan": {"Node Type": "Seq Scan", "Relation Name": "requirements", "Plan Rows": 2000, "Total Cost": 80.0, "Filter": "(project_id = $1)"}}
    ]
    stats = iter(
        [
            {"blks_hit": 0, "blks_read": 0, "temp_files": 0, "temp_bytes": 0, "deadlocks": 0},
            {"blks_hit": 99, "blks_read": 1, "temp_files": 0, "temp_bytes": 0, "deadlocks": 0},
        ]
    )

    class Docker(_PsqlDocker):
        def compose(self, *args, **options):
            sql = options.get("input", "")
            if "psql" in args and "blks_hit" in sql:
                self.sent.append(sql)
                return compose.Result(0, json.dumps(next(stats)), "")
            return super().compose(*args, **options)

    run = _profile_run()
    run.docker = Docker(
        {"pg_stat_statements_reset": "", "total_exec_time": json.dumps(statements), "GENERIC_PLAN": json.dumps(plan), "pg_stat_activity": "4 0"}
    )
    run.pg_enabled = True
    run.pg_begin()
    run.pg_end("T1", "browse")
    assert [r["query"] for r in run.pgstat_rows] == ["select * from requirements where project_id = $1", "select 1; select 2"]
    assert run.pgdb_rows[0]["cache_hit_percent"] == 99.0 and run.pgdb_rows[0]["connections_peak"] == 4
    assert [(r["relation"], r["filtered"], r["est_rows"]) for r in run.plan_rows] == [("requirements", "yes", 2000)]
    planned = [sql for sql in run.docker.sent if "GENERIC_PLAN" in sql]
    assert len(planned) == 1 and all(
        "ANALYZE" not in sql for sql in run.docker.sent if "EXPLAIN" in sql
    ), "only the one DML statement is planned, never executed"


def test_a_database_that_cannot_load_the_extension_gives_empty_files_and_one_note():
    run = _profile_run()
    run.docker = _PsqlDocker({}, fail=("create extension",))
    run.pg_prepare()
    run.pg_prepare()
    run.pg_begin()
    run.pg_end("T1", "browse")
    assert not run.pg_enabled and run.pgstat_rows == [] and run.pgdb_rows == [] and run.plan_rows == []
    assert len([n for n in run.notes if "pg_stat_statements" in n]) == 1


def test_the_servers_settings_and_the_pool_ceiling_are_recorded_once_per_run():
    class Docker(_PsqlDocker):
        def compose(self, *args, **options):
            if "python" in args:
                return compose.Result(0, "5 10\n", "")
            return super().compose(*args, **options)

    run = _profile_run(argv=["--workers", "2"])
    run.workers = 2
    run.docker = Docker({"current_setting": json.dumps({"max_connections": "100", "work_mem": "4MB"})})
    run.pg_prepare()
    assert run.pg_enabled and run.pg_settings["max_connections"] == "100"
    assert run.db_pool == {"pool_size": 5, "max_overflow": 10, "connection_ceiling": 2 * 17}
    sent = len(run.docker.sent)
    run.pg_prepare()
    assert not any("current_setting" in sql for sql in run.docker.sent[sent:]), "settings are read once per run"


def test_database_findings_flag_connections_cache_spill_and_deadlocks():
    analyse = _analyse()

    run = {"postgres": {"max_connections": "100", "shared_buffers": "128MB", "work_mem": "4MB"}, "db_pool": {"connection_ceiling": 140}}
    rows = [
        {
            "tier": "T2",
            "scenario": "browse",
            "connections_peak": "90",
            "idle_in_transaction_peak": "0",
            "cache_hit_percent": "98.5",
            "temp_files": "4",
            "temp_mib": "12.0",
            "deadlocks": "1",
        },
        {
            "tier": "T2",
            "scenario": "edit",
            "connections_peak": "10",
            "idle_in_transaction_peak": "0",
            "cache_hit_percent": "",
            "temp_files": "0",
            "temp_mib": "0",
            "deadlocks": "0",
        },
    ]
    kinds = sorted((f["kind"], f["where"]) for f in analyse.database_findings(rows, run))
    assert kinds == [
        ("cache", "T2/browse"),
        ("connections", "T2/browse"),
        ("connections", "configuration"),
        ("deadlock", "T2/browse"),
        ("work_mem", "T2/browse"),
    ]
    assert analyse.database_findings(rows[1:], {"postgres": run["postgres"], "db_pool": {"connection_ceiling": 68}}) == []


def test_plan_findings_report_a_filtered_seq_scan_of_a_large_table_at_its_largest_tier_once():
    analyse = _analyse()

    def plan(tier, relation, node, filtered, est):
        return {
            "tier": tier,
            "scenario": "browse",
            "rank": "1",
            "node": node,
            "relation": relation,
            "index": "",
            "filtered": filtered,
            "est_rows": str(est),
            "plan_cost": "1",
        }

    rows = [
        plan("T1", "requirements", "Seq Scan", "yes", 1200),
        plan("T2", "requirements", "Seq Scan", "yes", 9000),
        plan("T2", "projects", "Seq Scan", "yes", 40),
        plan("T2", "audit_events", "Seq Scan", "no", 50000),
        plan("T2", "comments", "Index Scan", "yes", 50000),
    ]
    found = analyse.plan_findings(rows, {"T1": 100, "T2": 1000})
    assert [(f["relation"], f["tier"], f["est_rows"]) for f in found] == [("requirements", "T2", 9000)]


def test_top_statements_are_the_costliest_per_scenario_and_sizes_parse():
    analyse = _analyse()

    def row(total, name):
        return {
            "tier": "T1",
            "scenario": "browse",
            "calls": "2",
            "total_ms": str(total),
            "mean_ms": "1",
            "rows": "1",
            "read_blocks": "0",
            "temp_blocks": "0",
            "query": name,
        }

    top = analyse.top_statements([row(5, "a"), row(50, "b"), row(20, "c"), row(1, "d")], per_scenario=2)
    assert [r["query"] for r in top[("T1", "browse")]] == ["b", "c"]
    assert analyse.parse_size_mib("128MB") == 128.0 and analyse.parse_size_mib("4GB") == 4096.0 and analyse.parse_size_mib("512kB") == 0.5
    assert analyse.parse_size_mib("on") is None


def test_a_long_database_identifier_is_not_mistaken_for_a_secret_but_a_random_token_still_is(tmp_path):
    identifier = "requirement_versions_requirement_id_version_number_key"
    token = "Zk3Xq9LmP2vB7nRt5YcW8dFhJ1sAeGuO4iKxN6bVq0TyHrCl"
    assert len(identifier) >= 48 and len(token) >= 48
    (tmp_path / "plans.csv").write_text(
        f"tier,scenario,rank,node,relation,index,filtered,est_rows,plan_cost\nT2,browse,1,Index Scan,requirement_versions,{identifier},no,9,1\n"
    )
    assert scrub.scan_tree(tmp_path, identities=["someoneelse"]) == []
    (tmp_path / "plans.csv").write_text(
        f"tier,scenario,rank,node,relation,index,filtered,est_rows,plan_cost\nT2,browse,1,Index Scan,requirement_versions,{token},no,9,1\n"
    )
    assert [f.rule for f in scrub.scan_tree(tmp_path, identities=["someoneelse"])] == ["long opaque string (possible secret)"]


def test_a_second_run_on_the_same_day_and_commit_gets_its_own_bundle_directory(tmp_path):
    first = bundle.bundle_dir(tmp_path, "mac-docker-desktop", "2026-10-25", "e7f99adaf4f6")
    assert bundle.unused_bundle_dir(first) == first
    first.mkdir(parents=True)
    second = bundle.unused_bundle_dir(first)
    assert second.name == "2026-10-25-e7f99ada-2"
    second.mkdir()
    assert bundle.unused_bundle_dir(first).name == "2026-10-25-e7f99ada-3"


def test_load_limit_defaults_by_host_kind_and_honours_the_operator():
    from perf import run_profile

    def limit(*argv):
        options = run_profile.parse_args(["lab-host", *argv])
        return run_profile.ProfileRun(options).thresholds().max_load_per_core

    assert limit() == 1.5
    assert limit("--dedicated") == run_profile.DEDICATED_MAX_LOAD_PER_CORE
    assert limit("--max-load-per-core", "2.5") == 2.5
    assert limit("--dedicated", "--max-load-per-core", "2.5") == 2.5


def test_worker_memory_tells_snapshots_at_different_user_levels_apart():
    """`processes.csv` has one snapshot per user level with the same scenario and repeat; they must not be merged."""
    analyse = _analyse()

    def snapshot(private):
        return [
            {"tier": "T1", "scenario": "browse", "repeat": "1", "role": "parent", "index": "1",
             "pss_mib": "19", "private_mib": "18", "shared_mib": "10"},
            *[{"tier": "T1", "scenario": "browse", "repeat": "1", "role": "worker", "index": str(i), "pss_mib": str(private + 10),
               "private_mib": str(private), "shared_mib": "35"} for i in (1, 2)],
        ]

    memory = analyse.worker_memory(snapshot(400) + snapshot(450) + snapshot(420))
    assert memory["T1"]["workers"] == 2 and memory["T1"]["private_mib_per_worker"] == 450


def test_capacity_scenario_runs_at_one_tier_once_and_steps_users_up():
    assert catalog.parameters("capacity", "full", 100, "T0") == []
    assert catalog.parameters("capacity", "full", 5000, "T3") == []
    full = catalog.parameters("capacity", "full", 1000, "T2")
    assert [p["users"] for p in full] == [16, 32, 64, 128, 256]
    assert [p["users"] for p in catalog.parameters("capacity", "quick", 1000, "T2")] == [16, 64]
    assert [p["users"] for p in catalog.parameters("capacity", "full", 1000, "T2", users=(8, 24))] == [8, 24]
    spec = catalog.CATALOG["capacity"]
    assert spec.heavy and spec.repeats == 1 and spec.tiers == ("T2",)
    assert "capacity" not in catalog.scenarios_for("full", allow_heavy=False, nested=False, soak=False)
    assert "capacity" in catalog.scenarios_for("full", allow_heavy=True, nested=False, soak=False)
    assert "capacity" not in catalog.scenarios_for("quick", allow_heavy=True, nested=False, soak=False)


def test_capacity_pacing_is_the_same_on_the_host_and_in_the_load_generator_and_the_budgets():
    import yaml

    source = (_PERF / "loadgen" / "scenarios.py").read_text()
    block = source[source.index("class Capacity("):source.index("SCENARIOS: dict")]
    assert f"constant_throughput({catalog.CAPACITY_REQUESTS_PER_SECOND:g})" in block
    budgets = yaml.safe_load((_PERF / "budgets.yaml").read_text())
    assert budgets["capacity"]["requests_per_user_per_second"] == catalog.CAPACITY_REQUESTS_PER_SECOND


def test_capacity_curve_names_the_largest_level_served_within_the_budget():
    import yaml

    analyse = _analyse()
    budgets = yaml.safe_load((_PERF / "budgets.yaml").read_text())

    def level(users, count, failures, rps, p95):
        return {"scenario": "capacity", "tier": "T2", "users": str(users), "count": str(count), "failures": str(failures),
                "rps": str(rps), "p95_ms": str(p95)}

    healthy = analyse.capacity_curve([level(16, 960, 0, 16, 40), level(32, 1920, 0, 32, 60), level(64, 3600, 0, 60, 400)], budgets)
    assert healthy["usable_users"] == 64 and healthy["first_unusable"] is None
    saturated = analyse.capacity_curve(
        [level(16, 960, 0, 16, 40), level(32, 1900, 0, 31, 90), level(64, 3000, 0, 40, 2500), level(128, 2000, 300, 45, 4000)], budgets,
    )
    assert saturated["usable_users"] == 32 and saturated["first_unusable"]["users"] == 64
    assert saturated["levels"][2]["delivered"] == 0.625
    # A later level that happens to look fine does not extend the usable range.
    lucky = analyse.capacity_curve([level(16, 960, 0, 16, 40), level(32, 100, 50, 30, 90), level(64, 3600, 0, 64, 100)], budgets)
    assert lucky["usable_users"] == 16
    assert analyse.capacity_curve([], budgets) == {"levels": [], "usable_users": None, "first_unusable": None}


def test_capacity_users_option_is_validated():
    from perf import run_profile

    assert run_profile.parse_args(["lab-host", "--capacity-users", "8,24,96"]).capacity_users == (8, 24, 96)
    assert run_profile.parse_args(["lab-host"]).capacity_users is None
    for bad in ("0", "8,x", "2000"):
        with pytest.raises(SystemExit):
            run_profile.parse_args(["lab-host", "--capacity-users", bad])


def test_a_capacity_level_ends_the_climb_when_requests_fail_or_the_rate_is_not_delivered():
    from perf import run_profile

    run = run_profile.ProfileRun(run_profile.parse_args(["lab-host"]))
    run.sampler = type("Rows", (), {"rows": [
        {"tier": "T2", "scenario": "capacity", "users": 64, "service": "loadgen", "cpu_percent": 20.0},
        {"tier": "T2", "scenario": "capacity", "users": 64, "service": "backend", "cpu_percent": 300.0},
    ]})()

    def summary(count, failures, rps):
        return {"total": {"count": count, "failures": failures, "rps": rps}}

    assert run.capacity_step_ends("T2", 64, summary(2900, 0, 64.0)) is False
    assert run.capacity_step_ends("T2", 64, summary(2000, 300, 60.0)) is True       # 15% fail
    assert run.capacity_step_ends("T2", 64, summary(1200, 0, 25.0)) is True         # 39% of the offered rate
    assert "stopped here" in run.notes[-1] and "64 users" in run.notes[-1]


def test_a_stalled_capacity_level_is_named_and_the_backend_is_given_time_to_settle(monkeypatch):
    from perf import run_profile

    run = run_profile.ProfileRun(run_profile.parse_args(["lab-host"]))
    run.sampler = type("Rows", (), {"rows": []})()
    assert run.capacity_step_ends("T2", 96, {"total": {"count": 0, "failures": 0, "rps": 0.0}}) is True
    assert "NO REQUEST COMPLETED" in run.notes[-1]

    readings = iter([60.0, 40.0, 5.0, 3.0])
    run.sampler = type("Sampler", (), {"poll_once": lambda self: [{"service": "backend", "cpu_percent": next(readings)}]})()
    monkeypatch.setattr(run_profile.time, "sleep", lambda seconds: None)
    run.settle_backend(limit_seconds=60)
    assert next(readings, None) is None, "it read until two quiet samples in a row, then stopped"
    assert not any("still busy" in note for note in run.notes)


def test_the_capacity_climb_stops_at_the_first_failing_level(monkeypatch):
    from perf import run_profile

    run = run_profile.ProfileRun(run_profile.parse_args(["lab-host", "--scenarios", "capacity", "--tiers", "T2", "--capacity-users", "8,32,96,192"]))
    run.summary = {"tiers": {"T2": 1000}}
    run.sampler = type("S", (), {"rows": [], "tag": lambda self, **tags: None, "poll_once": lambda self: []})()
    ran = []
    delivered = {8: 8.0, 32: 30.0, 96: 20.0, 192: 20.0}

    def fake_loadgen(manifest, scenario, params):
        ran.append(params["users"])
        return {"requests": [], "total": {"count": 1000, "failures": 0, "rps": delivered[params["users"]]}}

    monkeypatch.setattr(run, "run_loadgen", fake_loadgen)
    for name in ("pg_begin", "check_backend_health", "settle_backend"):
        monkeypatch.setattr(run, name, lambda *a, **k: None)
    monkeypatch.setattr(run, "pg_end", lambda *a, **k: None)
    monkeypatch.setattr(run, "record_snapshot", lambda *a, **k: None)
    run.run_scenarios("T2", {}, ["capacity"])
    assert ran == [8, 32, 96], "96 users delivered 21% of the offered rate, so 192 is not run"
