"""
Module: routers.orgs.scoring

Organisation-level endpoints of the generic scoring-matrix mechanism
(Module 1 Phase 10): read a scheme's effective configuration, edit its
axis levels, and set the org default model and rating bands. Scheme keys
come from the module registry; every route 404s unless the caller is an
org member and the scheme's owning module is enabled for the org.

Reads are open to any org member (scorers need the levels). Writes need
org admin, or the scheme's own `admin_role_key` module role if it declares
one (`user_satisfies_module_role` composes org admin in automatically).
Every write is audit-logged by `services.scoring`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.user import User
from app.modules.registry import RegisteredScoringScheme, get_all_registered_scoring_schemes, is_module_enabled
from app.schemas.scoring import (
    ScoringBandsIn,
    ScoringDefaultModelIn,
    ScoringLevelCreate,
    ScoringLevelOut,
    ScoringLevelUpdate,
    ScoringSchemeOut,
)
from app.services import scoring
from app.services.rbac import (
    is_org_admin,
    require_org_access_and_module_enabled,
    require_org_role,
    user_satisfies_module_role,
)

router = APIRouter(tags=["organizations-scoring"])


def _load_scheme(
    db: Session, user: User, organization_id: UUID, scheme_key: str, request: Request,
) -> RegisteredScoringScheme:
    """Returns the registered scheme after the membership/enablement gate.

    Raises:
        HTTPException: 404 for an unknown scheme, a non-member, or a
            disabled module.
    """
    registered = scoring.get_registered_scheme(scheme_key)
    require_org_access_and_module_enabled(db, user, organization_id, registered.module_key, request)
    return registered


def _require_scheme_admin(db: Session, user: User, organization_id: UUID, registered: RegisteredScoringScheme) -> None:
    """Raises 403 unless `user` may edit this scheme's org configuration."""
    role_key = registered.scheme.admin_role_key
    allowed = (
        user_satisfies_module_role(db, user, registered.module_key, role_key, organization_id=organization_id)
        if role_key else is_org_admin(db, user.id, organization_id)
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions to configure scoring.")


@router.get("/{organization_id}/scoring-schemes", response_model=list[ScoringSchemeOut])
def list_scoring_schemes(
    organization_id: UUID,
    _user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists the effective configuration of every scoring scheme whose
    module is enabled for this organisation (any org member; the shared
    `require_org_role` gate applies PAT scope, org-active and 2FA checks)."""
    return [
        scoring.build_scheme_config(db, organization_id, registered)
        for registered in get_all_registered_scoring_schemes().values()
        if is_module_enabled(db, organization_id, registered.module_key)
    ]


@router.get("/{organization_id}/scoring-schemes/{scheme_key}", response_model=ScoringSchemeOut)
def get_scoring_scheme(
    organization_id: UUID, scheme_key: str, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Returns one scheme's org-level effective configuration."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    return scoring.build_scheme_config(db, organization_id, registered)


@router.post(
    "/{organization_id}/scoring-schemes/{scheme_key}/axes/{axis_key}/levels",
    response_model=ScoringLevelOut, status_code=status.HTTP_201_CREATED,
)
def create_scoring_level(
    organization_id: UUID, scheme_key: str, axis_key: str, payload: ScoringLevelCreate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Adds a level to one axis."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    level = scoring.create_level(
        db, organization_id, registered, axis_key, name=payload.name.strip(),
        weight=Decimal(str(payload.weight)), description=payload.description, actor_id=current_user.id,
    )
    db.commit()
    return ScoringLevelOut(id=level.id, name=level.name, description=level.description, weight=float(level.weight))


@router.patch("/{organization_id}/scoring-schemes/{scheme_key}/levels/{level_id}", response_model=ScoringLevelOut)
def update_scoring_level(
    organization_id: UUID, scheme_key: str, level_id: UUID, payload: ScoringLevelUpdate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Renames, re-weights or re-describes a level. Scores reference the
    level by id, so every score using it changes with its weight."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    level = scoring.get_level(db, organization_id, scheme_key, level_id)
    scoring.update_level(
        db, level, name=payload.name.strip() if payload.name else None,
        weight=Decimal(str(payload.weight)) if payload.weight is not None else None,
        description=payload.description, set_description="description" in payload.model_fields_set,
        actor_id=current_user.id,
    )
    db.commit()
    return ScoringLevelOut(id=level.id, name=level.name, description=level.description, weight=float(level.weight))


@router.delete(
    "/{organization_id}/scoring-schemes/{scheme_key}/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def delete_scoring_level(
    organization_id: UUID, scheme_key: str, level_id: UUID, request: Request,
    reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Deletes a level: 409 if the axis would drop below two levels, or if
    it's in use and no `reassign_to_id` (same axis) is given."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    level = scoring.get_level(db, organization_id, scheme_key, level_id)
    scoring.delete_level(db, level, registered, reassign_to_id=reassign_to_id, actor_id=current_user.id)
    db.commit()


@router.put("/{organization_id}/scoring-schemes/{scheme_key}/default-model", response_model=ScoringSchemeOut)
def set_org_default_scoring_model(
    organization_id: UUID, scheme_key: str, payload: ScoringDefaultModelIn, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Sets the org default model, or clears it (`null`) to use the
    system default."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring.set_default_model(db, organization_id, registered.scheme, payload.model,
                              project_id=None, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.put(
    "/{organization_id}/scoring-schemes/{scheme_key}/models/{model_key}/bands", response_model=ScoringSchemeOut,
)
def set_org_scoring_bands(
    organization_id: UUID, scheme_key: str, model_key: str, payload: ScoringBandsIn, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Replaces the org's rating bands for one model, or clears them
    (`null`) to use the module's defaults."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    bands = None if payload.bands is None else [
        scoring.BandValue(label=b.label, min_score=b.min_score, tone=b.tone) for b in payload.bands
    ]
    scoring.set_bands(db, organization_id, registered.scheme, model_key, bands,
                      project_id=None, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)
