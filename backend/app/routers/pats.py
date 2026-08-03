"""
Module: routers.pats

Self-service Personal Access Token management: create, list, and revoke
(single or all at once) the caller's own tokens. The org-admin and
server-admin incident-response actions (per-token revoke/descope, bulk
revoke-all) live in routers/orgs.py and routers/system.py respectively,
alongside those routers' other org-/deployment-scoped admin actions —
see docs/decisions.md's "Personal Access Tokens" section for why.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.user import User
from app.schemas.pat import (
    BulkRevokeResult,
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreateOut,
    PersonalAccessTokenOrgRef,
    PersonalAccessTokenOut,
)
from app.security import generate_pat
from app.services.audit import log_event
from app.services.pats import compute_expiry_ceiling, effective_expiry, revoke_matching
from app.services.rbac import get_effective_org_roles

router = APIRouter(prefix="/api/v1/me/pats", tags=["personal-access-tokens"])


def _resolve_org_refs(db: Session, org_id_strs: list[str]) -> list[PersonalAccessTokenOrgRef]:
    orgs = db.scalars(select(Organization).where(Organization.id.in_(UUID(i) for i in org_id_strs))).all()
    return [PersonalAccessTokenOrgRef(id=org.id, name=org.name) for org in orgs]


@router.post("", response_model=PersonalAccessTokenCreateOut, status_code=status.HTTP_201_CREATED)
def create_pat(
    payload: PersonalAccessTokenCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a new Personal Access Token, scoped to the given orgs.

    The caller must hold some role in every listed org — not a security
    boundary by itself (real RBAC still gates everything the token is
    later used for), just preventing a confusing token that could never
    do anything. Returns the raw token secret once; it is never
    retrievable again afterward.
    """
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name is required.")
    if not payload.allowed_organization_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one organisation must be selected.")
    for org_id in payload.allowed_organization_ids:
        if not get_effective_org_roles(db, current_user.id, org_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You do not have a role in one or more selected organisations.")

    raw_token, token_hash, token_prefix = generate_pat()
    expires_at = compute_expiry_ceiling(db, payload.allowed_organization_ids, payload.requested_expires_at)
    pat = PersonalAccessToken(
        user_id=current_user.id,
        name=payload.name.strip(),
        token_hash=token_hash,
        token_prefix=token_prefix,
        allowed_organization_ids=[str(i) for i in payload.allowed_organization_ids],
        expires_at_ceiling=expires_at,
    )
    db.add(pat)
    db.flush()
    log_event(db, entity_type="personal_access_token", entity_id=pat.id, action="pat_created", actor_id=current_user.id)
    db.commit()
    db.refresh(pat)

    return PersonalAccessTokenCreateOut(
        id=pat.id, name=pat.name, token=raw_token, token_prefix=pat.token_prefix,
        allowed_organizations=_resolve_org_refs(db, pat.allowed_organization_ids),
        expires_at=pat.expires_at_ceiling, created_at=pat.created_at,
    )


@router.get("", response_model=list[PersonalAccessTokenOut])
def list_my_pats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lists the caller's own tokens (revoked ones included, so they can
    still see their own history) — never the secret or its hash."""
    pats = db.scalars(
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == current_user.id)
        .order_by(PersonalAccessToken.created_at.desc())
    ).all()
    return [
        PersonalAccessTokenOut(
            id=p.id, name=p.name, token_prefix=p.token_prefix,
            allowed_organizations=_resolve_org_refs(db, p.allowed_organization_ids),
            expires_at=effective_expiry(db, p), revoked_at=p.revoked_at,
            last_used_at=p.last_used_at, created_at=p.created_at,
        )
        for p in pats
    ]


@router.delete("/{pat_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_pat(pat_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revokes one of the caller's own tokens. 404 (not 403) if the id
    doesn't belong to the caller — the same IDOR-safe non-disclosure
    pattern used elsewhere in this codebase, so a caller can't probe for
    the existence of another user's token."""
    pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.id == pat_id, PersonalAccessToken.user_id == current_user.id))
    if pat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personal access token not found.")
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(UTC)
        log_event(db, entity_type="personal_access_token", entity_id=pat.id, action="pat_revoked", actor_id=current_user.id)
        db.commit()


@router.post("/revoke-all", response_model=BulkRevokeResult)
def revoke_all_my_pats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revokes every one of the caller's own non-revoked tokens in one call."""
    count = revoke_matching(db, PersonalAccessToken.user_id == current_user.id)
    log_event(
        db, entity_type="user", entity_id=current_user.id, action="pats_bulk_revoked",
        actor_id=current_user.id, detail={"count": count},
    )
    db.commit()
    return BulkRevokeResult(revoked_count=count)
