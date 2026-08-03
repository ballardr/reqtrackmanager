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

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken

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
    return result.rowcount
