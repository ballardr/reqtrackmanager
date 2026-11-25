"""
Module: routers.pats

Self-service Personal Access Token management: create, list and revoke (single or all at once) the
caller's own tokens. The org-admin and server-admin incident-response actions (per-token revoke/descope,
bulk revoke-all) live with those routers' other admin actions (docs/decisions.md's "Personal Access Tokens").

Every endpoint needs an interactive session (`deps.get_current_session_user`), never a PAT: a token that
could mint a wider or longer-lived token would make its own scope and expiry meaningless.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_session_user
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.project import Project
from app.models.user import User
from app.schemas.pat import (
    BulkRevokeResult,
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreateOut,
    PersonalAccessTokenOrgRef,
    PersonalAccessTokenOut,
    PersonalAccessTokenProjectRef,
)
from app.services.audit import log_event
from app.services.pats import compute_expiry_ceiling, create_token, effective_expiry, revoke_matching

router = APIRouter(prefix="/api/v1/me/pats", tags=["personal-access-tokens"])


def _resolve_org_refs(db: Session, org_id_strs: list[str]) -> list[PersonalAccessTokenOrgRef]:
    orgs = db.scalars(select(Organization).where(Organization.id.in_(UUID(i) for i in org_id_strs))).all()
    return [PersonalAccessTokenOrgRef(id=org.id, name=org.name) for org in orgs]


def _resolve_project_refs(db: Session, project_id_strs: list[str]) -> list[PersonalAccessTokenProjectRef]:
    if not project_id_strs:
        return []
    projects = db.scalars(select(Project).where(Project.id.in_(UUID(i) for i in project_id_strs))).all()
    return [PersonalAccessTokenProjectRef(id=p.id, name=p.name) for p in projects]


@router.get("/max-lifetime")
def get_max_lifetime(
    organization_ids: list[UUID] = Query(default_factory=list),
    current_user: User = Depends(get_current_session_user),
    db: Session = Depends(get_db),
) -> dict:
    """Returns the longest expiry currently allowed for a token scoped to the given orgs, the value
    `compute_expiry_ceiling` produces for a request with no explicit `requested_expires_at`.

    Lets the create-PAT form show and pre-fill it. An org's `pat_max_lifetime_days` is readable only by that
    org's admin (`GET .../advanced-settings`), but the resulting date is harmless to show to any member
    creating their own token.
    """
    max_expires_at = compute_expiry_ceiling(db, organization_ids, None)
    return {"max_expires_at": max_expires_at}


@router.post("", response_model=PersonalAccessTokenCreateOut, status_code=status.HTTP_201_CREATED)
def create_pat(
    payload: PersonalAccessTokenCreate,
    current_user: User = Depends(get_current_session_user),
    db: Session = Depends(get_db),
):
    """Creates a new Personal Access Token, scoped to the given orgs.

    The caller must hold some role in every listed org — not a security
    boundary by itself (real RBAC still gates everything the token is
    later used for), just preventing a confusing token that could never
    do anything. Returns the raw token secret once; it is never
    retrievable again afterward.
    """
    pat, raw_token = create_token(
        db, owner=current_user, issuer=current_user, name=payload.name, organization_ids=payload.allowed_organization_ids,
        project_ids=payload.allowed_project_ids, requested_expires_at=payload.requested_expires_at,
    )
    log_event(db, entity_type="personal_access_token", entity_id=pat.id, action="pat_created", actor_id=current_user.id)
    db.commit()
    db.refresh(pat)

    return PersonalAccessTokenCreateOut(
        id=pat.id, name=pat.name, token=raw_token, token_prefix=pat.token_prefix,
        allowed_organizations=_resolve_org_refs(db, pat.allowed_organization_ids),
        allowed_projects=_resolve_project_refs(db, pat.allowed_project_ids),
        expires_at=pat.expires_at_ceiling, created_at=pat.created_at,
    )


@router.get("", response_model=list[PersonalAccessTokenOut])
def list_my_pats(current_user: User = Depends(get_current_session_user), db: Session = Depends(get_db)):
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
            allowed_projects=_resolve_project_refs(db, p.allowed_project_ids),
            expires_at=effective_expiry(db, p), revoked_at=p.revoked_at,
            last_used_at=p.last_used_at, created_at=p.created_at,
        )
        for p in pats
    ]


@router.delete("/{pat_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_pat(pat_id: UUID, current_user: User = Depends(get_current_session_user), db: Session = Depends(get_db)):
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
def revoke_all_my_pats(current_user: User = Depends(get_current_session_user), db: Session = Depends(get_db)):
    """Revokes every one of the caller's own non-revoked tokens in one call."""
    count = revoke_matching(db, PersonalAccessToken.user_id == current_user.id)
    log_event(
        db, entity_type="user", entity_id=current_user.id, action="pats_bulk_revoked",
        actor_id=current_user.id, detail={"count": count},
    )
    db.commit()
    return BulkRevokeResult(revoked_count=count)
