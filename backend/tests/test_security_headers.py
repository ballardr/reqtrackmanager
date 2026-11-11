"""Security headers: the API's own, and the front-end proxy configurations (nginx here, Caddy for the demonstration)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FRONTEND_PRESENT = (REPO / "frontend" / "nginx.conf").exists()
needs_frontend_sources = pytest.mark.skipif(not FRONTEND_PRESENT, reason="frontend sources are not available (backend-only image)")


def _read(path: Path) -> str:
    """The file's text, or an empty string where the repository is not mounted (the tests that need it are skipped)."""
    return path.read_text() if path.exists() else ""


NGINX = _read(REPO / "frontend" / "nginx.conf")
HEADERS_INC = _read(REPO / "frontend" / "docker" / "security-headers.inc")
ENTRYPOINT = _read(REPO / "frontend" / "docker" / "env-config-entrypoint.sh")
_CADDY_DIR = REPO / "tests" / "container" / "caddy"
CADDY = "\n".join(p.read_text() for p in sorted(_CADDY_DIR.rglob("*")) if p.is_file()) if _CADDY_DIR.exists() else ""


def test_api_json_is_not_cached_and_carries_the_baseline_headers(client, admin_token):
    from tests.conftest import auth_headers

    response = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_only_json_without_a_policy_of_its_own_is_marked_no_store(client):
    assert "cache-control" not in client.get("/metrics").headers  # not JSON: the exposition format is left alone


@needs_frontend_sources
@pytest.mark.parametrize("header", [
    "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security",
    "Content-Security-Policy",
])
def test_the_front_end_proxy_sends_every_security_header(header):
    assert header in HEADERS_INC or header == "Content-Security-Policy" and "content-security-policy.inc" in HEADERS_INC


@needs_frontend_sources
def test_every_location_that_adds_a_header_includes_the_security_set_again():
    """nginx drops the server block's `add_header` lines in a location that has its own, so each one must include the set."""
    for match in re.finditer(r"location [^{]+\{(?P<body>[^}]*)\}", NGINX):
        body = match.group("body")
        if "add_header" in body:
            assert "security-headers.inc" in body, match.group(0)


@needs_frontend_sources
def test_the_policy_is_built_from_checked_values_and_names_the_hardening_directives():
    for directive in ("object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'", "script-src 'self'"):
        assert directive in ENTRYPOINT
    assert "origin_ok" in ENTRYPOINT  # an environment value is checked before it reaches the header
    assert "unsafe-eval" not in ENTRYPOINT and "script-src 'self' 'unsafe-inline'" not in ENTRYPOINT


@pytest.mark.skipif(not CADDY, reason="tests/container is not available (backend-only image)")
def test_the_demonstration_proxy_sets_strict_transport_security_for_a_public_certificate():
    """The other headers come from the services behind it, which the proxy passes through unchanged."""
    assert "Strict-Transport-Security" in CADDY
