"""Tests for developer profiling (`app.profiling`, `scripts/profile_tools.py`, the `profile` image target and
`docker-compose.profile.yml`).

Pinned here: profile mode is off by default and adds nothing to the application when off; when on, every request's
database statements are attributed to its route template (including from a threadpool endpoint), the output carries
counts and parameterised statement text but no bound value, and probes are not counted; the in-container tool
merges worker files, classifies processes and only ever signals a verified worker; and the profilers stay out of
the production image and compose file.

Process-table reads use a fake `/proc` tree, so the tests run on any platform. The real tools are exercised by a
`perf/run_profile.sh --profiling` run.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import signal
import sys
import tracemalloc
import types
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app import profiling
from app.config import Settings

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent


def _load_tools():
    spec = importlib.util.spec_from_file_location("profile_tools", _BACKEND / "scripts" / "profile_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = _load_tools()


@pytest.fixture(autouse=True)
def _clean_totals():
    profiling.reset()
    yield
    profiling.reset()


def _app_and_engine():
    """A tiny application with the profile middleware, and an instrumented in-memory database."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    profiling.instrument_engine(engine)
    engine.connect().close()  # the dialect's first-connect statements are not the application's
    app = FastAPI()
    app.middleware("http")(profiling.profile_middleware)

    @app.get("/items/{item_id}")
    def item(item_id: int):  # a sync endpoint runs in the threadpool: the context must follow it there
        with engine.connect() as connection:
            for _ in range(3):
                connection.execute(text("select :value"), {"value": item_id})
            connection.execute(text("select 1"))
        return {"ok": True}

    @app.get("/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        return {"ok": True}

    return app, engine


# --- off by default --------------------------------------------------------------------------------------


def test_profile_mode_is_off_by_default_and_the_application_registers_nothing_for_it():
    settings = Settings(_env_file=None)
    assert settings.profile_mode is False and settings.profile_tracemalloc is False
    from app.main import app

    dispatchers = [getattr(m.kwargs.get("dispatch"), "__name__", "") for m in app.user_middleware]
    assert "profile_middleware" not in dispatchers
    assert not [r for r in app.routes if "profil" in getattr(r, "path", "")], "profile mode adds no endpoint"


def test_profile_mode_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("PROFILE_MODE", "true")
    monkeypatch.setenv("PROFILE_OUTPUT_DIR", "/somewhere")
    settings = Settings(_env_file=None)
    assert settings.profile_mode is True and settings.profile_output_dir == "/somewhere"


# --- counting --------------------------------------------------------------------------------------------


def test_statements_are_attributed_to_the_route_template_across_requests_and_threads():
    app, _ = _app_and_engine()
    client = TestClient(app)
    for item_id in (1, 2):
        assert client.get(f"/items/{item_id}").status_code == 200
    stats = profiling.routes_snapshot()["GET /items/{item_id}"]
    assert stats["requests"] == 2 and stats["queries"] == 8 and stats["max_queries"] == 4
    assert stats["repeat_count"] == 3, "the statement a request repeated most is kept for N+1 diagnosis"
    assert stats["db_ms"] >= 0


def test_probes_unmatched_paths_and_work_outside_a_request():
    app, engine = _app_and_engine()
    client = TestClient(app)
    client.get("/health")
    client.get("/nothing-here")
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    snapshot = profiling.routes_snapshot()
    assert set(snapshot) == {"GET unmatched"}, "a probe is not product traffic and statements outside a request have no route"
    assert snapshot["GET unmatched"]["queries"] == 0


def test_the_output_carries_no_bound_value_or_resolved_path():
    app, _ = _app_and_engine()
    TestClient(app).get("/items/424242")
    document = json.dumps(profiling.routes_snapshot())
    assert "424242" not in document, "bound values and resolved ids never reach the output"
    assert "{item_id}" in document


def test_a_long_statement_is_truncated_and_whitespace_normalised():
    record = profiling.RequestRecord()
    record.add("select\n   a,\n   b from t " + "x" * 1000, 0.001)
    ((statement, _count),) = record.statements.items()
    assert "\n" not in statement and statement.startswith("select a, b from t") and len(statement) == profiling.STATEMENT_CHARS


def test_route_stats_keep_the_worst_repeat_and_the_largest_request():
    stats = profiling.RouteStats()
    for repeats in (2, 9, 4):
        record = profiling.RequestRecord()
        for _ in range(repeats):
            record.add("select 1", 0.002)
        record.add("select 2", 0.001)
        stats.add(record)
    assert stats.requests == 3 and stats.max_queries == 10 and stats.repeat_count == 9 and stats.repeat_statement == "select 1"
    assert stats.as_dict()["queries"] == 15 + 3


# --- output files ----------------------------------------------------------------------------------------


def test_query_stats_are_written_atomically_one_file_per_worker(tmp_path):
    profiling._ROUTES["GET /x"] = profiling.RouteStats(requests=1, queries=2)
    path = profiling.write_query_stats(tmp_path / "out")
    assert re.fullmatch(r"query_stats_\d+\.json", path.name)
    assert json.loads(path.read_text())["routes"]["GET /x"]["queries"] == 2
    assert not list(path.parent.glob("*.tmp")), "no half-written file is left behind"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/usr/local/lib/python3.12/site-packages/pydantic/main.py", "pydantic/main.py"),
        ("/app/app/services/search.py", "app/services/search.py"),
        ("/srv/elsewhere/helper.py", "helper.py"),
    ],
)
def test_source_paths_are_shortened_so_no_layout_or_user_detail_is_written(path, expected):
    assert profiling.relative_location(path) == expected


def test_allocation_growth_names_the_line_that_grew():
    tracemalloc.start(5)
    try:
        baseline = tracemalloc.take_snapshot()
        kept = [bytearray(2000) for _ in range(400)]  # noqa: F841 - held so the allocation is still live
        growth = profiling.allocation_growth(baseline, tracemalloc.take_snapshot())
    finally:
        tracemalloc.stop()
    assert growth and re.search(r"test_profiling\.py:\d+$", growth[0]["location"])
    assert growth[0]["size_diff_kib"] > 500 and all(row["size_diff_kib"] > 0 for row in growth)


def test_the_profile_loop_writes_query_totals_and_allocation_growth_and_survives_a_failed_write(tmp_path, monkeypatch):
    monkeypatch.setattr(profiling, "TRACEMALLOC_INTERVAL_SECONDS", 0)
    profiling._ROUTES["GET /x"] = profiling.RouteStats(requests=1, queries=1)

    async def run() -> None:
        task = asyncio.create_task(profiling.run_profile_loop(tmp_path, tracemalloc_enabled=True, baseline_seconds=0, interval_seconds=0.01))
        await asyncio.sleep(0.4)
        assert not task.done(), "a loop that has not been cancelled keeps running"
        task.cancel()

    try:
        asyncio.run(run())
    finally:
        tracemalloc.stop()
    assert list(tmp_path.glob("query_stats_*.json"))
    growth = json.loads(next(tmp_path.glob("tracemalloc_*.json")).read_text())
    assert growth["traced_kib"] > 0 and isinstance(growth["growth"], list)


def test_the_loop_does_not_stop_when_the_output_directory_cannot_be_written(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")

    async def run() -> bool:
        task = asyncio.create_task(profiling.run_profile_loop(blocked / "sub", tracemalloc_enabled=False, baseline_seconds=0, interval_seconds=0.01))
        await asyncio.sleep(0.1)
        alive = not task.done()
        task.cancel()
        return alive

    assert asyncio.run(run())


# --- the in-container tool -------------------------------------------------------------------------------


def _proc(tmp_path, entries: dict) -> Path:
    """A fake process table: `{pid: (cmdline, smaps_rollup text or None)}`."""
    for pid, (cmdline, smaps) in entries.items():
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())
        if smaps is not None:
            (directory / "smaps_rollup").write_text(smaps)
    return tmp_path


def _smaps(rss: int, pss: int, private: int, shared: int) -> str:
    return f"Rss:  {rss} kB\nPss:  {pss} kB\nShared_Clean:  {shared} kB\nShared_Dirty: 0 kB\n" f"Private_Clean:  0 kB\nPrivate_Dirty:  {private} kB\n"


def test_memory_separates_private_from_shared_and_totals_by_pss(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tools,
        "PROC",
        _proc(
            tmp_path,
            {
                1: ("python /usr/local/bin/uvicorn app.main:app", _smaps(16384, 7168, 6144, 10240)),
                9: ("python -c from multiprocessing.resource_tracker import main", _smaps(9216, 3072, 2048, 7168)),
                10: ("python -c from multiprocessing.spawn import spawn_main", _smaps(460800, 430080, 424960, 35840)),
                11: ("python -c from multiprocessing.spawn import spawn_main", _smaps(450560, 419840, 414720, 35840)),
                20: ("sh -c something else", _smaps(1024, 1024, 1024, 0)),
                30: ("python scripts/profile_tools.py memory", None),
            },
        ),
    )
    result = tools.memory()
    rows = [(p["role"], p["index"]) for p in result["processes"]]
    assert rows == [("parent", 1), ("worker", 1), ("worker", 2), ("tracker", 1)]
    worker = result["processes"][1]
    assert worker["private_mib"] == 415.0 and worker["shared_mib"] == 35.0 and worker["rss_mib"] == 450.0
    assert result["pss_total_mib"] == round((7168 + 3072 + 430080 + 419840) / 1024, 1)


def test_one_process_serving_requests_is_reported_as_single(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "PROC", _proc(tmp_path, {1: ("python /usr/local/bin/uvicorn app.main:app", _smaps(400000, 400000, 390000, 10000))}))
    assert [p["role"] for p in tools.memory()["processes"]] == ["single"]


def test_query_totals_of_every_worker_are_merged_and_a_bad_file_is_skipped(tmp_path):
    route = {"requests": 4, "queries": 12, "db_ms": 8.0, "max_queries": 4, "repeat_statement": "select a", "repeat_count": 2}
    other = {"requests": 6, "queries": 30, "db_ms": 20.5, "max_queries": 7, "repeat_statement": "select b", "repeat_count": 6}
    (tmp_path / "query_stats_1.json").write_text(json.dumps({"routes": {"GET /a": route}}))
    (tmp_path / "query_stats_2.json").write_text(json.dumps({"routes": {"GET /a": other, "GET /b": route}}))
    (tmp_path / "query_stats_3.json").write_text("{not json")
    merged = tools.queries(tmp_path)
    assert merged["GET /a"] == {"requests": 10, "queries": 42, "db_ms": 28.5, "max_queries": 7, "repeat_statement": "select b", "repeat_count": 6}
    assert merged["GET /b"]["requests"] == 4
    assert tools.queries(tmp_path / "missing") == {}


def test_a_baseline_signal_goes_only_to_a_verified_worker(tmp_path, monkeypatch):
    for pid in (111, 222, 1):
        (tmp_path / f"tracemalloc_{pid}.json").write_text("{}")
    sent = []
    monkeypatch.setattr(tools, "is_worker", lambda pid: pid == 111)
    monkeypatch.setattr(tools.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    result = tools.rebaseline(tmp_path)
    assert sorted(sent) == [(1, signal.SIGUSR2), (111, signal.SIGUSR2)]
    assert 222 not in result["signalled"], "a recycled pid that is not a worker must never receive SIGUSR2 (its default action is to terminate)"


@pytest.mark.parametrize(
    ("filename", "package", "location"),
    [
        ("/usr/local/lib/python3.12/site-packages/pydantic/main.py", "site-packages/pydantic", "pydantic/main.py"),
        ("/usr/local/lib/python3.12/site-packages/six.py", "site-packages/six", "six.py"),
        ("/app/app/main.py", "app/main", "app/main.py"),
        ("/app/app/services/search.py", "app/services", "app/services/search.py"),
        ("/app/app/modules/risk/models.py", "app/modules/risk", "app/modules/risk/models.py"),
        ("/usr/local/lib/python3.12/json/decoder.py", "stdlib", "decoder.py"),
        ("<unknown>", "other", "<unknown>"),
    ],
)
def test_allocation_sites_are_grouped_by_package_and_shortened(filename, package, location):
    assert tools._package(filename) == package
    assert tools._location(filename) == location


def test_heap_summary_attributes_live_memory_to_the_first_frame_outside_the_import_machinery(monkeypatch):
    class Record:
        def __init__(self, size, count, frames):
            self.size, self.n_allocations, self._frames = size, count, frames

        def stack_trace(self):
            return self._frames

    records = [
        Record(3 * 2**20, 100, [("_compile", "<frozen importlib._bootstrap_external>", 1), ("<module>", "/app/app/modules/risk/models.py", 12)]),
        Record(1 * 2**20, 10, [("build", "/usr/local/lib/python3.12/site-packages/pydantic/main.py", 40)]),
        Record(1 * 2**20, 5, [("build", "/usr/local/lib/python3.12/site-packages/pydantic/main.py", 40)]),
    ]

    class FileReader:
        def __init__(self, path):
            self.metadata = types.SimpleNamespace(peak_memory=9 * 2**20)

        def get_leaked_allocation_records(self, merge_threads=True):
            return records

    monkeypatch.setitem(sys.modules, "memray", types.SimpleNamespace(FileReader=FileReader))
    result = tools.heap(Path("capture.bin"))
    assert result["live_mib"] == 5.0 and result["peak_mib"] == 9.0
    assert result["by_package"][0] == {"name": "app/modules/risk", "mib": 3.0, "allocations": 100}
    assert result["by_package"][1] == {"name": "site-packages/pydantic", "mib": 2.0, "allocations": 15}
    assert result["by_location"][1]["name"] == "pydantic/main.py:40 build"


# --- the profilers stay out of production ----------------------------------------------------------------

_COMPOSE = _ROOT / "docker-compose.yml"
_PROFILE_COMPOSE = _ROOT / "docker-compose.profile.yml"
_DOCKERFILE = _BACKEND / "Dockerfile"
_repo_files = pytest.mark.skipif(
    not (_COMPOSE.exists() and _PROFILE_COMPOSE.exists() and _DOCKERFILE.exists()), reason="repository root files not mounted"
)


@_repo_files
def test_the_production_compose_file_has_no_profiling_setting():
    text_ = _COMPOSE.read_text()
    for needle in ("PROFILE_", "SYS_PTRACE", "docker-compose.profile", "target: profile", "memray", "py-spy"):
        assert needle not in text_, f"{needle} belongs in docker-compose.profile.yml only"


@_repo_files
def test_the_profile_override_adds_the_profile_target_one_capability_and_publishes_nothing():
    backend = yaml.safe_load(_PROFILE_COMPOSE.read_text())["services"]["backend"]
    assert backend["build"]["target"] == "profile"
    assert backend["cap_add"] == ["SYS_PTRACE"]
    assert backend["environment"]["PROFILE_MODE"] == "true"
    assert "ports" not in backend and not backend.get("privileged")
    assert "ghcr.io" not in backend["image"], "a profile build must never retag a published image"


@_repo_files
def test_the_profilers_are_installed_only_in_the_profile_stage_which_is_not_the_default():
    code = "\n".join(line for line in _DOCKERFILE.read_text().splitlines() if not line.lstrip().startswith("#"))
    stages = re.split(r"(?m)^FROM ", code)[1:]
    names = [re.search(r" AS (\w+)", stage).group(1) for stage in stages]
    assert names[-1] == "backend", "the last stage is the default build target and must stay the plain API image"
    assert "profile" in names
    for stage, name in zip(stages, names, strict=False):
        assert ("memray" in stage) == (name == "profile"), f"stage {name}"
    requirements = (_BACKEND / "requirements.txt").read_text().lower()
    assert "memray" not in requirements and "py-spy" not in requirements


# --- the single-process entry is dual-stack ---------------------------------------------------------------


def test_the_single_process_listener_accepts_ipv4_and_ipv6():
    """`uvicorn --workers 1 --host ::` is IPv6 only (asyncio sets IPV6_V6ONLY); app.serve must not be."""
    import socket

    from app import serve

    if not socket.has_ipv6:
        pytest.skip("no IPv6 on this host")
    try:
        sock = serve.bind_dual_stack("::", 0)
    except OSError:
        pytest.skip("cannot bind an IPv6 socket here")
    with sock:
        sock.listen()
        port = sock.getsockname()[1]
        assert sock.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                client = socket.socket(family)
            except OSError:
                continue
            with client:
                client.settimeout(3)
                client.connect((address, port))


def test_one_worker_is_served_by_the_dual_stack_entry_and_more_by_uvicorn_itself():
    script = (_BACKEND / "docker-entrypoint.sh").read_text()
    assert re.search(r"-le 1 \]; then\s+exec python -m app\.serve", script)
    assert "--host ::" in script and "--workers" in script
    assert "-m app.serve" in (_BACKEND / "scripts" / "profile_entrypoint.sh").read_text()
