"""Tests for `POST /system/users` — a server administrator adding a person from Server Management —
and the shared `services.user_provisioning` it shares with Org Admin's "New user" / "Invite user".

Covers both credential modes (invite, admin-set password), with and without an organisation, the shared
password rule, duplicate email, `sso_only`, authorisation, the audit row, that no secret is returned, and
that the org endpoints behave as before the extraction.
"""

from unittest.mock import Mock, patch

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.organization import PendingInvite, UserOrgRole
from app.models.user import User
from app.services import invites as invites_module
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login

URL = "/api/v1/system/users"


def _post(client, token, **body):
    return client.post(URL, json=body, headers=auth_headers(token))


def _audit(entity_type, entity_id):
    db = SessionLocal()
    try:
        return db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == str(entity_id))
        ).all()
    finally:
        db.close()


def test_password_user_without_an_organisation_can_log_in_and_has_no_membership(client, admin_token):
    resp = _post(client, admin_token, mode="password", email="Solo@NoOrg.example.com", display_name="Solo",
                 password="Password123!")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == "password" and body["email"] == "solo@noorg.example.com" and body["invite_id"] is None
    assert login(client, "solo@noorg.example.com", "Password123!")
    db = SessionLocal()
    try:
        assert db.scalars(select(UserOrgRole).where(UserOrgRole.user_id == body["user_id"])).all() == []
    finally:
        db.close()
    # An organisation-less account is in the "orphaned" view of the users list.
    listing = client.get(f"{URL}?no_org_membership=true", headers=auth_headers(admin_token)).json()
    assert "solo@noorg.example.com" in {u["email"] for u in listing}


def test_password_user_in_an_organisation_gets_the_role_and_an_audit_row(client, admin_token, org_id):
    resp = _post(client, admin_token, mode="password", email="creator@inorg.example.com", display_name="Creator",
                 password="Password123!", organization_id=org_id, role="project_creator")
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user_id"]
    assert login(client, "creator@inorg.example.com", "Password123!")
    roles = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    mine = next(u for u in roles if u["user_id"] == user_id)
    assert mine["roles"] == ["project_creator"]
    events = _audit("user", user_id)
    assert [e.action for e in events] == ["created"]
    assert str(events[0].actor_id) == client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    assert str(events[0].organization_id) == org_id


def test_response_and_audit_never_carry_the_password_or_a_hash(client, admin_token):
    secret = "S3cretPassw0rd-xyz"
    resp = _post(client, admin_token, mode="password", email="secret@x.example.com", display_name="Sec", password=secret)
    assert resp.status_code == 201
    assert secret not in resp.text and "password" not in resp.text.lower().replace('"mode":"password"', "")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "secret@x.example.com"))
        assert user.password_hash != secret
        for event in _audit("user", user.id):
            assert secret not in str(event.detail) and user.password_hash not in str(event.detail)
    finally:
        db.close()


def test_invite_for_an_organisation_is_accepted_and_the_user_then_logs_in(client, admin_token, org_id):
    client.put("/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token))
    with patch.object(invites_module, "send_email", new=Mock()) as send:
        resp = _post(client, admin_token, mode="invite", email="Invitee@Sys.example.com", organization_id=org_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == "invite" and body["user_id"] is None and body["invite_id"]
    assert "token" not in resp.text
    send.assert_called_once()
    assert send.call_args.args[0] == "invitee@sys.example.com"
    assert [e.action for e in _audit("pending_invite", body["invite_id"])] == ["invited"]

    db = SessionLocal()
    try:
        token = db.get(PendingInvite, body["invite_id"]).token
    finally:
        db.close()
    signup = client.post("/api/v1/auth/signup", json={
        "email": "invitee@sys.example.com", "password": "Password123!", "display_name": "Invitee", "invite_token": token,
    })
    assert signup.status_code == 201, signup.text
    assert login(client, "invitee@sys.example.com", "Password123!")


def test_invite_without_an_organisation_creates_an_account_with_no_membership(client, admin_token):
    client.put("/api/v1/system/signup-config", json={"signup_mode": "disabled"}, headers=auth_headers(admin_token))
    with patch.object(invites_module, "send_email", new=Mock()) as send:
        resp = _post(client, admin_token, mode="invite", email="NoOrgInvitee@sys.example.com")
    assert resp.status_code == 201, resp.text
    invite_id = resp.json()["invite_id"]
    send.assert_called_once()
    assert send.call_args.args[0] == "noorginvitee@sys.example.com"
    db = SessionLocal()
    try:
        invite = db.get(PendingInvite, invite_id)
        assert invite.organization_id is None and invite.project_id is None
        token = invite.token
    finally:
        db.close()
    # The invite works even though public sign-up is off, and the person joins nothing.
    signup = client.post("/api/v1/auth/signup", json={
        "email": "noorginvitee@sys.example.com", "password": "Password123!", "display_name": "No Org", "invite_token": token,
    })
    assert signup.status_code == 201, signup.text
    assert login(client, "noorginvitee@sys.example.com", "Password123!")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "noorginvitee@sys.example.com"))
        assert db.scalars(select(UserOrgRole).where(UserOrgRole.user_id == user.id)).all() == []
        assert db.get(PendingInvite, invite_id).accepted_at is not None
    finally:
        db.close()
    assert [e.action for e in _audit("pending_invite", invite_id)] == ["invited"]


def test_an_organisation_less_invite_is_not_listed_in_any_organisation(client, admin_token, org_id):
    with patch.object(invites_module, "send_email", new=Mock()):
        assert _post(client, admin_token, mode="invite", email="hidden@sys.example.com").status_code == 201
    org_admin_id = create_org_user(client, admin_token, org_id, "oa2@sys.example.com", role="org_admin")
    assert org_admin_id
    org_admin_token = login(client, "oa2@sys.example.com", "Password123!")
    listing = client.get(f"/api/v1/orgs/{org_id}/pending-invites", headers=auth_headers(org_admin_token)).json()
    assert "hidden@sys.example.com" not in {i["email"] for i in listing}


def test_an_invite_into_an_organisation_with_a_higher_role_is_refused(client, admin_token, org_id):
    resp = _post(client, admin_token, mode="invite", email="b@sys.example.com", organization_id=org_id, role="org_admin")
    assert resp.status_code == 400


def test_weak_password_is_400_and_creates_nothing(client, admin_token):
    resp = _post(client, admin_token, mode="password", email="weak@sys.example.com", display_name="W", password="short")
    assert resp.status_code == 400
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "weak@sys.example.com")) is None
    finally:
        db.close()


def test_missing_password_or_name_is_400(client, admin_token):
    assert _post(client, admin_token, mode="password", email="np@sys.example.com", display_name="N").status_code == 400
    assert _post(client, admin_token, mode="password", email="nn@sys.example.com", password="Password123!").status_code == 400


def test_duplicate_email_is_409_in_both_modes(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "dupe@sys.example.com")
    assert _post(client, admin_token, mode="password", email="DUPE@sys.example.com", display_name="D",
                 password="Password123!").status_code == 409
    assert _post(client, admin_token, mode="invite", email="dupe@sys.example.com", organization_id=org_id).status_code == 409


def test_unknown_organisation_is_404(client, admin_token):
    missing = "00000000-0000-0000-0000-000000000000"
    assert _post(client, admin_token, mode="password", email="m@sys.example.com", display_name="M",
                 password="Password123!", organization_id=missing).status_code == 404
    assert _post(client, admin_token, mode="invite", email="m2@sys.example.com", organization_id=missing).status_code == 404


def test_sso_only_organisation_is_rejected_in_both_modes(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "SysSsoOnlyOrg")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/sso-config",
        json={"slug": "sys-sso-only-org", "sso_enabled": True, "sso_only": True},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _post(client, admin_token, mode="password", email="s1@sys.example.com", display_name="S",
                 password="Password123!", organization_id=org["id"]).status_code == 400
    assert _post(client, admin_token, mode="invite", email="s2@sys.example.com", organization_id=org["id"]).status_code == 400


def test_only_a_server_admin_may_add_users(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "orgadmin@sys.example.com", role="org_admin")
    org_admin_token = login(client, "orgadmin@sys.example.com", "Password123!")
    resp = _post(client, org_admin_token, mode="password", email="x@sys.example.com", display_name="X",
                 password="Password123!", organization_id=org_id)
    assert resp.status_code == 403
    assert client.post(URL, json={}).status_code in (401, 403)


def test_cannot_mint_a_server_admin(client, admin_token):
    resp = _post(client, admin_token, mode="password", email="nope@sys.example.com", display_name="N",
                 password="Password123!", is_server_admin=True, server_roles=["module_administrator"])
    assert resp.status_code == 201
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "nope@sys.example.com")).is_server_admin is False
    finally:
        db.close()


def test_creation_is_rate_limited(client, admin_token, monkeypatch):
    from app.routers.system import users as users_router

    monkeypatch.setattr(users_router, "_create_limiters", {})
    monkeypatch.setattr(users_router.get_settings(), "user_create_rate_limit_burst", 2)
    monkeypatch.setattr(users_router.get_settings(), "user_create_rate_limit_per_minute", 1)
    codes = [
        _post(client, admin_token, mode="password", email=f"rl{i}@sys.example.com", display_name="R",
              password="Password123!").status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]


def test_org_endpoints_still_behave_as_before_after_the_extraction(client, admin_token, org_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users",
        json={"email": "Orgmade@Sys.example.com", "display_name": "Org Made", "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "orgmade@sys.example.com" and resp.json()["roles"] == ["member"]
    assert client.post(
        f"/api/v1/orgs/{org_id}/users",
        json={"email": "orgmade@sys.example.com", "display_name": "Dup", "password": "Password123!"},
        headers=auth_headers(admin_token),
    ).status_code == 409



def test_org_admin_can_no_longer_create_an_account_with_a_one_character_password(client, admin_token, org_id):
    """Found defect: `OrgUserCreate.password` had no minimum length, unlike signup and change-password."""
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users",
        json={"email": "tiny@sys.example.com", "display_name": "T", "password": "x"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
