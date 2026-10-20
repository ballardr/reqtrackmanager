"""
Pins the "IPv6 is always supported" rule: every shipped listener accepts IPv6
as well as IPv4, so an IPv6-first or IPv6-only host can reach every service.

Skipped when the repository root is not visible (the backend container mounts
only backend/).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "frontend").is_dir(), reason="repository checkout not available")


@pytest.mark.parametrize("conf", ["frontend/nginx.conf", "docs/website/nginx.conf.template"])
def test_nginx_listens_on_both_address_families(conf):
    """Each nginx server block has an IPv4 and an IPv6 `listen` for its port."""
    text = (ROOT / conf).read_text()
    port = re.search(r"^\s*listen (\d+);", text, re.MULTILINE).group(1)
    assert re.search(rf"^\s*listen \[::\]:{port};", text, re.MULTILINE)


@pytest.mark.parametrize(
    "path",
    ["backend/docker-entrypoint.sh", "mcp-server/server.py", "docs/website/Dockerfile"],
)
def test_server_processes_do_not_bind_ipv4_only(path):
    """No server process is started on the IPv4-only wildcard address."""
    text = "\n".join(line for line in (ROOT / path).read_text().splitlines() if not line.lstrip().startswith("#"))
    assert "0.0.0.0" not in text
    assert re.search(r'(--host :: |host="::"|"--host", "::")', text)
