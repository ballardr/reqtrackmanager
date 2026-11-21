"""Service users: an organisation administrator creates an account with no password and no sign-in, issues and revokes its
personal access tokens, and everything else treats it as an ordinary user. Pins the closed sign-in paths, the one-
organisation rule, the policy and two-factor exemptions, the token rules, email suppression, the bundle and the audit."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.credential_reset import CredentialResetToken
from app.models.notification import Notification, NotificationType
from app.models.organization import Organization, UserOrgRole
from app.models.pat import PersonalAccessToken
from app.models.service_user import ServiceUserProfile
from app.models.user import User
from app.services import service_users
from app.services.oidc_provisioning import find_or_provision_user
from tests.conftest import auth_headers, create_org_admin_in, create_org_group, create_org_user, create_project, login

DOC = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Accept this."}]}]}


@pytest.fixture
def world(client, admin_token):
    """An organisation with an administrator and a member, and a second organisation with its own administrator."""
    org, admin = create_org_admin_in(client, admin_token, "Svc Org")
    other, other_admin = create_org_admin_in(client, admin_token, "Svc Other Org")
    member_id = create_org_user(client, admin_token, org["id"], "svc_member@example.com")
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin)).json()["id"]
    return {
        "org": org["id"], "admin": admin, "admin_id": admin_id, "other": other["id"], "other_admin": other_admin, "member_id": member_id,
        "member": login(client, "svc_member@example.com", "Password123!"),
    }


def _base(org: str) -> str:
    return f"/api/v1/orgs/{org}/service-users"


def _create(client, world, name="Build agent", **fields) -> dict:
    resp = client.post(_base(world["org"]), json={"name": name, **fields}, headers=auth_headers(world["admin"]))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _issue(client, world, user_id: str, name="ci", **fields) -> dict:
    resp = client.post(f"{_base(world['org'])}/{user_id}/pats", json={"name": name, **fields}, headers=auth_headers(world["admin"]))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _db_user(user_id: str) -> User:
    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(user_id))
        assert user is not None
        db.expunge(user)
        return user
    finally:
        db.close()


# --- creation and shape ------------------------------------------------------------------------------


def test_creation_makes_an_ordinary_account_with_no_password_and_no_token(client, world):
    created = _create(client, world, description="Nightly build", email=None)
    user = _db_user(created["user_id"])

    assert user.is_service_account is True
    assert user.password_hash is None and user.auth_backend == service_users.SERVICE_AUTH_BACKEND
    assert user.email == service_users.generated_address(user.id) and user.email.endswith(".invalid")
    assert created["email"] is None and created["has_deliverable_email"] is False
    assert created["roles"] == ["member"] and created["active_token_count"] == 0
    assert created["flags"] == ["no_responsible"]
    listed = client.get(_base(world["org"]), headers=auth_headers(world["admin"])).json()
    assert [s["user_id"] for s in listed] == [created["user_id"]]
    db = SessionLocal()
    try:
        assert db.scalar(select(PersonalAccessToken.id).where(PersonalAccessToken.user_id == user.id)) is None
    finally:
        db.close()


def test_creation_validates_name_address_and_responsible_principal(client, world, admin_token):
    _create(client, world, name="Unique agent")
    headers = auth_headers(world["admin"])
    assert client.post(_base(world["org"]), json={"name": "  "}, headers=headers).status_code in (400, 422)
    duplicate = client.post(_base(world["org"]), json={"name": "unique AGENT"}, headers=headers)
    assert duplicate.status_code == 409
    taken = client.post(_base(world["org"]), json={"name": "Other", "email": "svc_member@example.com"}, headers=headers)
    assert taken.status_code == 409
    undeliverable = client.post(_base(world["org"]), json={"name": "Other", "email": "x@service.invalid"}, headers=headers)
    assert undeliverable.status_code in (400, 422)

    outsider = create_org_user(client, admin_token, world["other"], "svc_outsider@example.com")
    foreign = client.post(
        _base(world["org"]), json={"name": "Other", "responsible": {"type": "user", "id": outsider}}, headers=headers
    )
    assert foreign.status_code == 400
    ok = client.post(
        _base(world["org"]), json={"name": "Owned", "responsible": {"type": "user", "id": world["member_id"]}}, headers=headers
    )
    assert ok.status_code == 201 and ok.json()["flags"] == [] and ok.json()["responsible"]["label"] == "svc_member"


def test_update_changes_only_the_fields_sent_and_audits_field_names(client, world):
    created = _create(client, world, description="old")
    uid = created["user_id"]
    headers = auth_headers(world["admin"])
    assert client.patch(f"{_base(world['org'])}/{uid}", json={"description": "new"}, headers=headers).json()["description"] == "new"
    with_mail = client.patch(f"{_base(world['org'])}/{uid}", json={"email": "svc_notify@example.com"}, headers=headers).json()
    assert with_mail["email"] == "svc_notify@example.com" and with_mail["has_deliverable_email"] is True
    assert with_mail["name"] == created["name"]
    back = client.patch(f"{_base(world['org'])}/{uid}", json={"email": None}, headers=headers).json()
    assert back["email"] is None and _db_user(uid).email.endswith("@service.invalid")

    db = SessionLocal()
    try:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == uid, AuditEvent.entity_type == "service_user")).all()
        assert {e.action for e in events} == {"created", "updated"}
        assert all("svc_notify" not in json.dumps(e.detail or {}) for e in events)
    finally:
        db.close()


def test_only_an_administrator_of_the_same_organisation_may_manage(client, world):
    created = _create(client, world)
    uid = created["user_id"]
    for method, url in (("get", _base(world["org"])), ("get", f"{_base(world['org'])}/{uid}")):
        assert getattr(client, method)(url, headers=auth_headers(world["member"])).status_code == 403
    assert client.post(_base(world["org"]), json={"name": "x"}, headers=auth_headers(world["member"])).status_code == 403
    assert client.post(f"{_base(world['org'])}/{uid}/pats", json={"name": "x"}, headers=auth_headers(world["member"])).status_code == 403
    # Another organisation's administrator reaches nothing of this one: the route's own organisation is refused,
    # and addressing the account through their own organisation reads as absent.
    other = auth_headers(world["other_admin"])
    assert client.get(f"{_base(world['org'])}/{uid}", headers=other).status_code == 403
    assert client.get(f"{_base(world['other'])}/{uid}", headers=other).status_code == 404
    assert client.post(f"{_base(world['other'])}/{uid}/pats", json={"name": "x"}, headers=other).status_code == 404
    # An ordinary account is not a service user.
    assert client.get(f"{_base(world['org'])}/{world['member_id']}", headers=auth_headers(world["admin"])).status_code == 404


# --- tokens ------------------------------------------------------------------------------------------


def test_the_issued_token_authenticates_as_the_service_user_and_the_secret_is_shown_once(client, world):
    created = _create(client, world)
    issued = _issue(client, world, created["user_id"])
    secret = issued["token"]
    assert secret.startswith("rtm_pat_") and "shown once" in issued["notice"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(secret))
    assert me.status_code == 200 and me.json()["id"] == created["user_id"]

    listed = client.get(f"{_base(world['org'])}/{created['user_id']}/pats", headers=auth_headers(world["admin"]))
    assert listed.status_code == 200
    text = listed.text
    assert secret not in text and "token_hash" not in text and "token\"" not in text
    assert listed.json()[0]["created_by_display_name"] == _db_user(world["admin_id"]).display_name
    db = SessionLocal()
    try:
        pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.user_id == uuid.UUID(created["user_id"])))
        assert pat is not None and pat.token_hash != secret and secret not in json.dumps(pat.allowed_organization_ids)
        assert pat.created_by_user_id is not None and pat.created_by_user_id != pat.user_id
        assert [str(i) for i in pat.allowed_organization_ids] == [world["org"]]
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(pat.id))).all()
        assert [e.action for e in events] == ["service_user_pat_issued"]
        assert events[0].actor_id == pat.created_by_user_id and secret not in json.dumps(events[0].detail or {})
    finally:
        db.close()


def test_the_token_reaches_only_its_organisation_and_project_restriction(client, world, admin_token):
    created = _create(client, world)
    uid = created["user_id"]
    in_scope = create_project(client, world["admin"], world["org"], name="Svc In Scope")
    other_project = create_project(client, world["admin"], world["org"], name="Svc Other Project")
    outside = create_project(client, world["other_admin"], world["other"], name="Svc Outside")
    # Roles: an administrator grants the service user a role on two projects through the ordinary role endpoint.
    for project in (in_scope, other_project):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": uid, "role": "member"},
            headers=auth_headers(world["admin"]),
        )
        assert resp.status_code == 204, resp.text
    token = _issue(client, world, uid, allowed_project_ids=[in_scope["id"]])["token"]

    listed = {p["id"] for p in client.get("/api/v1/projects", headers=auth_headers(token)).json()}
    assert listed == {in_scope["id"]}
    assert client.get(f"/api/v1/orgs/{world['other']}", headers=auth_headers(token)).status_code == 403
    assert outside["id"] not in listed

    # A project the service user cannot reach, or one in another organisation, cannot be named.
    no_access = client.post(
        f"{_base(world['org'])}/{uid}/pats", json={"name": "x", "allowed_project_ids": [outside["id"]]},
        headers=auth_headers(world["admin"]),
    )
    assert no_access.status_code == 400
    unreachable = create_project(client, world["admin"], world["org"], name="Svc Unreachable")
    assert client.post(
        f"{_base(world['org'])}/{uid}/pats", json={"name": "x", "allowed_project_ids": [unreachable["id"]]},
        headers=auth_headers(world["admin"]),
    ).status_code == 400


def test_the_lifetime_cap_applies_and_tightening_it_shortens_an_issued_token(client, world):
    db = SessionLocal()
    try:
        db.get(Organization, uuid.UUID(world["org"])).pat_max_lifetime_days = 10
        db.commit()
    finally:
        db.close()
    created = _create(client, world)
    far = (datetime.now(UTC) + timedelta(days=400)).isoformat()
    issued = _issue(client, world, created["user_id"], requested_expires_at=far)
    expires = datetime.fromisoformat(issued["expires_at"].replace("Z", "+00:00"))
    assert expires <= datetime.now(UTC) + timedelta(days=10, minutes=1)

    db = SessionLocal()
    try:
        pat = db.get(PersonalAccessToken, uuid.UUID(issued["id"]))
        pat.created_at = datetime.now(UTC) - timedelta(days=11)
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/auth/me", headers=auth_headers(issued["token"])).status_code == 401


def test_revoking_kills_the_token_at_once_and_deactivation_kills_every_token(client, world):
    created = _create(client, world)
    uid = created["user_id"]
    first = _issue(client, world, uid, name="first")
    second = _issue(client, world, uid, name="second")
    assert client.get("/api/v1/auth/me", headers=auth_headers(first["token"])).status_code == 200
    revoked = client.delete(f"{_base(world['org'])}/{uid}/pats/{first['id']}", headers=auth_headers(world["admin"]))
    assert revoked.status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth_headers(first["token"])).status_code == 401
    assert client.get("/api/v1/auth/me", headers=auth_headers(second["token"])).status_code == 200
    # A token that is not this service user's reads as absent.
    assert client.delete(f"{_base(world['org'])}/{uid}/pats/{uuid.uuid4()}", headers=auth_headers(world["admin"])).status_code == 404

    deactivated = client.post(f"/api/v1/orgs/{world['org']}/users/{uid}/deactivate", headers=auth_headers(world["admin"]))
    assert deactivated.status_code == 204, deactivated.text
    assert client.get("/api/v1/auth/me", headers=auth_headers(second["token"])).status_code == 401
    assert client.post(f"{_base(world['org'])}/{uid}/pats", json={"name": "x"}, headers=auth_headers(world["admin"])).status_code == 409

    reactivated = client.post(f"{_base(world['org'])}/{uid}/reactivate", headers=auth_headers(world["admin"]))
    assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
    # Tokens revoked or deactivated earlier stay dead only if revoked; an unrevoked one works again once reactivated.
    assert client.get("/api/v1/auth/me", headers=auth_headers(first["token"])).status_code == 401
    assert client.get("/api/v1/auth/me", headers=auth_headers(second["token"])).status_code == 200


def test_a_token_cannot_create_change_or_issue_service_users_or_tokens(client, world):
    created = _create(client, world)
    admin_pat = client.post(
        "/api/v1/me/pats", json={"name": "admin", "allowed_organization_ids": [world["org"]]}, headers=auth_headers(world["admin"]),
    ).json()["token"]
    headers = auth_headers(admin_pat)
    assert client.post(_base(world["org"]), json={"name": "via token"}, headers=headers).status_code == 403
    assert client.patch(f"{_base(world['org'])}/{created['user_id']}", json={"description": "x"}, headers=headers).status_code == 403
    assert client.post(f"{_base(world['org'])}/{created['user_id']}/pats", json={"name": "x"}, headers=headers).status_code == 403
    # Reading is allowed.
    assert client.get(_base(world["org"]), headers=headers).status_code == 200


def test_the_service_users_own_token_cannot_mint_another_token(client, world):
    created = _create(client, world)
    token = _issue(client, world, created["user_id"])["token"]
    resp = client.post("/api/v1/me/pats", json={"name": "x", "allowed_organization_ids": [world["org"]]}, headers=auth_headers(token))
    assert resp.status_code == 403


# --- closed sign-in paths ----------------------------------------------------------------------------


def test_no_password_login_and_the_refusal_matches_an_unknown_account(client, world):
    created = _create(client, world, email="svc_signin@example.com")
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody_here@example.com", "password": "Password123!"})
    for email in ("svc_signin@example.com", _db_user(created["user_id"]).email):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
        assert resp.status_code == unknown.status_code == 401
        assert resp.json() == unknown.json()
    assert client.post("/api/v1/auth/login", json={"email": "svc_signin@example.com", "password": ""}).status_code in (401, 422)


def test_no_reset_link_no_confirmation_and_no_invitation(client, world, monkeypatch):
    created = _create(client, world, email="svc_reset@example.com")
    sent: list[str] = []
    monkeypatch.setattr("app.services.credential_reset.send_email", lambda to, *a, **k: sent.append(to))
    assert client.post("/api/v1/auth/forgot-password", json={"email": "svc_reset@example.com"}).status_code == 202
    assert client.post("/api/v1/auth/resend-confirmation", json={"email": "svc_reset@example.com"}).status_code == 202
    admin_reset = client.post(
        f"/api/v1/orgs/{world['org']}/users/{created['user_id']}/password-reset", headers=auth_headers(world["admin"])
    )
    assert admin_reset.status_code >= 400
    invite = client.post(
        f"/api/v1/orgs/{world['org']}/pending-invites", json={"email": "svc_reset@example.com"}, headers=auth_headers(world["admin"])
    )
    assert invite.status_code == 409
    db = SessionLocal()
    try:
        assert db.scalar(select(CredentialResetToken.id).where(CredentialResetToken.user_id == uuid.UUID(created["user_id"]))) is None
        assert service_users.SERVICE_AUTH_BACKEND == "service" and not sent
    finally:
        db.close()


def test_an_sso_sign_in_with_a_service_users_address_does_not_adopt_it(client, world):
    created = _create(client, world, email="svc_sso@example.com")
    db = SessionLocal()
    try:
        org = db.get(Organization, uuid.UUID(world["org"]))
        org.oidc_issuer_url = "https://idp.example.com/realms/t"
        org.sso_enabled = True
        claims = {"sub": "attacker-subject", "email": "svc_sso@example.com", "email_verified": True, "name": "Someone"}
        with pytest.raises(ValueError):
            find_or_provision_user(db, claims, issuer="https://idp.example.com/realms/t", org=org)
        db.rollback()
        user = db.get(User, uuid.UUID(created["user_id"]))
        assert user.auth_backend == service_users.SERVICE_AUTH_BACKEND and user.external_subject is None
    finally:
        db.close()


def test_a_signup_with_a_service_users_address_is_refused(client, world):
    _create(client, world, email="svc_signup@example.com")
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "svc_signup@example.com", "display_name": "Imposter", "password": "Password123!x"},
    )
    assert resp.status_code in (403, 409)


def test_the_account_cannot_become_a_server_administrator(client, world, admin_token):
    created = _create(client, world)
    resp = client.put(
        f"/api/v1/system/users/{created['user_id']}/server-admin", json={"is_server_admin": True}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400
    assert _db_user(created["user_id"]).is_server_admin is False


def test_scim_does_not_list_read_adopt_or_change_a_service_user(client, world):
    created = _create(client, world, email="svc_scim@example.com")
    token = client.post(f"/api/v1/orgs/{world['org']}/scim-token", headers=auth_headers(world["admin"])).json()["token"]
    scim = auth_headers(token)
    assert client.get("/scim/v2/Users", headers=scim).json()["totalResults"] == 2  # the administrator and the member
    assert client.get(f"/scim/v2/Users/{created['user_id']}", headers=scim).status_code == 404
    assert client.patch(
        f"/scim/v2/Users/{created['user_id']}", json={"Operations": [{"op": "replace", "path": "active", "value": False}]}, headers=scim
    ).status_code == 404
    assert client.post("/scim/v2/Users", json={"userName": "svc_scim@example.com"}, headers=scim).status_code == 409
    assert _db_user(created["user_id"]).is_active is True


# --- one organisation --------------------------------------------------------------------------------


def test_a_service_user_cannot_be_added_to_another_organisation(client, world, admin_token):
    created = _create(client, world)
    uid = created["user_id"]
    db = SessionLocal()
    try:
        other = db.get(Organization, uuid.UUID(world["other"]))
        from app.models.enums import ExternalUserPolicy

        other.external_user_policy = ExternalUserPolicy.ANYONE
        db.commit()
    finally:
        db.close()
    headers = auth_headers(world["other_admin"])
    granted = client.post(f"/api/v1/orgs/{world['other']}/users/{uid}/roles", json={"user_id": uid, "role": "member"}, headers=headers)
    assert granted.status_code == 403
    project = create_project(client, world["other_admin"], world["other"], name="Svc Foreign Project")
    by_email = _create(client, world, name="Mailbox agent", email="svc_mailbox@example.com")
    added = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email", json={"email": "svc_mailbox@example.com", "role": "member"},
        headers=headers,
    )
    assert added.status_code == 403
    searched = client.get(
        f"/api/v1/orgs/{world['other']}/users/search", params={"q": "svc_mailbox@example.com"}, headers=headers
    ).json()
    assert searched["external"] is None
    db = SessionLocal()
    try:
        orgs = set(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == uuid.UUID(uid))))
        assert orgs == {uuid.UUID(world["org"])}
        assert by_email["user_id"]
    finally:
        db.close()


def test_a_service_user_holds_ordinary_roles_and_the_access_review_flags_administrator_rights(client, world):
    created = _create(client, world)
    uid = created["user_id"]
    granted = client.post(
        f"/api/v1/orgs/{world['org']}/users/{uid}/roles", json={"user_id": uid, "role": "org_admin"}, headers=auth_headers(world["admin"])
    )
    assert granted.status_code == 204, granted.text
    got = client.get(f"{_base(world['org'])}/{uid}", headers=auth_headers(world["admin"])).json()
    assert set(got["flags"]) == {"administrator", "no_responsible"}
    users = client.get(
        f"/api/v1/orgs/{world['org']}/users", params={"is_service_account": "true"}, headers=auth_headers(world["admin"])
    ).json()
    assert [u["user_id"] for u in users] == [uid] and users[0]["is_service_account"] is True
    everyone = client.get(f"/api/v1/orgs/{world['org']}/users", headers=auth_headers(world["admin"])).json()
    assert {u["user_id"] for u in everyone} >= {uid, world["member_id"]}


# --- policy and two-factor exemptions ----------------------------------------------------------------


def _require_policy(client, world) -> str:
    org_policies = f"/api/v1/orgs/{world['org']}/policies"
    made = client.post(
        org_policies, json={"title": "Svc Policy", "body": DOC, "requires_acknowledgement": True}, headers=auth_headers(world["admin"])
    )
    assert made.status_code == 201, made.text
    published = client.post(f"{org_policies}/{made.json()['id']}/publish", json={}, headers=auth_headers(world["admin"]))
    assert published.status_code == 200, published.text
    return made.json()["id"]


def test_the_policy_gate_blocks_a_person_but_never_a_service_user_and_status_lists_it_apart(client, world):
    created = _create(client, world)
    # The role is granted first: once a policy is required the administrator's own writes are blocked until accepted.
    granted = client.post(
        f"/api/v1/orgs/{world['org']}/users/{created['user_id']}/roles",
        json={"user_id": created["user_id"], "role": "org_admin"}, headers=auth_headers(world["admin"]),
    )
    assert granted.status_code == 204, granted.text
    token = _issue(client, world, created["user_id"])["token"]
    policy_id = _require_policy(client, world)

    write = {"name": "Svc Gate Group"}
    blocked = client.post(f"/api/v1/orgs/{world['org']}/groups", json=write, headers=auth_headers(world["member"]))
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "policy_acknowledgement_required"
    allowed = client.post(f"/api/v1/orgs/{world['org']}/groups", json=write, headers=auth_headers(token))
    assert allowed.status_code in (200, 201), allowed.text

    status_view = client.get(f"/api/v1/orgs/{world['org']}/policies/{policy_id}/acknowledgements", headers=auth_headers(world["admin"])).json()
    assert [p["email"] for p in status_view["people"]] and created["user_id"] not in {p["user_id"] for p in status_view["people"]}
    assert [p["user_id"] for p in status_view["not_applicable"]] == [created["user_id"]]
    assert status_view["required"] == len(status_view["people"])


def test_an_organisation_that_requires_two_factor_does_not_block_a_service_user(client, world):
    created = _create(client, world)
    uid = created["user_id"]
    client.post(f"/api/v1/orgs/{world['org']}/users/{uid}/roles", json={"user_id": uid, "role": "org_admin"}, headers=auth_headers(world["admin"]))
    token = _issue(client, world, uid)["token"]
    db = SessionLocal()
    try:
        db.get(Organization, uuid.UUID(world["org"])).require_2fa = True
        db.commit()
    finally:
        db.close()
    assert client.get(_base(world["org"]), headers=auth_headers(token)).status_code == 200
    # The same requirement still blocks a person without a second factor.
    assert client.get(f"/api/v1/orgs/{world['org']}/users", headers=auth_headers(world["member"])).status_code == 403


# --- email ---------------------------------------------------------------------------------------


def test_notifications_email_a_supplied_address_and_never_a_generated_one(client, world, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.notifications.send_email", lambda to, *a, **k: sent.append(to))
    with_mail = _create(client, world, name="Mailed agent", email="svc_mail_ok@example.com")
    without = _create(client, world, name="Silent agent")
    from app.services.notifications import notify

    db = SessionLocal()
    try:
        for uid in (with_mail["user_id"], without["user_id"]):
            notify(db, db.get(User, uuid.UUID(uid)), notification_type=NotificationType.PROJECT_JOINED, title="Hello", body="x")
        db.commit()
        rows = db.scalars(select(Notification).where(Notification.title == "Hello")).all()
        assert len(rows) == 2 and sum(1 for r in rows if r.emailed_at is not None) == 1
    finally:
        db.close()
    assert sent == ["svc_mail_ok@example.com"]
    assert service_users.can_receive_email(_db_user(without["user_id"])) is False


# --- responsible principal and groups ---------------------------------------------------------------


def test_a_group_can_be_responsible_and_deleting_it_clears_the_field(client, world):
    group_id = create_org_group(client, world["admin"], world["org"], "Platform Team", users=[world["member_id"]])
    created = _create(client, world, responsible={"type": "org_group", "id": group_id})
    assert created["responsible"]["type"] == "org_group" and created["flags"] == []
    in_use = client.delete(f"/api/v1/orgs/{world['org']}/groups/{group_id}", headers=auth_headers(world["admin"]))
    assert in_use.status_code == 409 and "service user responsible" in in_use.text
    resp = client.delete(
        f"/api/v1/orgs/{world['org']}/groups/{group_id}", params={"clear_optional": "true"}, headers=auth_headers(world["admin"])
    )
    assert resp.status_code == 204, resp.text
    got = client.get(f"{_base(world['org'])}/{created['user_id']}", headers=auth_headers(world["admin"])).json()
    assert got["responsible"] is None and got["flags"] == ["no_responsible"]


def test_a_service_user_cannot_be_its_own_responsible_party(client, world):
    created = _create(client, world)
    resp = client.patch(
        f"{_base(world['org'])}/{created['user_id']}", json={"responsible": {"type": "user", "id": created["user_id"]}},
        headers=auth_headers(world["admin"]),
    )
    assert resp.status_code == 400


# --- bundle ---------------------------------------------------------------------------------------


def test_the_organisation_bundle_carries_configuration_and_never_a_token_hash_or_address(client, world, admin_token):
    group_id = create_org_group(client, world["admin"], world["org"], "Bundle Team", users=[world["member_id"]])
    created = _create(
        client, world, name="Bundle agent", description="Exports", email="svc_bundle@example.com",
        responsible={"type": "org_group", "id": group_id},
    )
    issued = _issue(client, world, created["user_id"])
    exported = client.get(f"/api/v1/orgs/{world['org']}/export", headers=auth_headers(world["admin"]))
    assert exported.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(exported.content))
    org_json = zf.read("org.json").decode()
    data = json.loads(org_json)
    raw = b"".join(zf.read(n) for n in zf.namelist())
    assert issued["token"].encode() not in raw and b"svc_bundle@example.com" not in raw
    assert b".invalid" not in raw
    assert [m["email"] for m in data["members"]] and all("service" not in m["email"] for m in data["members"])
    assert data["service_users"] == [{
        "name": "Bundle agent", "description": "Exports", "org_roles": ["member"], "group_names": [], "is_active": True,
        "responsible": {"type": "org_group", "name": "Bundle Team"},
    }]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Svc Imported Org"}, files={"file": ("bundle.zip", exported.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    db = SessionLocal()
    try:
        rows = db.execute(
            select(User, ServiceUserProfile).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id)
            .where(ServiceUserProfile.organization_id == new_org)
        ).all()
        assert [(u.display_name, p.description) for u, p in rows] == [("Bundle agent", "Exports")]
        user = rows[0][0]
        assert user.password_hash is None and user.email.endswith("@service.invalid") and user.email != "svc_bundle@example.com"
        assert user.id != uuid.UUID(created["user_id"])
        assert db.scalar(select(PersonalAccessToken.id).where(PersonalAccessToken.user_id == user.id)) is None
    finally:
        db.close()


def test_an_ordinary_users_bundle_entry_is_unchanged_by_a_service_user_in_the_same_organisation(client, world):
    _create(client, world, name="Quiet agent")
    exported = client.get(f"/api/v1/orgs/{world['org']}/export", headers=auth_headers(world["admin"]))
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    emails = {m["email"] for m in data["members"]}
    assert "svc_member@example.com" in emails and len(emails) == 2
    assert all(not e.endswith(".invalid") for e in emails)


def test_deleting_the_organisation_deactivates_and_archives_its_service_users(client, world, admin_token):
    created = _create(client, world)
    token = _issue(client, world, created["user_id"])["token"]
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 200
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{world['org']}", json={"confirm_name": "Svc Org"}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text
    user = _db_user(created["user_id"])
    assert user.is_active is False and user.is_archived is True and user.is_service_account is True
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 401
