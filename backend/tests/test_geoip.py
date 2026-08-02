"""Tests for the optional IP geolocation lookup (C-A-07).

Real network calls are never exercised here — only the gating logic
(disabled by default, excluded ranges, non-blocking login) is tested, since
hitting a real third-party service in CI would be flaky and slow.
"""

from unittest.mock import patch

from app.config import get_settings
from app.services import geoip


def test_disabled_by_default():
    assert get_settings().geoip_lookup_enabled is False


def test_private_and_loopback_ranges_are_excluded_by_default():
    for ip in ["127.0.0.1", "10.1.2.3", "172.16.0.5", "192.168.1.1", "::1"]:
        assert geoip._is_excluded(ip) is True


def test_public_ip_is_not_excluded_by_default():
    assert geoip._is_excluded("8.8.8.8") is False


def test_unparseable_address_is_excluded():
    """The TestClient's own `request.client.host` is the literal string
    "testclient", not a real IP — this must never reach the network."""
    assert geoip._is_excluded("testclient") is True


def test_resolve_and_store_does_nothing_when_disabled():
    with patch("httpx.get") as mock_get:
        geoip.resolve_and_store_login_location(login_event_id=None, ip_address="8.8.8.8")
        mock_get.assert_not_called()


def test_login_never_calls_the_geoip_service_directly(client, admin_token):
    """The login endpoint itself must never make the network call inline —
    only a scheduled background task may, and only when enabled (default
    off), so login latency/availability never depends on this feature."""
    with patch("httpx.get") as mock_get:
        resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": "ChangeMe123!"}
        )
        assert resp.status_code == 200
        mock_get.assert_not_called()
