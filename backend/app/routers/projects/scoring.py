"""
Module: routers.projects.scoring

Project-level endpoints of the generic scoring-matrix mechanism (Module 1
Phase 10): read a scheme's effective configuration for a project (levels
are the org's; default model and bands resolve project → nearest ancestor
→ org → system), and set or clear the project's own default-model and band
overrides.

Reads need project view-or-manage; writes need project-settings management
(project managers/administrators, org admins). Every route 404s unless the
scheme's module is enabled for the project. Writes are audit-logged by
`services.scoring`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project
from app.models.user import User
from app.modules.registry import RegisteredScoringScheme, is_module_enabled_for_project
from app.schemas.scoring import ScoringBandsIn, ScoringDefaultModelIn, ScoringSchemeOut
from app.services import scoring
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


@router.get("/{project_id}/scoring-schemes/{scheme_key}", response_model=ScoringSchemeOut)
def get_project_scoring_scheme(
    project_id: UUID, scheme_key: str,
    _user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns the scheme's effective configuration for this project."""
    registered = _load_scheme(db, project_id, scheme_key)
    project = db.get(Project, project_id)
    assert project is not None  # require_project_view_or_manage already 404s a missing project
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
    scoring.set_default_model(db, project.organization_id, registered.scheme, payload.model,
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
    scoring.set_bands(db, project.organization_id, registered.scheme, model_key, bands,
                      project_id=project.id, actor_id=current_user.id)
    db.commit()
    return scoring.build_scheme_config(db, project.organization_id, registered, project)
