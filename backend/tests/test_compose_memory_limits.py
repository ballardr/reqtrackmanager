"""
Pins the memory limits of the production Compose stack (`docker-compose.yml`).

Why: every always-on service carries a limit taken from the measured peaks in docs/performance.md, so a runaway
service is killed by its own cap instead of taking the host down. A limit that is missing, that cannot be set from
`.env`, or that is too small for the default worker count (the kernel would OOM-kill the backend on its first busy
day) is a defect no other test sees, because the test stacks do not use this file.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"

pytestmark = pytest.mark.skipif(not COMPOSE.is_file(), reason="repository root not available")

# Services without a Compose profile: what a plain `docker compose up` starts.
ALWAYS_ON = {"db": "DB_MEM_LIMIT", "storage": "STORAGE_MEM_LIMIT", "backend": "BACKEND_MEM_LIMIT",
             "frontend": "FRONTEND_MEM_LIMIT", "mcp-server": "MCP_MEM_LIMIT"}

MIB_PER_WORKER = 560  # measured private memory of one worker under load (docs/performance.md, Sizing)
UNITS = {"m": 1, "g": 1024}


@pytest.fixture(scope="module")
def services() -> dict:
    """Returns the parsed `services` mapping of docker-compose.yml."""
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _default_mib(value: str, variable: str) -> int:
    """Returns the default (in MiB) of a `${VARIABLE:-<n><m|g>}` expression, failing if it is not that shape."""
    match = re.fullmatch(r"\$\{" + variable + r":-(\d+)([mg])\}", str(value))
    assert match, f"mem_limit must be ${{{variable}:-<n>m|g}}, got {value!r}"
    return int(match.group(1)) * UNITS[match.group(2)]


def test_every_always_on_service_has_an_env_tunable_limit(services):
    """A plain `docker compose up` starts no service without a memory limit an operator can raise from `.env`."""
    for name, variable in ALWAYS_ON.items():
        assert "mem_limit" in services[name], f"{name} has no mem_limit"
        assert _default_mib(services[name]["mem_limit"], variable) > 0
    always_on = {n for n, s in services.items() if "profiles" not in s}
    assert always_on == set(ALWAYS_ON), "a new always-on service needs a measured limit and an entry here"


def test_backend_default_limit_fits_the_default_worker_count(services):
    """The backend's default limit covers the default workers at the measured per-worker memory, plus the parent."""
    environment = services["backend"]["environment"]["BACKEND_WORKERS"]
    workers = int(re.fullmatch(r"\$\{BACKEND_WORKERS:-(\d+)\}", environment).group(1))
    limit = _default_mib(services["backend"]["mem_limit"], "BACKEND_MEM_LIMIT")
    assert limit >= workers * MIB_PER_WORKER + 100, "raise BACKEND_MEM_LIMIT's default with the worker count"


def _run_entrypoint(tmp_path, limit: str, workers: int) -> str:
    """Runs the backend entrypoint (two or more workers, so it ends in the stand-in `uvicorn`, never a real server)
    with a stand-in `uvicorn` and a fake cgroup limit file; returns its stderr."""
    import os
    import stat
    import subprocess

    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    uvicorn = fake / "uvicorn"
    uvicorn.write_text("#!/bin/sh\nexit 0\n")
    uvicorn.chmod(uvicorn.stat().st_mode | stat.S_IEXEC)
    limit_file = tmp_path / "memory.max"
    limit_file.write_text(limit)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "MEMORY_LIMIT_FILE": str(limit_file),
           "BACKEND_WORKERS": str(workers), "PROMETHEUS_MULTIPROC_DIR": str(tmp_path / "prom")}
    result = subprocess.run(["sh", str(ROOT / "backend" / "docker-entrypoint.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stderr


def test_the_entrypoint_warns_when_the_memory_limit_cannot_hold_the_workers(tmp_path):
    """Four workers need about 2.3 GiB: a 1 GiB limit warns, a 3.5 GiB limit and "max" (no limit) stay silent."""
    assert "WARNING" in _run_entrypoint(tmp_path, str(1024 * 1024 * 1024), 4)
    assert _run_entrypoint(tmp_path, str(3500 * 1024 * 1024), 4) == ""
    assert _run_entrypoint(tmp_path, "max\n", 4) == ""
    assert _run_entrypoint(tmp_path, str(2048 * 1024 * 1024), 2) == ""  # two workers need about 1.2 GiB
