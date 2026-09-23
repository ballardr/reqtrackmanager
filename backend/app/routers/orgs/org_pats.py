"""
Module: routers.orgs.org_pats

Organisation-admin-side Personal Access Token incident-response actions:
list every non-revoked token touching this org, revoke or descope one
specific token, or revoke every token touching this org in one action.
Self-service creation/listing/revocation lives in `routers/pats.py` under
`/api/v1/me/pats` — see docs/decisions.md's "Personal Access Tokens"
section for the full design, in particular why the per-token view only
ever reveals *how many* other orgs a multi-org token also reaches, never
which ones.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.pat import PersonalAccessToken
from app.models.user import User
from app.schemas.pat import BulkRevokeResult, OrgPersonalAccessTokenOut
from app.services.audit import log_event
from app.services.pats import effective_expiry, revoke_matching
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-pats"])


def _get_org_pat_or_404(db: Session, organization_id: UUID, pat_id: UUID) -> PersonalAccessToken:
    # Row-locked (not a plain db.get): descope_org_pat below does a
    # read-modify-write on allowed_organization_ids (read the current list,
    # remove one org, write it back) — without a lock, two concurrent
    # descope calls on the same multi-org token (e.g. org A's admin and org
    # B's admin both reacting to the same incident at once, exactly the
    # scenario this feature exists for) would each read the same
    # pre-removal list and whichever commits last would silently overwrite
    # the other's removal, leaving that org's admin believing their
    # descope succeeded (204, a real audit-log row) when the token in fact
    # remained scoped to their org. The lock makes the second call block
    # until the first commits, then read the already-updated list.
    pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.id == pat_id).with_for_update())
    if pat is None or str(organization_id) not in pat.allowed_organization_ids:
        # 404, not 403: this org's admin must not be able to distinguish
        # "no such token" from "a real token that just isn't scoped here."
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personal access token not found.")
    return pat


@router.get("/{organization_id}/pats", response_model=list[OrgPersonalAccessTokenOut])
def list_org_pats(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    pats = db.scalars(
        select(PersonalAccessToken)
        .where(
            PersonalAccessToken.revoked_at.is_(None),
            PersonalAccessToken.allowed_organization_ids.contains([str(organization_id)]),
        )
        .order_by(PersonalAccessToken.created_at.desc())
    ).all()
    owners = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.user_id for p in pats}))).all()}
    return [
        OrgPersonalAccessTokenOut(
            id=p.id, user_id=p.user_id,
            user_email=owners[p.user_id].email, user_display_name=owners[p.user_id].display_name,
            name=p.name, token_prefix=p.token_prefix, expires_at=effective_expiry(db, p),
            other_org_count=len(p.allowed_organization_ids) - 1,
            last_used_at=p.last_used_at, created_at=p.created_at,
        )
        for p in pats
    ]


@router.post("/{organization_id}/pats/{pat_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_org_pat(
    organization_id: UUID, pat_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes one specific token outright — e.g. a member who has left
    this org, whose token isn't (or shouldn't remain) usable anywhere."""
    pat = _get_org_pat_or_404(db, organization_id, pat_id)
    pat.revoked_at = datetime.now(UTC)
    log_event(
        db, entity_type="personal_access_token", entity_id=pat.id, action="org_pat_revoked",
        actor_id=current_user.id, organization_id=organization_id, detail={"pat_owner_id": str(pat.user_id)},
    )
    db.commit()


@router.post("/{organization_id}/pats/{pat_id}/descope", status_code=status.HTTP_204_NO_CONTENT)
def descope_org_pat(
    organization_id: UUID, pat_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Removes this org from a token's scope, leaving it valid for the
    member's other orgs — the softer alternative to `revoke_org_pat` when a
    multi-org token shouldn't reach this org anymore but its owner still
    legitimately needs it elsewhere. Auto-revokes if this was the token's
    only remaining org (a token scoped to nothing can never authenticate
    anything anyway)."""
    pat = _get_org_pat_or_404(db, organization_id, pat_id)
    pat.allowed_organization_ids = [oid for oid in pat.allowed_organization_ids if oid != str(organization_id)]
    if not pat.allowed_organization_ids:
        pat.revoked_at = datetime.now(UTC)
    log_event(
        db, entity_type="personal_access_token", entity_id=pat.id, action="org_pat_descoped",
        actor_id=current_user.id, organization_id=organization_id, detail={"pat_owner_id": str(pat.user_id)},
    )
    db.commit()


@router.post("/{organization_id}/pats/revoke-all", response_model=BulkRevokeResult)
def revoke_all_org_pats(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes every non-revoked token touching this org, across every
    member, in one incident-response action. Fully kills each matching
    token — including any other orgs it's also scoped to — rather than
    just descoping this org from it; see docs/decisions.md for why."""
    count = revoke_matching(db, PersonalAccessToken.allowed_organization_ids.contains([str(organization_id)]))
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="org_pats_bulk_revoked",
        actor_id=current_user.id, organization_id=organization_id, detail={"count": count},
    )
    db.commit()
    return BulkRevokeResult(revoked_count=count)

