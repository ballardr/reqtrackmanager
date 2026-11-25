"""
Module: services.pats

Business logic for Personal Access Tokens: expiry computation (both at
creation and dynamically at auth time) and the shared bulk-revocation
primitive used by the self-service, org-admin, and server-admin endpoints
alike. See models/pat.py and docs/decisions.md's "Personal Access Tokens"
section for the full design.

This module is imported by both app.deps (to enforce expiry on every
authenticated request) and the PAT-related routers (to compute expiry at
creation and to answer "what does this org's cap currently mean"), so the
one `effective_expiry` calculation lives here rather than being duplicated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.project import Project
from app.models.user import User
from app.security import generate_pat
from app.services.lookups import affected_rows
from app.services.rbac import get_effective_org_roles, get_effective_project_roles

settings = get_settings()


def org_max_lifetime_days(org: Organization) -> int:
    """An organisation's effective PAT max-lifetime cap: its own
    `pat_max_lifetime_days` if set, else the deployment-wide default."""
    return org.pat_max_lifetime_days or settings.pat_default_max_lifetime_days


def compute_expiry_ceiling(db: Session, allowed_organization_ids: list[UUID], requested_expires_at: datetime | None) -> datetime:
    """Computes the `expires_at_ceiling` to store on a new PAT.

    This is `min(requested_expires_at, now + shortest scoped org's cap)` —
    a caller-requested expiry beyond what the scoped orgs allow is silently
    clamped rather than rejected, so the creation response can just show
    the real resulting value instead of needing a round-trip error/retry.
    """
    now = datetime.now(UTC)
    shortest_cap_days = min(
        (org_max_lifetime_days(org) for org in db.scalars(select(Organization).where(Organization.id.in_(allowed_organization_ids)))),
        default=settings.pat_default_max_lifetime_days,
    )
    ceiling = now + timedelta(days=shortest_cap_days)
    if requested_expires_at is not None and requested_expires_at < ceiling:
        return requested_expires_at
    return ceiling


def create_token(
    db: Session, *, owner: User, issuer: User, name: str, organization_ids: list[UUID], project_ids: list[UUID],
    requested_expires_at: datetime | None,
) -> tuple[PersonalAccessToken, str]:
    """Creates a token for `owner`, issued by `issuer` (the owner themself, or an administrator for a service user).

    The one place a token row is made, so hash-only storage, the scope rules, the expiry ceiling and the
    organisation lifetime cap apply the same to both routes. The owner must hold a role in every listed organisation
    and some role on every listed project (not a security boundary: real access control still gates what the token
    does, this only prevents a token that could never do anything).

    Args:
        db: Active session; the row is added and flushed, not committed.
        owner: The account the token authenticates as.
        issuer: Who is issuing it (recorded as `created_by_user_id`).
        name: The label (blank is refused).
        organization_ids: The organisations it may be used against (at least one).
        project_ids: Optional further restriction to projects of those organisations.
        requested_expires_at: A shorter expiry than the ceiling, or `None` for the ceiling.

    Returns:
        The token row and its raw secret, which the caller shows once and never stores or logs.

    Raises:
        HTTPException: 400 for a blank name, no organisation, a role or project access the owner lacks, or a
            project outside the listed organisations.
    """
    who = "You do" if owner.id == issuer.id else "The service user does"
    if not name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name is required.")
    if not organization_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one organisation must be selected.")
    for org_id in organization_ids:
        if not get_effective_org_roles(db, owner.id, org_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{who} not have a role in one or more selected organisations.")
    allowed_org_ids = set(organization_ids)
    for project_id in project_ids:
        project = db.get(Project, project_id)
        if project is None or project.organization_id not in allowed_org_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Each selected project must belong to one of the selected organisations."
            )
        if not get_effective_project_roles(db, owner.id, project_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{who} not have access to one or more selected projects.")
    raw_token, token_hash, token_prefix = generate_pat()
    pat = PersonalAccessToken(
        user_id=owner.id, created_by_user_id=issuer.id, name=name.strip(), token_hash=token_hash,
        token_prefix=token_prefix, allowed_organization_ids=[str(i) for i in organization_ids],
        allowed_project_ids=[str(i) for i in project_ids],
        expires_at_ceiling=compute_expiry_ceiling(db, organization_ids, requested_expires_at),
    )
    db.add(pat)
    db.flush()
    return pat, raw_token


def effective_expiry(db: Session, pat: PersonalAccessToken) -> datetime:
    """Computes a PAT's actual, currently-enforced expiry.

    `min(pat.expires_at_ceiling, *cap)`, where `cap` is one entry per
    currently-scoped org: `pat.created_at + that org's *current*
    pat_max_lifetime_days (or the system default)`. Recomputing from live
    org settings on every check — rather than only trusting the stored
    `expires_at_ceiling` — is what makes an org admin tightening their cap
    apply retroactively to already-issued tokens: this can only ever push
    the effective expiry earlier than `expires_at_ceiling`, never later
    (raising a cap never extends a token past what was fixed at creation).
    """
    caps = [pat.expires_at_ceiling]
    for org_id in pat.allowed_organization_ids:
        org = db.get(Organization, UUID(org_id))
        if org is not None:
            caps.append(pat.created_at + timedelta(days=org_max_lifetime_days(org)))
    return min(caps)


def is_usable(db: Session, pat: PersonalAccessToken) -> bool:
    """Whether a PAT is currently neither revoked nor past its effective expiry."""
    return pat.revoked_at is None and datetime.now(UTC) < effective_expiry(db, pat)


def revoke_all_for_user(db: Session, user_id: UUID) -> int:
    """Revokes every active Personal Access Token the user owns (a response to suspected compromise).

    Called when a password is reset through an emailed link and when two-factor authentication is switched off:
    both are recovery or weakening steps after which a token created earlier, with no second factor, must not
    survive. A routine password change does not call it, so an integration is not reconfigured by it.

    Returns:
        How many tokens were revoked.
    """
    return revoke_matching(db, PersonalAccessToken.user_id == user_id)


def revoke_matching(db: Session, predicate) -> int:
    """Revokes every currently-active PAT matching `predicate` in one
    statement, returning how many rows were affected. Shared by the
    self-service "revoke all mine", org-admin "revoke all in my org", and
    server-admin "revoke all platform-wide" bulk actions — each supplies a
    different SQLAlchemy filter expression as `predicate`.
    """
    result = db.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.revoked_at.is_(None), predicate)
        .values(revoked_at=datetime.now(UTC))
    )
    return affected_rows(result)
