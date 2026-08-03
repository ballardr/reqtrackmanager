"""Tests for Massif (v3) OIDC provisioning logic (E-U-01) and org SSO
configuration endpoints. The full browser-driven login flow against a real
Keycloak instance is covered by
tests/playwright/tests/e2e-workflows/sso.spec.ts, not here — this file
covers `services/oidc_provisioning.py` directly with synthetic claims (no
network calls), and the config API surface."""

import pytest

from app.database import SessionLocal
from app.models.organization import Organization
from app.services.oidc_provisioning import find_or_provision_user, meets_required_group, sync_org_roles_from_claims
from tests.conftest import auth_headers, create_org_admin_in

ISSUER_A = "https://idp-a.example.com/realms/tenant"
ISSUER_B = "https://idp-b.example.com/realms/other-tenant"


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
