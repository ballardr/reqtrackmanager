"""Tests for organisation renaming and the "send test email" admin actions:
the deployment-wide one (`POST /system/test-email`, server-admin only,
always via `Settings.smtp_*`) and the organisation-scoped one
(`POST /orgs/{id}/test-email`, org-admin only, via that org's own
`Organization.smtp_*` override — see `services/email.py`'s module
docstring and docs/decisions.md's "SMTP/SSO organisation settings are a
storage-only seam" entry for why this is currently the only thing that
reads those columns). Email delivery itself is mocked (verified for real
against MailHog in docs/decisions.md's manual verification), matching
`test_digest.py`'s existing approach.
"""

from unittest.mock import Mock, patch

from app.routers import orgs as orgs_router
from app.routers import system as system_router
from tests.conftest import auth_headers, create_org_user, login

# ---------------------------------------------------------------------------
# Organisation rename
# ---------------------------------------------------------------------------


def test_org_admin_can_rename_organization(client, admin_token, org_id):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/name", json={"name": "  Renamed Org  "}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    # Whitespace is trimmed, same as OrganizationCreate.name.
    assert resp.json()["name"] == "Renamed Org"

    fetched = client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(admin_token))
    assert fetched.json()["name"] == "Renamed Org"


def test_rename_organization_rejects_blank_name(client, admin_token, org_id):
    resp = client.put(f"/api/v1/orgs/{org_id}/name", json={"name": "   "}, headers=auth_headers(admin_token))
    assert resp.status_code == 422


def test_member_cannot_rename_organization(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "rename_member@example.com", role="member")
    member_token = login(client, "rename_member@example.com", "Password123!")
    resp = client.put(
        f"/api/v1/orgs/{org_id}/name", json={"name": "Hijacked Name"}, headers=auth_headers(member_token)
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Deployment-wide test email (POST /system/test-email)
# ---------------------------------------------------------------------------


def test_system_test_email_defaults_to_caller_and_uses_deployment_smtp(client, admin_token):
    with patch.object(system_router, "send_email", new=Mock()) as mock_send:
        resp = client.post("/api/v1/system/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert args[0] == "admin@example.com"
    # No smtp_override -> send_email falls back to the deployment-wide Settings.
    assert kwargs.get("smtp_override") is None
    # A real rendered HTML email (services/email_templates.py), not a bare string.
    assert "<html" in kwargs["html_body"].lower()
    assert "deployment-wide SMTP configuration" in kwargs["html_body"]


def test_system_test_email_honours_explicit_recipient(client, admin_token):
    with patch.object(system_router, "send_email", new=Mock()) as mock_send:
        resp = client.post(
            "/api/v1/system/test-email", json={"to_email": "someone-else@example.com"},
            headers=auth_headers(admin_token),
        )
    assert resp.status_code == 204, resp.text
    assert mock_send.call_args.args[0] == "someone-else@example.com"


def test_system_test_email_requires_server_admin(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "not_server_admin@example.com", role="org_admin")
    member_token = login(client, "not_server_admin@example.com", "Password123!")
    with patch.object(system_router, "send_email", new=Mock()) as mock_send:
        resp = client.post("/api/v1/system/test-email", json={}, headers=auth_headers(member_token))
    assert resp.status_code == 403
    mock_send.assert_not_called()


def test_system_test_email_send_failure_returns_502_with_reason(client, admin_token):
    with patch.object(system_router, "send_email", new=Mock(side_effect=ConnectionRefusedError("refused"))):
        resp = client.post("/api/v1/system/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 502
    assert "refused" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Organisation-scoped test email (POST /orgs/{id}/test-email)
# ---------------------------------------------------------------------------


def test_org_test_email_requires_smtp_configured(client, admin_token, org_id):
    resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 400
    assert "smtp" in resp.json()["detail"].lower()


def test_org_test_email_uses_orgs_own_smtp_override(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={
            "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_username": "relay-user",
            "smtp_password": "super-secret", "smtp_use_tls": True, "sso_group_mappings": [],
        },
        headers=auth_headers(admin_token),
    )

    with patch.object(orgs_router, "send_email", new=Mock()) as mock_send:
        resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert args[0] == "admin@example.com"  # defaults to the caller
    override = kwargs["smtp_override"]
    assert override.host == "smtp.example.com"
    assert override.port == 587
    assert override.username == "relay-user"
    assert override.password == "super-secret"
    assert override.use_tls is True
    # Real rendered HTML using this org's own branding/name, not a bare string.
    assert "<html" in kwargs["html_body"].lower()


def test_org_test_email_requires_org_admin(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_use_tls": True, "sso_group_mappings": []},
        headers=auth_headers(admin_token),
    )
    create_org_user(client, admin_token, org_id, "org_test_email_member@example.com", role="member")
    member_token = login(client, "org_test_email_member@example.com", "Password123!")

    with patch.object(orgs_router, "send_email", new=Mock()) as mock_send:
        resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(member_token))
    assert resp.status_code == 403
    mock_send.assert_not_called()


def test_org_test_email_send_failure_returns_502_with_reason(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_use_tls": True, "sso_group_mappings": []},
        headers=auth_headers(admin_token),
    )
    with patch.object(orgs_router, "send_email", new=Mock(side_effect=TimeoutError("timed out"))):
        resp = client.post(f"/api/v1/orgs/{org_id}/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 502
    assert "timed out" in resp.json()["detail"]
