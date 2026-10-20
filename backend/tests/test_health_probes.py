"""
Pins scripts/check_health_probes.py: container health probes must address
`127.0.0.1`, not `localhost`, so an IPv6-first host cannot report a working
IPv4-only service as unhealthy.

Skipped when the repository root is not visible (the backend container mounts
only backend/); CI's `docs` job and the pre-commit hook run the script directly.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_health_probes.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("check_health_probes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None, reason="repository checkout not available")


def test_every_probe_in_the_repository_uses_the_ipv4_loopback():
    """No Dockerfile or Compose probe addresses `localhost`."""
    assert checker.find_problems() == []


def test_checker_flags_localhost_probes_in_dockerfiles_and_compose():
    """Both probe shapes are caught, and a comment or non-probe use is not."""
    dockerfile = "HEALTHCHECK --interval=10s \\\n    CMD wget -qO- http://localhost:3000/health || exit 1\n"
    compose = '    healthcheck:\n      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n'
    assert checker.check_text(dockerfile) == [2]
    assert checker.check_text(compose) == [2]
    assert checker.check_text("# wget http://localhost:3000/health\nENV URL=http://localhost:3000\n") == []
    assert checker.check_text(dockerfile.replace("localhost", "127.0.0.1")) == []
