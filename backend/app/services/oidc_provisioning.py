"""
Module: services.oidc_provisioning

Provisioning logic shared by the OIDC login flow (routers/auth_oidc.py) and,
per the enterprise-integration blueprint (docs/enterprise-integration.md), a
future SCIM implementation: turning verified IdP claims into a local `User`
account and organisation role, for Massif (v3)'s E-U-01.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.organization import Organization, UserOrgRole
from app.models.user import User


def find_or_provision_user(db: Session, claims: dict, *, issuer: str) -> User:
    """Resolves a `User` from verified OIDC claims, provisioning one if needed.

    Resolution order:
        1. By `(external_subject, oidc_issuer)` together — the reliable
           match once a user has ever logged in before. Scoped to the
           issuer, not `external_subject` alone: per the OIDC spec, `sub` is
           only guaranteed unique *within a single issuer*, and since every
           organisation independently configures its own issuer (a routine,
           per-tenant admin action, not a deployment-trusted one), matching
           on `external_subject` alone would let two different, unrelated
           IdPs collide on the same subject value and resolve to the same
           account.
        2. By email, but ONLY when the IdP asserts `email_verified: true` —
           an IdP that doesn't verify email must never be allowed to
           silently take over an existing native account just by claiming
           its address; that would let anyone who can create an account at
           an unverified-email IdP hijack any existing local account.
        3. Otherwise, auto-provisions a new native-less account
           (`auth_backend="oidc"`, `password_hash=None`).

    Args:
        db: Active database session.
        claims: Verified ID token claims (already signature/issuer/audience
            checked by the caller before this function is trusted).
        issuer: The verified issuer URL the claims were checked against
            (`org.oidc_issuer_url`, not a value taken from the claims
            themselves — the caller already confirmed `claims["iss"]`
            matches this before calling).

    Returns:
        The resolved or newly created User (added to the session, not yet committed).
    """
    subject = claims["sub"]
    email = claims.get("email")
    email_verified = bool(claims.get("email_verified", False))

    user = db.scalar(
        select(User).where(User.auth_backend == "oidc", User.external_subject == subject, User.oidc_issuer == issuer)
    )
    if user is not None:
        return user

    if not email:
        raise ValueError("OIDC claims did not include an email address; cannot provision a new user.")

    existing_by_email = db.scalar(select(User).where(User.email == email))
    if existing_by_email is not None:
        if not email_verified:
            # Refuse outright rather than falling through to "provision a
            # new user" below: a second User row with this same email is
            # impossible anyway (unique constraint), and silently linking
            # to the existing account without a verified-email assertion is
            # exactly the account-takeover this check exists to prevent.
            raise ValueError(
                f"{email} is already registered and this identity provider did not assert a verified email; "
                "refusing to link automatically."
            )
        if existing_by_email.auth_backend != "oidc" or not existing_by_email.external_subject:
            existing_by_email.auth_backend = "oidc"
            existing_by_email.external_subject = subject
            existing_by_email.oidc_issuer = issuer
        return existing_by_email

    user = User(
        id=uuid.uuid4(), email=email, display_name=claims.get("name") or email.split("@")[0],
        auth_backend="oidc", external_subject=subject, oidc_issuer=issuer, password_hash=None,
    )
    db.add(user)
    db.flush()
    return user


def meets_required_group(org: Organization, claims: dict) -> bool:
    """Whether `claims` satisfy `org.oidc_required_group`, the access gate
    checked before a token is ever issued (distinct from
    `sso_group_mappings`, which decides *which* org role a user gets, not
    *whether* they're let in at all).

    When `org.oidc_required_group` is unset, every successfully-authenticated
    user is admitted (today's default behaviour) — the gate is opt-in per
    organisation. When set, the IdP's `groups` or `roles` claim (whichever
    the provider uses — both are checked, same as role-mapping) must contain
    that exact group name, or the login is refused before a session is
    created, regardless of what `sso_group_mappings` would otherwise grant.
    """
    if not org.oidc_required_group:
        return True
    idp_groups = set(claims.get("groups") or []) | set(claims.get("roles") or [])
    return org.oidc_required_group in idp_groups


def sync_org_roles_from_claims(db: Session, user: User, org: Organization, claims: dict) -> None:
    """Grants/updates `user`'s role in `org` based on `org.sso_group_mappings`
    (C-U-07, E-U-01) — a list of `{"sso_group": ..., "org_role": ...}`
    entries matched against the IdP's group/role claim.

    This is the concrete answer to "how does a user provisioned via SSO gain
    their application permissions": the IdP asserts group membership (in the
    `groups` or `roles` claim, whichever the provider uses — both are
    checked), each configured mapping whose `sso_group` appears in either
    claim grants the corresponding `OrgRole`. A user with no matching group
    still gets a `User` account (provisioned above) but no org role — they
    can log in but see no organisation content until an admin either adds a
    mapping or grants them a role directly, same as any other user with no
    role.
    """
    idp_groups = set(claims.get("groups") or []) | set(claims.get("roles") or [])
    if not idp_groups:
        return

    mapped_roles = {
        OrgRole(m["org_role"]) for m in org.sso_group_mappings if m.get("sso_group") in idp_groups
    }
    if not mapped_roles:
        return

    existing_roles = set(
        db.scalars(
            select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == org.id)
        ).all()
    )
    for role in mapped_roles - existing_roles:
        db.add(UserOrgRole(user_id=user.id, organization_id=org.id, role=role))
