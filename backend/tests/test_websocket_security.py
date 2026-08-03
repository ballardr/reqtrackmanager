"""Regression tests for two hardening-review findings in `routers/ws.py`:

- `token_version` wasn't checked at all, so a password change or 2FA
  disable — this system's "primary technical incident-containment tool"
  (access-control-policy.md) — did not actually revoke access to the
  WebSocket live-updates surface, contradicting docs/decisions.md's own
  (corrected) claim that this had already been fixed.
- `Organization.is_active` wasn't checked at all either (a later pass,
  alongside the organisation disable/hard-delete feature), so disabling an
  organisation — documented to lock out *everyone*, including its own
  admins, at every org/project-scoped surface — had no effect on this one
  surface: a member could still open a brand-new WebSocket connection to a
  disabled org's project and stream live updates indefinitely.

See `_user_session_still_valid` and the handshake check in `routers/ws.py`.
"""

from fastapi import WebSocketDisconnect

from app.routers.ws import _user_session_still_valid
from tests.conftest import auth_headers, create_project, login


def test_password_change_immediately_blocks_a_new_websocket_connection(client, admin_token, org_id):
    """A token that was valid before a password change must be rejected at
    the WebSocket handshake afterward — the same guarantee REST already
    provides via deps.py, now also covered here."""
    project = create_project(client, admin_token, org_id)
    old_token = admin_token

    # The pre-change token can open a connection.
    with client.websocket_connect(f"/ws/projects/{project['id']}?token={old_token}") as ws:
        ws.close()

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(old_token),
    )
    assert resp.status_code == 204

    # The pre-change token — now stale — must be rejected at handshake,
    # not allowed to open a live socket.
    try:
        with client.websocket_connect(f"/ws/projects/{project['id']}?token={old_token}"):
            raise AssertionError("Expected the stale, password-changed token to be rejected at handshake.")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401

    # A fresh token (from a fresh login with the new password) still works.
    new_token = login(client, "admin@example.com", "NewPassword123!")
    with client.websocket_connect(f"/ws/projects/{project['id']}?token={new_token}") as ws:
        ws.close()


def test_user_session_still_valid_reflects_a_token_version_bump(client, admin_token, org_id):
    """Unit-level coverage of the periodic recheck loop's own validity
    check (the handshake test above can't easily wait out the real
    60-second interval to prove the *ongoing* recheck also catches this,
    so this exercises the exact function that loop calls)."""
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    user_id = me["id"]

    # A token issued with the user's current token_version (0, fresh
    # bootstrap account) is valid...
    assert _user_session_still_valid(user_id, token_version=0, organization_id=None) is True

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    # ...but is no longer valid once token_version has moved on, even
    # though this check never looks at the JWT's expiry at all.
    assert _user_session_still_valid(user_id, token_version=0, organization_id=None) is False


def test_new_websocket_connection_rejected_after_org_disabled(client, admin_token):
    """A brand-new connection request must be rejected outright once the
    project's organisation is disabled — not just an already-open socket
    left running."""
    from tests.conftest import create_org_admin_in

    org, org_admin_token = create_org_admin_in(client, admin_token, "WS Disable Test Org")
    project = create_project(client, org_admin_token, org["id"])

    # Works fine while the org is active.
    with client.websocket_connect(f"/ws/projects/{project['id']}?token={org_admin_token}") as ws:
        ws.close()

    assert client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token)).status_code == 200

    try:
        with client.websocket_connect(f"/ws/projects/{project['id']}?token={org_admin_token}"):
            raise AssertionError("Expected a new connection to a disabled org's project to be rejected.")
    except WebSocketDisconnect as exc:
        assert exc.code == 4403

    # Re-enabling restores it.
    assert client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token)).status_code == 200
    with client.websocket_connect(f"/ws/projects/{project['id']}?token={org_admin_token}") as ws:
        ws.close()


def test_user_session_still_valid_reflects_org_disable(client, admin_token):
    """Unit-level coverage of the periodic recheck loop's org-active check
    — proves an already-open connection would also be caught within one
    recheck interval, not just new handshakes."""
    from tests.conftest import create_org_admin_in

    org, org_admin_token = create_org_admin_in(client, admin_token, "WS Periodic Recheck Org")
    me = client.get("/api/v1/auth/me", headers=auth_headers(org_admin_token)).json()
    user_id = me["id"]

    assert _user_session_still_valid(user_id, token_version=0, organization_id=org["id"]) is True

    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    assert _user_session_still_valid(user_id, token_version=0, organization_id=org["id"]) is False

    client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token))
    assert _user_session_still_valid(user_id, token_version=0, organization_id=org["id"]) is True
