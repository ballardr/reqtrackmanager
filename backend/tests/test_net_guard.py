"""Tests for `services.net_guard`, the check that keeps a tenant-supplied hostname from aiming a server-side
connection at the platform's own network, and for its use on an organisation's SMTP relay."""

from unittest.mock import Mock, patch

import pytest

from app.routers.orgs import settings as orgs_settings_router
from app.services.net_guard import assert_public_host
from tests.conftest import auth_headers


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.1.2.3", "192.168.0.10", "169.254.169.254", "::1", "172.16.0.5"])
def test_private_and_loopback_hosts_are_refused(host):
    with pytest.raises(ValueError):
        assert_public_host(host)


def test_a_global_address_literal_is_accepted():
    assert_public_host("93.184.216.34")


@pytest.mark.parametrize("host", ["", "   "])
def test_an_empty_host_is_refused(host):
    with pytest.raises(ValueError):
        assert_public_host(host)


def test_the_refusal_never_contains_the_resolved_address():
    with pytest.raises(ValueError) as excinfo:
        assert_public_host("localhost")
    assert "127.0.0.1" not in str(excinfo.value)


def _configure_smtp(client, admin_token, org_id, host):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_host": host, "smtp_port": 25, "smtp_use_tls": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def test_org_test_email_will_not_connect_to_an_internal_address(client, admin_token, org_id):
    """An organisation administrator cannot use the test-email action to make the server open a connection to
    its own network: nothing is sent, and the response is the guard's refusal."""
    _configure_smtp(client, admin_token, org_id, "169.254.169.254")
    with patch.object(orgs_settings_router, "send_email", new=Mock()) as mock_send:
        resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 400
    assert "SMTP host refused" in resp.json()["detail"]
    mock_send.assert_not_called()


def test_the_operator_can_opt_an_internal_relay_in(client, admin_token, org_id, monkeypatch):
    monkeypatch.setattr(orgs_settings_router.settings, "org_smtp_allow_private_network_targets", True)
    _configure_smtp(client, admin_token, org_id, "10.0.0.25")
    with patch.object(orgs_settings_router, "send_email", new=Mock()) as mock_send:
        resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    mock_send.assert_called_once()
