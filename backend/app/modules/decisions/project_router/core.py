"""
Module: modules.decisions.project_router.core

Decision CRUD: create/list/get/update/archive/unarchive. Also home for
`_decision_to_out` (imported by `workflow.py`, the only other bucket that
returns a `DecisionOut`). See the package's own `__init__.py` docstring
for the full router-split account.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import PrincipalType
from app.models.project import Project
from app.models.user import User
from app.modules.decisions import edits
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision
from app.modules.decisions.project_router._shared import _get_decision_in_project, _is_locked, _require_edit_role, _require_view
from app.modules.decisions.schemas import DecisionCreate, DecisionOut, DecisionUpdate
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.services.audit import log_event
from app.services.principals import principal_labels, principal_ref
from app.services.project_scope import ProjectScope
from app.services.tags import TagFilter

router = APIRouter(tags=["decisions-core"])


def _decisions_to_out(db: Session, decisions: Sequence[Decision]) -> list[DecisionOut]:
    """Builds the responses for many Decisions, resolving every owner and decision maker in one batch."""
    refs = [r for d in decisions for r in (principal_ref(d.owner_type, d.owner_id), principal_ref(d.decision_maker_type, d.decision_maker_id))]
    labels = principal_labels(db, refs)
    return [
        DecisionOut(
            id=d.id, project_id=d.project_id, unique_code=d.unique_code,
            title=d.title, decision_statement=d.decision_statement,
            decision_type_id=d.decision_type_id, status=d.status,
            decision_date=d.decision_date,
            decision_maker=labels[(d.decision_maker_type, d.decision_maker_id)] if d.decision_maker_id else None,
            owner=labels[(d.owner_type, d.owner_id)], context=d.context, options_considered=d.options_considered,
            chosen_option=d.chosen_option, rationale=d.rationale, consequences=d.consequences,
            assumptions=d.assumptions, constraints=d.constraints, creator_id=d.creator_id,
            is_archived=d.is_archived, archived_at=d.archived_at, archived_by=d.archived_by,
            is_locked=_is_locked(d), created_at=d.created_at, updated_at=d.updated_at,
        )
        for d in decisions
    ]


def _decision_to_out(db: Session, decision: Decision) -> DecisionOut:
    """Builds the response for one Decision (see `_decisions_to_out`)."""
    return _decisions_to_out(db, [decision])[0]


@router.post("", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
def create_decision(
    project_id: UUID, payload: DecisionCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a Decision in `DRAFT` status. Any project member with the
    module enabled may create one (module.py's "ordinary project members
    get View + Propose") — no `decision_owner` grant required."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    decision = edits.stage_decision(
        db, project, current_user, title=payload.title, decision_statement=payload.decision_statement,
        decision_type_id=payload.decision_type_id, decision_date=payload.decision_date,
        decision_maker=payload.decision_maker, owner=payload.owner,
        **payload.model_dump(include=set(edits.TEXT_FIELDS) - {"title", "decision_statement"}),
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.get("", response_model=list[DecisionOut])
def list_decisions(
    project_id: UUID,
    decision_type_id: UUID | None = None,
    status_filter: DecisionStatus | None = Query(None, alias="status"),
    owner_type: PrincipalType = PrincipalType.USER,
    owner_id: UUID | None = None,
    owner_mine: bool = False,
    decision_maker_type: PrincipalType = PrincipalType.USER,
    decision_maker_id: UUID | None = None,
    decision_maker_mine: bool = False,
    search: str | None = None,
    include_archived: bool = False,
    tag_filter: TagFilter = Depends(),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    project_scope: ProjectScope = Depends(),
):
    """Lists Decisions with filter-panel query params, mirroring
    `routers.requirements.list_requirements`'s own filtering style
    (component/category/status/search there -> decision_type/status/owner/
    decision_maker/search here). `owner_type`+`owner_id` (and the decision-maker pair) match one
    principal exactly; `owner_mine` / `decision_maker_mine` match the caller's own and their
    groups' (`services.principals.principal_filter_clause`). No `limit`/`offset` pagination yet — a
    project's Decision set is expected to be small relative to its
    Requirement set, and nothing asks for it; can be
    added later the same way `list_requirements` added it, without a
    breaking change. **Decided by: Agent** (scope containment)."""

    def rows_for(pid: UUID) -> list:
        """This endpoint's rows for one project of the scope."""
        decisions = edits.filter_decisions(
            db, current_user, pid, include_archived=include_archived, decision_type_id=decision_type_id,
            status_filter=status_filter, owner_type=owner_type, owner_id=owner_id, owner_mine=owner_mine,
            decision_maker_type=decision_maker_type, decision_maker_id=decision_maker_id,
            decision_maker_mine=decision_maker_mine,
        )
        decisions = edits.search_decisions(tag_filter.keep(db, pid, DECISION_ARTEFACT_TYPE, decisions), search)
        return _decisions_to_out(db, decisions)

    return project_scope.collect(
        db, db.get(Project, project_id), current_user.id, DECISION_ARTEFACT_TYPE, rows_for,
        gate=("decisions", None),
    )


@router.get("/{decision_id}", response_model=DecisionOut)
def get_decision(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _decision_to_out(db, _get_decision_in_project(db, project_id, decision_id))


@router.put("/{decision_id}", response_model=DecisionOut)
def update_decision(
    project_id: UUID, decision_id: UUID, payload: DecisionUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Direct edit of a Decision's content fields. 409s once the Decision
    is locked (`APPROVED`/`SUPERSEDED`) — see this module's own docstring."""
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    edits.stage_decision_update(db, project, decision, current_user, {name: getattr(payload, name) for name in DecisionUpdate.model_fields})
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.post("/{decision_id}/archive", response_model=DecisionOut)
def archive_decision(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Soft-deletes a Decision (never hard-deleted — §13/10.6's "remains available for historical purposes" applies to every
    non-current Decision, not just a rejected one). Not blocked by the
    content lock: archiving isn't a content edit, the same distinction
    `routers.requirements.delete_requirement` draws (no `is_locked` check
    there either)."""
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    if decision.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Decision is already archived.")
    decision.is_archived = True
    decision.archived_at = datetime.now(UTC)
    decision.archived_by = current_user.id
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.post("/{decision_id}/unarchive", response_model=DecisionOut)
def unarchive_decision(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Reverses `archive_decision` — mirrors `routers.requirements.
    restore_requirement`'s existing "every archive has an unarchive"
    convention. **Decided by: Agent** (small, symmetric addition; not
    separately called out in the task brief, but a codebase-wide pattern)."""
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    if not decision.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Decision is not archived.")
    decision.is_archived = False
    decision.archived_at = None
    decision.archived_by = None
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)
