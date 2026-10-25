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
    swapping = resources.preflight_headroom(caps, total_requirements=1000, disk_path=Path("/"), **{**ok, "swap": lambda: 3.0})
    full = resources.preflight_headroom(caps, total_requirements=20000, disk_path=Path("/"), **{**ok, "free_disk": lambda p: 8.0})
    assert "busy" in busy[0] and "memory" in low_memory[0] and "swap" in swapping[0] and "disk" in full[0]


def test_watchdog_trips_on_each_pressure_signal_and_calls_back_once():
    base = {"load": lambda: 0.1, "available": lambda: 8.0, "swap": lambda: 0.0, "free_disk": lambda p: 50.0}
    tripped: list = []
    for name, reader, text in (
        ("load", lambda: 5.0, "load"),
        ("available", lambda: 0.2, "memory"),
        ("swap", lambda: 5.0, "swap"),
        ("free_disk", lambda p: 1.0, "disk"),
    ):
        dog = resources.Watchdog(resources.Thresholds(), Path("/"), readers={**base, name: reader}, on_trip=tripped.append)
        assert text in dog.check_once() and dog.tripped
    healthy = resources.Watchdog(resources.Thresholds(), Path("/"), readers=base)
    assert healthy.check_once() is None and not healthy.tripped


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
