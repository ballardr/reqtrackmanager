"""
Module: routers.orgs.scoring

Organisation-level endpoints of the generic scoring-matrix mechanism
: read a scheme's effective configuration, edit its
axis levels, and set the org default model, rating bands and per-cell rating overrides. Scheme keys
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
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.registry import RegisteredScoringScheme, get_all_registered_scoring_schemes, is_module_enabled
from app.schemas.scoring import (
    ScoringAxisCreate,
    ScoringAxisUpdate,
    ScoringBandsIn,
    ScoringCellRatingsIn,
    ScoringCriterionRef,
    ScoringDefaultModelIn,
    ScoringEnabledModelsIn,
    ScoringLevelCreate,
    ScoringLevelOut,
    ScoringLevelUpdate,
    ScoringModelCreate,
    ScoringModelUpdate,
    ScoringSchemeOut,
)
from app.services import scoring, scoring_custom
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


def _effective(db: Session, organization_id: UUID, registered: RegisteredScoringScheme) -> RegisteredScoringScheme:
    """`registered` with the organisation's custom axes and models added and its hidden ones left out."""
    return scoring_custom.effective_registered(db, organization_id, registered)


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


def _level_out(level: ScoringLevel) -> ScoringLevelOut:
    """The API shape of one level."""
    return ScoringLevelOut(
        id=level.id, name=level.name, description=level.description, weight=float(level.weight),
        threshold=None if level.threshold is None else float(level.threshold),
        org_threshold=None if level.threshold is None else float(level.threshold),
    )


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
    scoring_custom.require_axis_editable(db, organization_id, scheme_key, axis_key, None)
    level = scoring.create_level(
        db, organization_id, _effective(db, organization_id, registered), axis_key, name=payload.name.strip(),
        weight=Decimal(str(payload.weight)), description=payload.description, actor_id=current_user.id,
        threshold=None if payload.threshold is None else Decimal(str(payload.threshold)),
    )
    db.commit()
    return _level_out(level)


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
    scoring_custom.require_axis_editable(db, organization_id, scheme_key, level.axis_key, None)
    scoring.update_level(
        db, level, name=payload.name.strip() if payload.name else None,
        weight=Decimal(str(payload.weight)) if payload.weight is not None else None,
        description=payload.description, set_description="description" in payload.model_fields_set,
        actor_id=current_user.id, threshold=None if payload.threshold is None else Decimal(str(payload.threshold)),
        scheme=_effective(db, organization_id, registered).scheme,
    )
    db.commit()
    return _level_out(level)


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
    scoring_custom.require_axis_editable(db, organization_id, scheme_key, level.axis_key, None)
    scoring.delete_level(db, level, _effective(db, organization_id, registered), reassign_to_id=reassign_to_id, actor_id=current_user.id)
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
    scoring.set_default_model(db, organization_id, _effective(db, organization_id, registered).scheme, payload.model,
                              project_id=None, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.put("/{organization_id}/scoring-schemes/{scheme_key}/enabled-models", response_model=ScoringSchemeOut)
def set_org_enabled_scoring_models(
    organization_id: UUID, scheme_key: str, payload: ScoringEnabledModelsIn, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Sets the models the organisation shows side by side, or clears them (`null`) to enable every model."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring.set_enabled_models(db, organization_id, _effective(db, organization_id, registered).scheme, payload.models,
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
    scoring.set_bands(db, organization_id, _effective(db, organization_id, registered).scheme, model_key, bands,
                      project_id=None, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.put(
    "/{organization_id}/scoring-schemes/{scheme_key}/models/{model_key}/cell-ratings",
    response_model=ScoringSchemeOut,
)
def set_org_scoring_cell_ratings(
    organization_id: UUID, scheme_key: str, model_key: str, payload: ScoringCellRatingsIn, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Replaces the org's per-cell rating overrides for one two-axis model,
    or clears them (`null`) so cells use the rating bands' thresholds."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    cells = None if payload.cells is None else [
        scoring.CellRatingValue(c.first_level_id, c.second_level_id, c.band_label) for c in payload.cells
    ]
    scoring.set_cell_ratings(db, organization_id, _effective(db, organization_id, registered).scheme, model_key, cells,
                             project_id=None, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


# --- Organisation-defined axes and models, hidden registered criteria ----------------------------------------------


def _axis_levels(payload: ScoringAxisCreate) -> list[scoring_custom.LevelSpec]:
    return [scoring_custom.LevelSpec(lvl.name, lvl.weight, lvl.description) for lvl in payload.levels]


def _model_axes(axes) -> list[scoring_custom.ModelAxisSpec]:
    return [
        scoring_custom.ModelAxisSpec(a.axis_key, a.role, a.exponent, a.importance, a.lower_is_better) for a in axes
    ]


@router.post(
    "/{organization_id}/scoring-schemes/{scheme_key}/axes", response_model=ScoringSchemeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_org_scoring_axis(
    organization_id: UUID, scheme_key: str, payload: ScoringAxisCreate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Defines an axis (with its levels) for the whole organisation. 400 if the scheme takes no custom criteria."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.create_axis(
        db, organization_id, registered.scheme, project_id=None, label=payload.label, description=payload.description,
        levels=_axis_levels(payload), actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.patch("/{organization_id}/scoring-schemes/{scheme_key}/axes/{axis_key}", response_model=ScoringSchemeOut)
def update_org_scoring_axis(
    organization_id: UUID, scheme_key: str, axis_key: str, payload: ScoringAxisUpdate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Renames or re-describes an organisation axis."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.update_axis(
        db, organization_id, registered.scheme, axis_key, project_id=None, label=payload.label,
        description=payload.description, set_description="description" in payload.model_fields_set,
        actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.delete("/{organization_id}/scoring-schemes/{scheme_key}/axes/{axis_key}", response_model=ScoringSchemeOut)
def delete_org_scoring_axis(
    organization_id: UUID, scheme_key: str, axis_key: str, request: Request, clear_scores: bool = Query(False),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Deletes an organisation axis and its levels: 409 if a model uses it, or scores use it and `clear_scores`
    was not given (which drops those scores)."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.delete_axis(
        db, organization_id, registered, axis_key, project_id=None, clear_scores=clear_scores, actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.post(
    "/{organization_id}/scoring-schemes/{scheme_key}/models", response_model=ScoringSchemeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_org_scoring_model(
    organization_id: UUID, scheme_key: str, payload: ScoringModelCreate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Defines a model (a product with divisors and exponents, or a weighted sum) for the whole organisation."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.create_model(
        db, organization_id, registered.scheme, project_id=None, label=payload.label,
        combination=payload.combination, axes=_model_axes(payload.axes), actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.patch("/{organization_id}/scoring-schemes/{scheme_key}/models/{model_key}", response_model=ScoringSchemeOut)
def update_org_scoring_model(
    organization_id: UUID, scheme_key: str, model_key: str, payload: ScoringModelUpdate, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Renames an organisation model and/or replaces how it combines its axes (its per-cell ratings are dropped)."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.update_model(
        db, organization_id, registered.scheme, model_key, project_id=None, label=payload.label,
        combination=payload.combination, axes=None if payload.axes is None else _model_axes(payload.axes),
        actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.delete("/{organization_id}/scoring-schemes/{scheme_key}/models/{model_key}", response_model=ScoringSchemeOut)
def delete_org_scoring_model(
    organization_id: UUID, scheme_key: str, model_key: str, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Deletes an organisation model with its bands, defaults and enabled rows, wherever set."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.delete_model(
        db, organization_id, registered.scheme, model_key, project_id=None, actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.post("/{organization_id}/scoring-schemes/{scheme_key}/hidden-criteria", response_model=ScoringSchemeOut)
def hide_org_scoring_criterion(
    organization_id: UUID, scheme_key: str, payload: ScoringCriterionRef, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Hides a registered axis or model for the whole organisation (restorable; scores already stored are kept)."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.hide_criterion(
        db, organization_id, registered.scheme, payload.kind, payload.key, project_id=None, actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)


@router.delete("/{organization_id}/scoring-schemes/{scheme_key}/hidden-criteria", response_model=ScoringSchemeOut)
def restore_org_scoring_criterion(
    organization_id: UUID, scheme_key: str, kind: str, key: str, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Makes a criterion the organisation hid visible again."""
    registered = _load_scheme(db, current_user, organization_id, scheme_key, request)
    _require_scheme_admin(db, current_user, organization_id, registered)
    scoring_custom.restore_criterion(
        db, organization_id, registered.scheme, kind, key, project_id=None, actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, organization_id, registered)
