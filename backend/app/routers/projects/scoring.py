"""
Module: routers.projects.scoring

Project-level endpoints of the generic scoring-matrix mechanism: read a scheme's effective configuration for a project (levels
are the org's; default model and bands resolve project → nearest ancestor
→ org → system), and set or clear the project's own default-model, band and
per-cell rating overrides, plus the project's set of enabled models and its thresholds for a derived axis.

Reads need project view-or-manage; writes need project-settings management
(project managers/administrators, org admins). Every route 404s unless the
scheme's module is enabled for the project. Writes are audit-logged by
`services.scoring`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project
from app.models.user import User
from app.modules.registry import RegisteredScoringScheme, is_module_enabled_for_project
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
    ScoringThresholdsIn,
)
from app.services import scoring, scoring_custom
from app.services.lookups import project_or_404
from app.services.rbac import require_project_manage, require_project_view_or_manage

router = APIRouter(tags=["projects-scoring"])


def _load_scheme(db: Session, project_id: UUID, scheme_key: str) -> RegisteredScoringScheme:
    """Returns the registered scheme if its module is enabled for the
    project.

    Raises:
        HTTPException: 404 for an unknown scheme or a disabled module.
    """
    registered = scoring.get_registered_scheme(scheme_key)
    if not is_module_enabled_for_project(db, project_id, registered.module_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return registered


def _effective(db: Session, project: Project, registered: RegisteredScoringScheme) -> RegisteredScoringScheme:
    """`registered` with the criteria this project sees: the organisation's and its own and its ancestors' custom
    axes and models, minus what is hidden."""
    return scoring_custom.effective_registered(db, project.organization_id, registered, project.id)


@router.get("/{project_id}/scoring-schemes/{scheme_key}", response_model=ScoringSchemeOut)
def get_project_scoring_scheme(
    project_id: UUID, scheme_key: str,
    _user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns the scheme's effective configuration for this project."""
    registered = _load_scheme(db, project_id, scheme_key)
    project = project_or_404(db, project_id)
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.put("/{project_id}/scoring-schemes/{scheme_key}/default-model", response_model=ScoringSchemeOut)
def set_project_default_scoring_model(
    project_id: UUID, scheme_key: str, payload: ScoringDefaultModelIn,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Overrides the project's default model, or clears the override
    (`null`) so it inherits from its ancestors/org."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring.set_default_model(db, project.organization_id, _effective(db, project, registered).scheme, payload.model,
                              project_id=project.id, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.put("/{project_id}/scoring-schemes/{scheme_key}/enabled-models", response_model=ScoringSchemeOut)
def set_project_enabled_scoring_models(
    project_id: UUID, scheme_key: str, payload: ScoringEnabledModelsIn,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Overrides the models the project shows side by side, or clears the override (`null`) so it inherits from
    its ancestors/org."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring.set_enabled_models(db, project.organization_id, _effective(db, project, registered).scheme, payload.models,
                               project_id=project.id, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.put("/{project_id}/scoring-schemes/{scheme_key}/models/{model_key}/bands", response_model=ScoringSchemeOut)
def set_project_scoring_bands(
    project_id: UUID, scheme_key: str, model_key: str, payload: ScoringBandsIn,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Overrides the project's rating bands for one model, or clears the
    override (`null`) so it inherits."""
    registered = _load_scheme(db, project_id, scheme_key)
    bands = None if payload.bands is None else [
        scoring.BandValue(label=b.label, min_score=b.min_score, tone=b.tone) for b in payload.bands
    ]
    scoring.set_bands(db, project.organization_id, _effective(db, project, registered).scheme, model_key, bands,
                      project_id=project.id, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.put("/{project_id}/scoring-schemes/{scheme_key}/axes/{axis_key}/thresholds", response_model=ScoringSchemeOut)
def set_project_axis_thresholds(
    project_id: UUID, scheme_key: str, axis_key: str, payload: ScoringThresholdsIn,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Overrides the project's thresholds for a derived axis (where each level starts, e.g. how much weighted demand
    reaches "Many"), or clears the override (`null`) so it inherits from its ancestors/org. Level names and weights
    stay the organisation's."""
    registered = _load_scheme(db, project_id, scheme_key)
    scheme = _effective(db, project, registered).scheme
    scoring.set_axis_thresholds(
        db, project.organization_id, scheme, scoring.list_levels(db, project.organization_id, scheme.key), axis_key,
        None if payload.thresholds is None else {lid: Decimal(str(v)) for lid, v in payload.thresholds.items()},
        project_id=project.id, actor_id=current_user.id,
    )
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.put("/{project_id}/scoring-schemes/{scheme_key}/models/{model_key}/cell-ratings", response_model=ScoringSchemeOut)
def set_project_scoring_cell_ratings(
    project_id: UUID, scheme_key: str, model_key: str, payload: ScoringCellRatingsIn,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Overrides the project's per-cell ratings for one two-axis model, or
    clears the override (`null`) so it inherits."""
    registered = _load_scheme(db, project_id, scheme_key)
    cells = None if payload.cells is None else [
        scoring.CellRatingValue(c.first_level_id, c.second_level_id, c.band_label) for c in payload.cells
    ]
    scoring.set_cell_ratings(db, project.organization_id, _effective(db, project, registered).scheme, model_key, cells,
                             project_id=project.id, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


# --- Project-defined axes and models, hidden criteria --------------------------------------------------------------


def _level_out(level) -> ScoringLevelOut:
    return ScoringLevelOut(
        id=level.id, name=level.name, description=level.description, weight=float(level.weight),
        threshold=None if level.threshold is None else float(level.threshold),
        org_threshold=None if level.threshold is None else float(level.threshold),
    )


def _model_axes(axes) -> list[scoring_custom.ModelAxisSpec]:
    return [
        scoring_custom.ModelAxisSpec(a.axis_key, a.role, a.exponent, a.importance, a.lower_is_better) for a in axes
    ]


def _config(db: Session, project: Project, registered: RegisteredScoringScheme):
    return scoring.build_scheme_config(db, project.organization_id, registered, project)


@router.post(
    "/{project_id}/scoring-schemes/{scheme_key}/axes", response_model=ScoringSchemeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_scoring_axis(
    project_id: UUID, scheme_key: str, payload: ScoringAxisCreate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Defines an axis (with its levels) for this project and the projects below it."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.create_axis(
        db, project.organization_id, registered.scheme, project_id=project.id, label=payload.label,
        description=payload.description,
        levels=[scoring_custom.LevelSpec(lvl.name, lvl.weight, lvl.description) for lvl in payload.levels],
        actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.patch("/{project_id}/scoring-schemes/{scheme_key}/axes/{axis_key}", response_model=ScoringSchemeOut)
def update_project_scoring_axis(
    project_id: UUID, scheme_key: str, axis_key: str, payload: ScoringAxisUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames or re-describes an axis this project defined."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.update_axis(
        db, project.organization_id, registered.scheme, axis_key, project_id=project.id, label=payload.label,
        description=payload.description, set_description="description" in payload.model_fields_set,
        actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.delete("/{project_id}/scoring-schemes/{scheme_key}/axes/{axis_key}", response_model=ScoringSchemeOut)
def delete_project_scoring_axis(
    project_id: UUID, scheme_key: str, axis_key: str, clear_scores: bool = Query(False),
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes an axis this project defined and its levels: 409 if a model uses it, or scores use it and
    `clear_scores` was not given."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.delete_axis(
        db, project.organization_id, registered, axis_key, project_id=project.id, clear_scores=clear_scores,
        actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.post(
    "/{project_id}/scoring-schemes/{scheme_key}/axes/{axis_key}/levels",
    response_model=ScoringLevelOut, status_code=status.HTTP_201_CREATED,
)
def create_project_scoring_level(
    project_id: UUID, scheme_key: str, axis_key: str, payload: ScoringLevelCreate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adds a level to an axis this project defined."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.require_axis_editable(db, project.organization_id, scheme_key, axis_key, project.id)
    level = scoring.create_level(
        db, project.organization_id, _effective(db, project, registered), axis_key, name=payload.name.strip(),
        weight=Decimal(str(payload.weight)), description=payload.description, actor_id=current_user.id,
        project_id=project.id,
    )
    db.commit()
    return _level_out(level)


@router.patch("/{project_id}/scoring-schemes/{scheme_key}/levels/{level_id}", response_model=ScoringLevelOut)
def update_project_scoring_level(
    project_id: UUID, scheme_key: str, level_id: UUID, payload: ScoringLevelUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames, re-weights or re-describes a level of an axis this project defined."""
    registered = _load_scheme(db, project_id, scheme_key)
    level = scoring.get_level(db, project.organization_id, scheme_key, level_id)
    scoring_custom.require_axis_editable(db, project.organization_id, scheme_key, level.axis_key, project.id)
    scoring.update_level(
        db, level, name=payload.name.strip() if payload.name else None,
        weight=Decimal(str(payload.weight)) if payload.weight is not None else None,
        description=payload.description, set_description="description" in payload.model_fields_set,
        actor_id=current_user.id, threshold=None if payload.threshold is None else Decimal(str(payload.threshold)),
        scheme=_effective(db, project, registered).scheme,
    )
    db.commit()
    return _level_out(level)


@router.delete("/{project_id}/scoring-schemes/{scheme_key}/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_scoring_level(
    project_id: UUID, scheme_key: str, level_id: UUID, reassign_to_id: UUID | None = Query(None),
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a level of an axis this project defined (409 below two levels, or in use with no
    `reassign_to_id` on the same axis)."""
    registered = _load_scheme(db, project_id, scheme_key)
    level = scoring.get_level(db, project.organization_id, scheme_key, level_id)
    scoring_custom.require_axis_editable(db, project.organization_id, scheme_key, level.axis_key, project.id)
    scoring.delete_level(
        db, level, _effective(db, project, registered), reassign_to_id=reassign_to_id, actor_id=current_user.id,
    )
    db.commit()


@router.post(
    "/{project_id}/scoring-schemes/{scheme_key}/models", response_model=ScoringSchemeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_scoring_model(
    project_id: UUID, scheme_key: str, payload: ScoringModelCreate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Defines a model (a product with divisors and exponents, or a weighted sum) for this project and the projects
    below it, from the axes it can see."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.create_model(
        db, project.organization_id, registered.scheme, project_id=project.id, label=payload.label,
        combination=payload.combination, axes=_model_axes(payload.axes), actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.patch("/{project_id}/scoring-schemes/{scheme_key}/models/{model_key}", response_model=ScoringSchemeOut)
def update_project_scoring_model(
    project_id: UUID, scheme_key: str, model_key: str, payload: ScoringModelUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a model this project defined and/or replaces how it combines its axes."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.update_model(
        db, project.organization_id, registered.scheme, model_key, project_id=project.id, label=payload.label,
        combination=payload.combination, axes=None if payload.axes is None else _model_axes(payload.axes),
        actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.delete("/{project_id}/scoring-schemes/{scheme_key}/models/{model_key}", response_model=ScoringSchemeOut)
def delete_project_scoring_model(
    project_id: UUID, scheme_key: str, model_key: str,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a model this project defined, with its bands, default and enabled rows."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.delete_model(
        db, project.organization_id, registered.scheme, model_key, project_id=project.id, actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.post("/{project_id}/scoring-schemes/{scheme_key}/hidden-criteria", response_model=ScoringSchemeOut)
def hide_project_scoring_criterion(
    project_id: UUID, scheme_key: str, payload: ScoringCriterionRef,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hides an axis or model this project inherits (restorable; scores already stored are kept)."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.hide_criterion(
        db, project.organization_id, registered.scheme, payload.kind, payload.key, project_id=project.id,
        actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)


@router.delete("/{project_id}/scoring-schemes/{scheme_key}/hidden-criteria", response_model=ScoringSchemeOut)
def restore_project_scoring_criterion(
    project_id: UUID, scheme_key: str, kind: str, key: str,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Makes a criterion this project hid visible again."""
    registered = _load_scheme(db, project_id, scheme_key)
    scoring_custom.restore_criterion(
        db, project.organization_id, registered.scheme, kind, key, project_id=project.id, actor_id=current_user.id,
    )
    db.commit()
    return _config(db, project, registered)
