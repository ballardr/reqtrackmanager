"""Tests for Massif (v3) OIDC provisioning logic (E-U-01) and org SSO
configuration endpoints. The full browser-driven login flow against a real
Keycloak instance is covered by
tests/playwright/tests/e2e-workflows/sso.spec.ts, not here — this file
covers `services/oidc_provisioning.py` directly with synthetic claims (no
network calls), and the config API surface."""

import pytest

from app.database import SessionLocal
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.security import create_oidc_state_token
from app.services.oidc_provisioning import (
    find_or_provision_user,
    meets_required_group,
    sync_org_groups_from_claims,
    sync_org_roles_from_claims,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project
from tests.test_access_review import _make_orphaned_user

ISSUER_A = "https://idp-a.example.com/realms/tenant"
ISSUER_B = "https://idp-b.example.com/realms/other-tenant"


def _patch_fake_oidc(monkeypatch, *, email: str, subject: str = "fake-subject") -> None:
    """Stubs the three network-calling steps of the OIDC callback
    (discovery, code exchange, ID-token verification) so `oidc_callback`
    can be driven end-to-end through the real HTTP router without a live
    IdP — the same three functions `oidc_client.py` exposes and
    `routers/auth_oidc.py::oidc_callback` calls by module attribute."""
    monkeypatch.setattr("app.services.oidc_client.discover", lambda issuer_url: {})
    monkeypatch.setattr(
        "app.services.oidc_client.exchange_code_for_tokens", lambda discovery, **kwargs: {"id_token": "fake"}
    )
    monkeypatch.setattr(
        "app.services.oidc_client.verify_id_token",
        lambda discovery, id_token, **kwargs: {"sub": subject, "email": email, "email_verified": True},
    )


def _sso_org(client, admin_token, org_id, slug: str) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={
            "slug": slug, "sso_enabled": True,
            "oidc_issuer_url": "https://idp.example.com/realms/x", "oidc_client_id": "cid",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def test_find_or_provision_user_creates_a_new_oidc_user():
    db = SessionLocal()
    try:
        user = find_or_provision_user(
            db, {"sub": "idp-subject-1", "email": "newsso@example.com", "email_verified": True, "name": "New SSO"},
            issuer=ISSUER_A,
        )
        db.commit()
        assert user.auth_backend == "oidc"
        assert user.external_subject == "idp-subject-1"
        assert user.oidc_issuer == ISSUER_A
        assert user.password_hash is None
        assert user.email == "newsso@example.com"
    finally:
        db.close()


def test_find_or_provision_user_resolves_by_subject_on_repeat_login():
    db = SessionLocal()
    try:
        first = find_or_provision_user(
            db, {"sub": "idp-subject-2", "email": "repeat@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        db.commit()
        second = find_or_provision_user(
            db, {"sub": "idp-subject-2", "email": "repeat@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        db.commit()
        assert first.id == second.id
    finally:
        db.close()


def test_find_or_provision_user_does_not_collide_across_different_issuers_with_the_same_subject():
    """E-U-01 hardening: `sub` is only unique per-issuer per the OIDC spec.
    Two different, unrelated identity providers asserting the same raw
    subject string must never resolve to the same account."""
    db = SessionLocal()
    try:
        first = find_or_provision_user(
            db, {"sub": "shared-subject-value", "email": "tenant-a-user@example.com", "email_verified": True},
            issuer=ISSUER_A,
        )
        db.commit()
        second = find_or_provision_user(
            db, {"sub": "shared-subject-value", "email": "tenant-b-user@example.com", "email_verified": True},
            issuer=ISSUER_B,
        )
        db.commit()
        assert first.id != second.id
        assert first.oidc_issuer == ISSUER_A
        assert second.oidc_issuer == ISSUER_B
    finally:
        db.close()


def test_find_or_provision_user_does_not_link_to_existing_account_via_unverified_email(client, admin_token, org_id):
    """Anti-spoofing check: an IdP that doesn't assert verified email must
    not be able to take over the bootstrap admin's account just by claiming
    its email address — the login attempt must be refused outright, not
    silently linked and not fall through to provisioning a colliding
    duplicate account (impossible anyway: email is unique)."""
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            find_or_provision_user(
                db, {"sub": "attacker-subject", "email": "admin@example.com", "email_verified": False}, issuer=ISSUER_A,
            )
        db.rollback()

        # Confirm the real admin account was left completely untouched.
        from sqlalchemy import select

        from app.models.user import User

        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert admin.auth_backend == "native"
        assert admin.external_subject is None
    finally:
        db.close()


def test_sync_org_roles_from_claims_grants_mapped_role():
    db = SessionLocal()
    try:
        org = Organization(name="OIDC Role Sync Org", sso_group_mappings=[{"sso_group": "admins", "org_role": "org_admin"}])
        db.add(org)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "role-sync-subject", "email": "rolesync@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_roles_from_claims(db, user, org, {"groups": ["admins"]})
        db.commit()

        from sqlalchemy import select

        from app.models.organization import UserOrgRole

        roles = db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
        assert "org_admin" in [r.value for r in roles]
    finally:
        db.close()


def test_sync_org_roles_grants_nothing_when_no_group_matches():
    db = SessionLocal()
    try:
        org = Organization(name="OIDC No Match Org", sso_group_mappings=[{"sso_group": "admins", "org_role": "org_admin"}])
        db.add(org)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "no-match-subject", "email": "nomatch@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_roles_from_claims(db, user, org, {"groups": ["unrelated-group"]})
        db.commit()

        from sqlalchemy import select

        from app.models.organization import UserOrgRole

        roles = db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
        assert roles == []
    finally:
        db.close()


def test_sync_org_roles_revokes_role_once_matching_group_claim_disappears():
    """Hardening-review regression: sync_org_roles_from_claims used to only
    ever grant roles, never revoke them — a role granted via a matching
    IdP group claim persisted forever even after later logins no longer
    asserted that group."""
    from sqlalchemy import select

    from app.models.organization import UserOrgRole

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Sync Down Org", sso_group_mappings=[{"sso_group": "admins", "org_role": "org_admin"}])
        db.add(org)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "sync-down-subject", "email": "syncdown@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_roles_from_claims(db, user, org, {"groups": ["admins"]})
        db.commit()
        roles = db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
        assert "org_admin" in [r.value for r in roles]

        # A later login where the IdP no longer asserts "admins" (but does
        # assert *some* non-empty groups claim, e.g. the user is still in
        # some other, unmapped group) revokes the role.
        sync_org_roles_from_claims(db, user, org, {"groups": ["some-other-group"]})
        db.commit()
        roles = db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
        assert roles == []
    finally:
        db.close()


def test_sync_org_roles_never_touches_a_role_outside_the_mapping_vocabulary():
    """A role granted manually (with no corresponding sso_group entry at
    all) must survive sync-down regardless of what the IdP asserts —
    sync_org_roles_from_claims may only manage roles its own org's mapping
    vocabulary covers."""
    from sqlalchemy import select

    from app.models.organization import UserOrgRole

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Manual Role Org", sso_group_mappings=[{"sso_group": "admins", "org_role": "org_admin"}])
        db.add(org)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "manual-role-subject", "email": "manualrole@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        # Manually granted, outside any sso_group_mappings entry.
        db.add(UserOrgRole(user_id=user.id, organization_id=org.id, role=OrgRole.PROJECT_CREATOR))
        db.commit()

        sync_org_roles_from_claims(db, user, org, {"groups": ["unrelated-group"]})
        db.commit()

        roles = {
            r.value
            for r in db.scalars(
                select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
            ).all()
        }
        assert roles == {"project_creator"}
    finally:
        db.close()


def test_sync_org_roles_leaves_existing_roles_alone_when_idp_asserts_no_groups_claim_at_all():
    """An IdP that simply doesn't send a groups/roles claim (a provider
    configuration gap, not a genuine "zero groups" assertion) must not
    cause a mass revocation of every SSO-managed role at this org."""
    from sqlalchemy import select

    from app.models.organization import UserOrgRole

    db = SessionLocal()
    try:
        org = Organization(name="OIDC No Claim Org", sso_group_mappings=[{"sso_group": "admins", "org_role": "org_admin"}])
        db.add(org)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "no-claim-subject", "email": "noclaim@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_roles_from_claims(db, user, org, {"groups": ["admins"]})
        db.commit()

        sync_org_roles_from_claims(db, user, org, {})  # no groups/roles claim in this login's token at all
        db.commit()

        roles = db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
        assert "org_admin" in [r.value for r in roles]
    finally:
        db.close()


def test_sync_org_groups_from_claims_grants_membership_in_a_synced_group():
    from sqlalchemy import select

    from app.models.organization import OrgGroup, OrgGroupMember

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Group Sync Org")
        db.add(org)
        db.flush()
        group = OrgGroup(organization_id=org.id, name="Engineering", idp_synced_group_name="eng-team")
        db.add(group)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "group-sync-subject", "email": "groupsync@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_groups_from_claims(db, user, org, {"groups": ["eng-team"]})
        db.commit()

        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id)
        ).all()
        assert user.id in member_ids
    finally:
        db.close()


def test_sync_org_groups_grants_nothing_when_no_group_matches():
    from sqlalchemy import select

    from app.models.organization import OrgGroup, OrgGroupMember

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Group No Match Org")
        db.add(org)
        db.flush()
        group = OrgGroup(organization_id=org.id, name="Engineering", idp_synced_group_name="eng-team")
        db.add(group)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "group-no-match-subject", "email": "groupnomatch@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_groups_from_claims(db, user, org, {"groups": ["unrelated-group"]})
        db.commit()

        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id)
        ).all()
        assert user.id not in member_ids
    finally:
        db.close()


def test_sync_org_groups_revokes_membership_once_matching_group_claim_disappears():
    from sqlalchemy import select

    from app.models.organization import OrgGroup, OrgGroupMember

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Group Sync Down Org")
        db.add(org)
        db.flush()
        group = OrgGroup(organization_id=org.id, name="Engineering", idp_synced_group_name="eng-team")
        db.add(group)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "group-sync-down-subject", "email": "groupsyncdown@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_groups_from_claims(db, user, org, {"groups": ["eng-team"]})
        db.commit()
        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id)
        ).all()
        assert user.id in member_ids

        sync_org_groups_from_claims(db, user, org, {"groups": ["some-other-group"]})
        db.commit()
        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id)
        ).all()
        assert user.id not in member_ids
    finally:
        db.close()


def test_sync_org_groups_never_touches_an_unsynced_group_or_nested_group_edges():
    """A manually-managed group (idp_synced_group_name unset) must never be
    touched, and a synced group's *nested-group* edges (structural,
    admin-managed) must never be added/removed by claims-based sync — only
    direct user membership rows."""
    from sqlalchemy import select

    from app.models.organization import OrgGroup, OrgGroupMember

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Group Unmanaged Org")
        db.add(org)
        db.flush()
        manual_group = OrgGroup(organization_id=org.id, name="Manual Team")
        synced_group = OrgGroup(organization_id=org.id, name="Synced Team", idp_synced_group_name="synced-team")
        db.add_all([manual_group, synced_group])
        db.flush()
        nested_group = OrgGroup(organization_id=org.id, name="Nested Team")
        db.add(nested_group)
        db.flush()
        db.add(OrgGroupMember(org_group_id=synced_group.id, member_org_group_id=nested_group.id))
        db.commit()

        user = find_or_provision_user(
            db, {"sub": "unmanaged-subject", "email": "unmanaged@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        db.add(OrgGroupMember(org_group_id=manual_group.id, user_id=user.id))
        db.commit()

        sync_org_groups_from_claims(db, user, org, {"groups": ["manual team", "unrelated"]})
        db.commit()

        manual_member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == manual_group.id)
        ).all()
        assert user.id in manual_member_ids  # untouched, even though the claim name superficially matches

        nested_edges = db.scalars(
            select(OrgGroupMember.member_org_group_id).where(OrgGroupMember.org_group_id == synced_group.id)
        ).all()
        assert nested_group.id in nested_edges  # nesting edge survives sync untouched
    finally:
        db.close()


def test_sync_org_groups_leaves_existing_membership_alone_when_idp_asserts_no_groups_claim_at_all():
    from sqlalchemy import select

    from app.models.organization import OrgGroup, OrgGroupMember

    db = SessionLocal()
    try:
        org = Organization(name="OIDC Group No Claim Org")
        db.add(org)
        db.flush()
        group = OrgGroup(organization_id=org.id, name="Engineering", idp_synced_group_name="eng-team")
        db.add(group)
        db.flush()
        user = find_or_provision_user(
            db, {"sub": "group-no-claim-subject", "email": "groupnoclaim@example.com", "email_verified": True}, issuer=ISSUER_A,
        )
        sync_org_groups_from_claims(db, user, org, {"groups": ["eng-team"]})
        db.commit()

        sync_org_groups_from_claims(db, user, org, {})  # no groups/roles claim in this login's token at all
        db.commit()

        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id)
        ).all()
        assert user.id in member_ids
    finally:
        db.close()


def test_meets_required_group_admits_everyone_when_unset():
    org = Organization(name="No Gate Org")
    assert meets_required_group(org, {}) is True
    assert meets_required_group(org, {"groups": ["anything"]}) is True


def test_meets_required_group_admits_matching_group_via_groups_or_roles_claim():
    org = Organization(name="Gated Org", oidc_required_group="reqtrack-approved")
    assert meets_required_group(org, {"groups": ["reqtrack-approved"]}) is True
    assert meets_required_group(org, {"roles": ["reqtrack-approved"]}) is True


def test_meets_required_group_rejects_missing_or_unrelated_group():
    org = Organization(name="Gated Org 2", oidc_required_group="reqtrack-approved")
    assert meets_required_group(org, {}) is False
    assert meets_required_group(org, {"groups": ["some-other-group"]}) is False


def test_sso_config_round_trips_required_group(client, admin_token, org_id):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={"slug": "gated-org-slug", "sso_enabled": True, "oidc_required_group": "reqtrack-approved"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["oidc_required_group"] == "reqtrack-approved"

    resp = client.get(f"/api/v1/orgs/{org_id}/sso-config", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["oidc_required_group"] == "reqtrack-approved"


def test_org_group_idp_sync_target_round_trips(client, admin_token, org_id):
    group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Synced Via API"}, headers=auth_headers(admin_token)
    ).json()
    assert group["idp_synced_group_name"] is None

    resp = client.patch(
        f"/api/v1/orgs/{org_id}/groups/{group['id']}", json={"idp_synced_group_name": "eng-team"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["idp_synced_group_name"] == "eng-team"

    groups = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    updated = next(g for g in groups if g["id"] == group["id"])
    assert updated["idp_synced_group_name"] == "eng-team"

    # Clearing it back to None is also supported.
    resp = client.patch(
        f"/api/v1/orgs/{org_id}/groups/{group['id']}", json={"idp_synced_group_name": None},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["idp_synced_group_name"] is None


def test_two_org_groups_cannot_claim_the_same_idp_synced_group_name(client, admin_token, org_id):
    client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "First", "idp_synced_group_name": "eng-team"},
        headers=auth_headers(admin_token),
    )
    second = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Second"}, headers=auth_headers(admin_token)
    ).json()

    resp = client.patch(
        f"/api/v1/orgs/{org_id}/groups/{second['id']}", json={"idp_synced_group_name": "eng-team"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_update_sso_config_requires_org_admin(client, admin_token, org_id):
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For SSO Config Check")
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={"slug": "sneaky", "sso_enabled": True}, headers=auth_headers(other_admin_token),
    )
    assert resp.status_code == 403


def test_sso_config_requires_slug_before_enabling(client, admin_token, org_id):
    resp = client.put(f"/api/v1/orgs/{org_id}/sso-config", json={"sso_enabled": True}, headers=auth_headers(admin_token))
    assert resp.status_code == 400


def test_login_info_by_slug_is_public_and_omits_secrets(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={
            "slug": "public-org-slug", "sso_enabled": True,
            "oidc_issuer_url": "http://example.com/realms/x", "oidc_client_id": "cid",
            "oidc_client_secret": "super-secret-value",
        },
        headers=auth_headers(admin_token),
    )
    resp = client.get("/api/v1/orgs/by-slug/public-org-slug/login-info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sso_enabled"] is True
    assert "oidc_client_secret" not in body
    assert "super-secret-value" not in resp.text


def test_oidc_callback_rejects_a_deactivated_account(client, admin_token, org_id, monkeypatch):
    """Deeper hardening-review finding: `oidc_callback` never checked
    account status at all — only `NativeAuthBackend.authenticate` did. A
    deactivated account could otherwise complete SSO login and receive a
    (functionally inert, since get_current_user also checks is_active)
    token, but worse: consume_pending_invites/sync_org_roles_from_claims
    would still run and commit brand-new role grants before that account
    was ever reactivated. Driven through the real HTTP callback with the
    network-calling OIDC steps stubbed out, not just the provisioning
    helper directly, since the fix lives in the router between those calls."""
    _sso_org(client, admin_token, org_id, "deactivated-oidc-org")
    email = "deactivated-oidc@example.com"
    orphaned_id = _make_orphaned_user(client, admin_token, org_id, email)
    assert client.post(f"/api/v1/system/users/{orphaned_id}/deactivate", headers=auth_headers(admin_token)).status_code == 204

    _patch_fake_oidc(monkeypatch, email=email)
    state = create_oidc_state_token(org_id, "x" * 16)
    resp = client.get(f"/api/v1/auth/oidc/callback?code=fake&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=account_inactive" in resp.headers["location"]
    assert "token=" not in resp.headers["location"]


def test_oidc_callback_rejects_a_banned_account_and_grants_no_pending_invite(client, admin_token, org_id, monkeypatch):
    """A banned account (is_banned implies is_active=False) must be rejected
    the same way, and — the concrete exploit this closes — a PendingInvite
    outstanding for that email at the time of the attempt must NOT be
    consumed/granted by the rejected login."""
    _sso_org(client, admin_token, org_id, "banned-oidc-org")
    email = "banned-oidc@example.com"

    # A PendingInvite outstanding for this email in a *different* org,
    # created while no account for it exists yet anywhere (assign-by-email's
    # "no account exists yet" branch — the only one that actually creates a
    # PendingInvite row rather than checking is_banned against an existing
    # account, see routers/projects.py::assign_project_role_by_email).
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "BannedOidcInviteTargetOrg")
    resp = client.put(
        f"/api/v1/orgs/{other_org['id']}/advanced-settings",
        json={"allow_self_signup": False, "auto_accept_email_domain": None, "external_user_policy": "anyone"},
        headers=auth_headers(other_org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    project = create_project(client, other_org_admin_token, other_org["id"], name="Invite Target Project")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles/by-email",
        json={"email": email, "role": "member"},
        headers=auth_headers(other_org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "invited"

    # Unrelated to that invite: this same email separately has a real,
    # orphaned native account (e.g. it also signed up natively elsewhere
    # first), which then gets banned.
    orphaned_id = _make_orphaned_user(client, admin_token, org_id, email)
    assert client.post(f"/api/v1/system/users/{orphaned_id}/ban", headers=auth_headers(admin_token)).status_code == 204

    _patch_fake_oidc(monkeypatch, email=email)
    state = create_oidc_state_token(org_id, "x" * 16)
    resp = client.get(f"/api/v1/auth/oidc/callback?code=fake&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=account_inactive" in resp.headers["location"]

    org_users = client.get(f"/api/v1/orgs/{other_org['id']}/users", headers=auth_headers(other_org_admin_token)).json()
    assert not any(u["email"] == email for u in org_users), "banned account must not gain the pending invite's org role"
