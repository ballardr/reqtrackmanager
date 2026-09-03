"""Tests for the org-level pending-invite endpoints (Phase A, follow-up UX
batch — docs/decisions.md's "Org-level invites" entry):

  - `GET /orgs/{id}/pending-invites` — org-only (`project_id IS NULL`)
    unaccepted `PendingInvite`s.
  - `POST /orgs/{id}/pending-invites` — creates one ("Invite user").
  - `POST /orgs/{id}/pending-invites/{invite_id}/resend` — token rotation.

Mirrors `test_invites_and_external_users.py`'s coverage of the equivalent
project-level endpoints (`routers/projects.py`'s `list_pending_project_
invites`/`resend_pending_project_invite`), which this batch's Phase A used
as its template.

Also covers `GET /orgs/{id}/users`'s `org_role` filter (already implemented
server-side but previously unwired from the frontend and untested)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from app.database import SessionLocal
from app.models.organization import PendingInvite
from app.services import invites as invites_module
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _set_policy(client, token, org_id, policy, domain=None):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"external_user_policy": policy, "auto_accept_email_domain": domain},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_create_org_pending_invite_and_list_shows_it(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgInviteOrg")
    with patch.object(invites_module, "send_email", new=Mock()) as mock_send:
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "invitee@orginvite.example.com"},
            headers=auth_headers(org_admin_token),
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "invitee@orginvite.example.com"
    assert body["status"] == "pending"
    assert body["invited_by_display_name"]
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "invitee@orginvite.example.com"

    resp = client.get(f"/api/v1/orgs/{org['id']}/pending-invites", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    emails = [i["email"] for i in resp.json()]
    assert "invitee@orginvite.example.com" in emails


def test_create_org_pending_invite_rejected_for_sso_only_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "SsoOnlyInviteOrg")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/sso-config",
        json={"slug": "sso-only-invite-org", "sso_enabled": True, "sso_only": True},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites",
        json={"email": "wontwork@ssoonly.example.com"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


def test_create_org_pending_invite_rejects_existing_email(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "DupeEmailInviteOrg")
    create_org_user(client, org_admin_token, org["id"], "already@dupeemail.example.com")

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites",
        json={"email": "already@dupeemail.example.com"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409


def test_org_pending_invites_list_never_includes_project_scoped_invites(client, admin_token):
    """The org-level list endpoint must only ever surface `project_id IS
    NULL` rows — a project-scoped invite (created via a project's by-email
    add-user flow) stays owned by `GET /projects/{id}/pending-invites`."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "MixedInviteOrg")
    _set_policy(client, org_admin_token, org["id"], "anyone")
    project = create_project(client, org_admin_token, org["id"])

    with patch.object(invites_module, "send_email", new=Mock()):
        client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "orgonly@mixedinvite.example.com"},
            headers=auth_headers(org_admin_token),
        )
        client.post(
            f"/api/v1/projects/{project['id']}/roles/by-email",
            json={"email": "projectscoped@mixedinvite.example.com", "role": "member"},
            headers=auth_headers(org_admin_token),
        )

    resp = client.get(f"/api/v1/orgs/{org['id']}/pending-invites", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    emails = [i["email"] for i in resp.json()]
    assert "orgonly@mixedinvite.example.com" in emails
    assert "projectscoped@mixedinvite.example.com" not in emails

    # And the reverse: the project-level endpoint never lists the org-only invite.
    resp = client.get(f"/api/v1/projects/{project['id']}/pending-invites", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    project_emails = [i["email"] for i in resp.json()]
    assert "projectscoped@mixedinvite.example.com" in project_emails
    assert "orgonly@mixedinvite.example.com" not in project_emails


def test_resend_org_pending_invite_rotates_token_and_resends_email(client, admin_token):
    """Pins the same two core guarantees as the project-level equivalent
    (`test_resend_pending_invite_rotates_token_and_resends_email`): the old
    token stops working and the new one redeems normally."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgResendOrg")
    with patch.object(invites_module, "send_email", new=Mock()):
        client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "resend@orgresend.example.com"},
            headers=auth_headers(org_admin_token),
        )

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(email="resend@orgresend.example.com").one()
        invite_id = str(invite.id)
        old_token = invite.token
    finally:
        db.close()

    with patch.object(invites_module, "send_email", new=Mock()) as mock_send:
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites/{invite_id}/resend",
            headers=auth_headers(org_admin_token),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "resend@orgresend.example.com"

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(id=invite_id).one()
        new_token = invite.token
        assert new_token != old_token
    finally:
        db.close()

    client.put("/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token))

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "resend@orgresend.example.com", "password": "Password123!", "display_name": "Org Resend Test",
            "invite_token": old_token,
        },
    )
    assert resp.status_code == 400

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "resend@orgresend.example.com", "password": "Password123!", "display_name": "Org Resend Test",
            "invite_token": new_token,
        },
    )
    assert resp.status_code == 201, resp.text


def test_resend_org_pending_invite_works_on_an_already_expired_invite(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgResendExpiredOrg")
    with patch.object(invites_module, "send_email", new=Mock()):
        client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "expired@orgresend.example.com"},
            headers=auth_headers(org_admin_token),
        )

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(email="expired@orgresend.example.com").one()
        invite_id = str(invite.id)
        invite.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    with patch.object(invites_module, "send_email", new=Mock()) as mock_send:
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites/{invite_id}/resend",
            headers=auth_headers(org_admin_token),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    mock_send.assert_called_once()

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(id=invite_id).one()
        assert invite.expires_at > datetime.now(UTC)
    finally:
        db.close()


def test_resend_org_pending_invite_rejects_an_already_accepted_invite(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgResendAcceptedOrg")
    with patch.object(invites_module, "send_email", new=Mock()):
        client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "accepted@orgresend.example.com"},
            headers=auth_headers(org_admin_token),
        )

    db = SessionLocal()
    try:
        invite = db.query(PendingInvite).filter_by(email="accepted@orgresend.example.com").one()
        invite_id = str(invite.id)
        token = invite.token
    finally:
        db.close()

    client.put("/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token))
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "accepted@orgresend.example.com", "password": "Password123!",
            "display_name": "Accepted Org Resend", "invite_token": token,
        },
    )

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites/{invite_id}/resend",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409


def test_org_pending_invite_endpoints_are_gated_at_org_admin_tier(client, admin_token):
    """`require_org_role(ORG_ADMIN)` — a plain org member (below that tier)
    is rejected on all three endpoints."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgInviteGateOrg")
    with patch.object(invites_module, "send_email", new=Mock()):
        client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "gatecheck@orginvitegate.example.com"},
            headers=auth_headers(org_admin_token),
        )
    db = SessionLocal()
    try:
        invite_id = str(db.query(PendingInvite).filter_by(email="gatecheck@orginvitegate.example.com").one().id)
    finally:
        db.close()

    create_org_user(client, org_admin_token, org["id"], "belowgate@orginvitegate.example.com", role="member")
    member_token = login(client, "belowgate@orginvitegate.example.com", "Password123!")

    resp = client.get(f"/api/v1/orgs/{org['id']}/pending-invites", headers=auth_headers(member_token))
    assert resp.status_code == 403

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites",
        json={"email": "another@orginvitegate.example.com"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites/{invite_id}/resend",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_org_pending_invite_endpoints_reject_a_server_admin_with_no_role_in_the_org(client, admin_token):
    """Hardening-pass regression test (docs/decisions.md's I-M-05 entry
    addendum): these three endpoints previously reused
    `require_org_admin_or_server_admin` — the single, narrow carve-out
    documented for `create_org_user` only (bootstrapping the first user of
    a brand-new org). A server admin with no genuine role in an
    *already-existing* org must not be able to read that org's invitee PII
    or seed/rotate invites into it — I-M-05's "does not give access to
    data within organisations" invariant applies here same as everywhere
    else. `admin_token` is the bootstrap server admin, who holds no
    `UserOrgRole` in the org `create_org_admin_in` creates below (that
    helper hands org-admin standing to a brand-new, separate user)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "OrgInviteServerAdminGateOrg")
    with patch.object(invites_module, "send_email", new=Mock()):
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/pending-invites",
            json={"email": "gatecheck2@orginviteserveradmingate.example.com"},
            headers=auth_headers(org_admin_token),
        )
    assert resp.status_code == 201, resp.text
    invite_id = resp.json()["id"]

    resp = client.get(f"/api/v1/orgs/{org['id']}/pending-invites", headers=auth_headers(admin_token))
    assert resp.status_code == 403

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites",
        json={"email": "another2@orginviteserveradmingate.example.com"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/pending-invites/{invite_id}/resend",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 403


def test_list_org_users_filters_by_org_role(client, admin_token):
    """`GET /orgs/{id}/users?org_role=...` already existed server-side but
    had no frontend control wired up to it and no test pinning it — Phase A
    both wires it up (Org Users' new role `FilterField`) and pins the
    server-side behaviour here."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "RoleFilterOrg")
    create_org_user(client, org_admin_token, org["id"], "creator@rolefilter.example.com", role="project_creator")
    create_org_user(client, org_admin_token, org["id"], "member@rolefilter.example.com", role="member")

    resp = client.get(
        f"/api/v1/orgs/{org['id']}/users?org_role=project_creator", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert "creator@rolefilter.example.com" in emails
    assert "member@rolefilter.example.com" not in emails

    resp = client.get(f"/api/v1/orgs/{org['id']}/users?org_role=member", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert "member@rolefilter.example.com" in emails
    assert "creator@rolefilter.example.com" not in emails
