"""
Module: modules.decisions.project_router

Decision Management's Phase 4 project-scoped API
(docs/plans/module-04-decision-management-plan.md Phase 4) — Decision CRUD,
lifecycle-transition actions, relationship endpoints (supersession,
Decision<->Requirement, Decision<->Decision), comments, file attachments,
and Decision Type management. Mounted at `/api/v1/projects/{project_id}/
modules/decisions`, mirroring `app.modules.compliance.project_router`'s
own structure and RBAC conventions.

RBAC shape (per `module.py`'s own role docstrings, Phase 0 addendum item 3):
- Every read endpoint is gated by `require_project_module_enabled
  ("decisions")` (`_require_view`) — any project member with the module
  enabled may view, mirroring `require_project_view`'s established
  404-not-403-when-disabled convention (`services.rbac.require_module_
  role`'s own docstring; also the "wrong role -> 403, disabled module ->
  404" distinction this router's own tests exercise).
- Creating a Decision, adding a comment, and lifecycle-*viewing* only need
  `_require_view` — module.py's role docstrings are explicit that
  "ordinary project members get View + Propose", so a Decision starts
  life, and can be proposed by anyone, without a `decision_owner` grant.
  **Decided by: Agent** (reading module.py's existing role docstrings
  literally, since Phase 4 is the first place this distinction has any
  code to attach to).
- Editing an existing Decision's content, archiving it, attaching/removing
  a direct file, and managing this project's Decision Types all require
  `decision_owner` (`_require_edit_role`, composed via `services.rbac.
  user_satisfies_module_role` so it also passes for `is_server_admin` and
  `ProjectRole.PROJECT_MANAGER`, exactly like `require_module_role`'s own
  composition) — these are the "management-level" actions `module.py`'s
  `decision_owner` role docstring names.
- `propose`/`submit-for-review` require **either** `decision_owner` **or**
  the Decision's own `owner_id` (`_require_owner_of_decision_or_role`) —
  the task brief's own text names this as an open call to make: a Decision
  Owner already manages every Decision in the project, but a plain member
  who owns *their own* Decision must also be able to move it through the
  pre-approval part of its lifecycle without needing a project-wide grant.
  **Decided by: Agent.**
- `approve`/`reject` require the flat `decision_approver` module role
  (`_require_approver`) — Phase 0 addendum item 3's own placeholder
  approval model, consumed here for the first time now that a router
  exists to gate.
- Relationship-creation endpoints (supersession, Decision<->Requirement,
  Decision<->Decision) require `decision_owner` (`_require_edit_role`) —
  mirroring `routers.requirements.create_link`'s own precedent of gating
  traceability-link creation behind the same role that gates other
  requirement edits (`_require_edit_role` there too), rather than opening
  it to any viewer. **Decided by: Agent.**

Content-field immutability once a Decision reaches `APPROVED`/`SUPERSEDED`
(source overview §13/10.6, deliberately deferred by Phase 2 — see
`service.py`'s own module docstring) is enforced here, at the router layer,
exactly where every other lock-after-approval check in this codebase lives
(`services.requirements.is_locked`'s call sites in `routers.requirements`/
`routers.change_requests`) — `update_decision` 409s once `_is_locked`
(status in `{APPROVED, SUPERSEDED}`) is true; status-transition and
relationship endpoints remain unaffected, since a Decision's own
relationships and lifecycle progression aren't "content" under this rule
any more than a `ReviewComment`/`ArtefactLink` is under C-G-12.

Every mutating endpoint (create/update/archive/unarchive, Decision Type
create/rename/reorder/delete, comment create/edit, file attach/detach)
calls `services.audit.log_event` before its single `db.commit()` — the
lifecycle-transition (`propose`/`submit-for-review`/`approve`/`reject`) and
relationship-creation (`supersede`/`link-requirement`/`link-decision`)
endpoints do **not** double-log: `service.py`'s own functions already call
`log_event` internally (Phase 2/3), so this router only commits after
calling them.

External dependencies: `app.services.rbac` (module-role/module-enabled
gating), `app.services.audit` (mutation logging), `app.services.files`
(file upload/delete, reused not reimplemented), `app.services.relationships`
(generic `ArtefactLink` queries), `app.services.sequences`
(`Decision.unique_code` generation), `app.services.definitions`
(Decision Type delete-with-reassignment), `app.services.ordering` (Decision
Type reordering) — every one reused as-is, none reimplemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import ArtefactType
from app.models.file import FileAsset
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision, DecisionComment, DecisionCommentFile, DecisionFile, DecisionTypeDefinition
from app.modules.decisions.schemas import (
    DecisionCommentCreate,
    DecisionCommentOut,
    DecisionCommentUpdate,
    DecisionCreate,
    DecisionDecisionLinkCreate,
    DecisionLinkOut,
    DecisionOut,
    DecisionRequirementLinkCreate,
    DecisionSupersessionCreate,
    DecisionTransitionRequest,
    DecisionTypeCreate,
    DecisionTypeOut,
    DecisionTypeUpdate,
    DecisionUpdate,
)
from app.modules.decisions.service import (
    DECISION_ARTEFACT_TYPE,
    approve_decision,
    create_decision_decision_link,
    create_decision_requirement_link,
    create_supersession,
    propose_decision,
    reject_decision,
    submit_decision_for_review,
)
from app.schemas.file import FileAssetOut
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.files import delete_file, upload_file
from app.services.ordering import move_ordered
from app.services.rbac import (
    get_effective_org_roles,
    require_module_role,
    require_project_module_enabled,
    user_satisfies_module_role,
)
from app.services.relationships import get_all_links
from app.services.requirements import get_current_version
from app.services.sequences import generate_unique_code

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/decisions", tags=["decisions"])

# Factories called once, at router-definition time — same convention as
# every other module router in this codebase (`modules.compliance.
# project_router`'s own comment on this).
_require_view = require_project_module_enabled("decisions")
_require_owner_role = require_module_role("decisions", "decision_owner")
_require_approver = require_module_role("decisions", "decision_approver")

# A Decision's content fields become immutable once it reaches either of
# these statuses (source overview §13/10.6) — see this module's own
# docstring.
_LOCKED_STATUSES = frozenset({DecisionStatus.APPROVED, DecisionStatus.SUPERSEDED})


def _is_locked(decision: Decision) -> bool:
    return decision.status in _LOCKED_STATUSES


def _decision_to_out(decision: Decision) -> DecisionOut:
    return DecisionOut(
        id=decision.id, project_id=decision.project_id, unique_code=decision.unique_code,
        title=decision.title, decision_statement=decision.decision_statement,
        decision_type_id=decision.decision_type_id, status=decision.status,
        decision_date=decision.decision_date, decision_maker_id=decision.decision_maker_id,
        owner_id=decision.owner_id, context=decision.context, options_considered=decision.options_considered,
        chosen_option=decision.chosen_option, rationale=decision.rationale, consequences=decision.consequences,
        assumptions=decision.assumptions, constraints=decision.constraints, creator_id=decision.creator_id,
        is_archived=decision.is_archived, archived_at=decision.archived_at, archived_by=decision.archived_by,
        is_locked=_is_locked(decision), created_at=decision.created_at, updated_at=decision.updated_at,
    )


def _get_decision_in_project(db: Session, project_id: UUID, decision_id: UUID) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found.")
    return decision


def _get_decision_type_in_project(db: Session, project_id: UUID, decision_type_id: UUID) -> DecisionTypeDefinition:
    decision_type = db.get(DecisionTypeDefinition, decision_type_id)
    if decision_type is None or decision_type.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid decision_type_id.")
    return decision_type


def _require_org_member_or_none(db: Session, project: Project, user_id: UUID | None) -> None:
    """400s unless `user_id` is `None` or an effective member of the
    project's own organisation — guards `owner_id`/`decision_maker_id`
    exactly like `modules.compliance.project_router._require_project_
    member_or_none` guards its own assignee/owner fields, for the same
    reason (a Decision Maker overseeing several projects need not hold a
    formal `ProjectRole` on this specific one)."""
    if user_id is None:
        return
    if not get_effective_org_roles(db, user_id, project.organization_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "owner_id/decision_maker_id must be a member of this project's organisation."
        )


def _user_satisfies_decision_owner(db: Session, current_user: User, project: Project) -> bool:
    return user_satisfies_module_role(
        db, current_user, "decisions", "decision_owner",
        organization_id=project.organization_id, project_id=project.id,
    )


def _require_edit_role(db: Session, current_user: User, project: Project) -> None:
    if not _user_satisfies_decision_owner(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Decision Owner (or project manager) may do this.")


def _require_owner_of_decision_or_role(db: Session, current_user: User, project: Project, decision: Decision) -> None:
    """Gate for `propose`/`submit-for-review` — see this module's own
    docstring for why this is a distinct, looser gate than
    `_require_edit_role`."""
    if current_user.id == decision.owner_id:
        return
    _require_edit_role(db, current_user, project)


def _apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls a Phase 2/3 `service.py` function, translating its `ValueError`
    (that layer's own "validation failed" convention) into an HTTP 409 —
    the translation every one of `service.py`'s own docstrings names as
    "Phase 4's router" responsibility."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- Decision Types (project-scoped definition table) ------------------------


@router.get("/decision-types", response_model=list[DecisionTypeOut])
def list_decision_types(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return db.scalars(
        select(DecisionTypeDefinition)
        .where(DecisionTypeDefinition.project_id == project_id)
        .order_by(DecisionTypeDefinition.sort_order)
    ).all()


@router.post("/decision-types", response_model=DecisionTypeOut, status_code=status.HTTP_201_CREATED)
def create_decision_type(
    project_id: UUID, payload: DecisionTypeCreate,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(DecisionTypeDefinition.id).where(
            DecisionTypeDefinition.project_id == project_id, DecisionTypeDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A decision type with this name already exists.")
    count = len(
        db.scalars(select(DecisionTypeDefinition.id).where(DecisionTypeDefinition.project_id == project_id)).all()
    )
    decision_type = DecisionTypeDefinition(project_id=project_id, name=payload.name, sort_order=count)
    db.add(decision_type)
    db.flush()
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"name": decision_type.name})
    db.commit()
    db.refresh(decision_type)
    return decision_type


@router.patch("/decision-types/{decision_type_id}", response_model=DecisionTypeOut)
def rename_decision_type(
    project_id: UUID, decision_type_id: UUID, payload: DecisionTypeUpdate,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    decision_type = _get_decision_type_in_project(db, project_id, decision_type_id)
    existing = db.scalar(
        select(DecisionTypeDefinition.id).where(
            DecisionTypeDefinition.project_id == project_id, DecisionTypeDefinition.name == payload.name,
            DecisionTypeDefinition.id != decision_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A decision type with this name already exists.")
    decision_type.name = payload.name
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type.id, action="renamed",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(decision_type)
    return decision_type


@router.post("/decision-types/{decision_type_id}/move", response_model=DecisionTypeOut)
def move_decision_type(
    project_id: UUID, decision_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    result = move_ordered(
        db, DecisionTypeDefinition, [DecisionTypeDefinition.project_id == project_id], decision_type_id, payload.direction
    )
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type_id, action="reordered",
              actor_id=current_user.id, project_id=project_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.delete("/decision-types/{decision_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_decision_type(
    project_id: UUID, decision_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    """Deletes a project's Decision Type, applying the shared rename/
    delete/reassign rules (`services.definitions`). Unlike `Decision
    Template` (org-scoped, no persistent FK from `Decision` — see Phase 0
    addendum item 6), `Decision.decision_type_id` **is** a real, non-null
    FK, so deleting an in-use type requires an explicit `reassign_to_id`
    (409 naming the count if omitted) — resolved independently of the
    template answer, per this phase's own build instructions, rather than
    copying it. `allow_empty=False`: unlike `ActionTypeDefinition`, Decision
    Types have no hierarchical-project fallback mechanism, so a project
    must always retain at least one. **Decided by: Agent.**"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    delete_definition_with_reassignment(
        db, definition_model=DecisionTypeDefinition, scope_column=DecisionTypeDefinition.project_id,
        scope_id=project_id, item_id=decision_type_id, reassign_to_id=reassign_to_id,
        referencing_model=Decision, referencing_fk_column=Decision.decision_type_id,
        referencing_fk_name="decision_type_id", entity_type="decision_type_definition", noun="decision type",
        plural_noun="decision(s)", reassign_verb="move",
        min_count_message="A project must always have at least one decision type.",
        actor_id=current_user.id, organization_id=project.organization_id, project_id=project_id,
    )
    db.commit()

# --- Decisions: CRUD ---------------------------------------------------------


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
    _get_decision_type_in_project(db, project_id, payload.decision_type_id)
    owner_id = payload.owner_id if payload.owner_id is not None else current_user.id
    _require_org_member_or_none(db, project, owner_id)
    _require_org_member_or_none(db, project, payload.decision_maker_id)

    unique_code = generate_unique_code(db, project, DECISION_ARTEFACT_TYPE, "DEC")
    decision = Decision(
        project_id=project_id, unique_code=unique_code, title=payload.title,
        decision_statement=payload.decision_statement, decision_type_id=payload.decision_type_id,
        status=DecisionStatus.DRAFT, decision_date=payload.decision_date,
        decision_maker_id=payload.decision_maker_id, owner_id=owner_id,
        context=payload.context, options_considered=payload.options_considered,
        chosen_option=payload.chosen_option, rationale=payload.rationale, consequences=payload.consequences,
        assumptions=payload.assumptions, constraints=payload.constraints, creator_id=current_user.id,
    )
    db.add(decision)
    db.flush()
    log_event(
        db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="created",
        actor_id=current_user.id, project_id=project_id, detail={"title": decision.title},
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.get("", response_model=list[DecisionOut])
def list_decisions(
    project_id: UUID,
    decision_type_id: UUID | None = None,
    status_filter: DecisionStatus | None = Query(None, alias="status"),
    owner_id: UUID | None = None,
    decision_maker_id: UUID | None = None,
    search: str | None = None,
    include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists Decisions with filter-panel query params, mirroring
    `routers.requirements.list_requirements`'s own filtering style
    (component/category/status/search there -> decision_type/status/owner/
    decision_maker/search here). No `limit`/`offset` pagination yet — a
    project's Decision set is expected to be small relative to its
    Requirement set, and nothing in this phase's scope asks for it; can be
    added later the same way `list_requirements` added it, without a
    breaking change. **Decided by: Agent** (scope containment)."""
    query = select(Decision).where(Decision.project_id == project_id)
    if not include_archived:
        query = query.where(Decision.is_archived.is_(False))
    if decision_type_id:
        query = query.where(Decision.decision_type_id == decision_type_id)
    if status_filter:
        query = query.where(Decision.status == status_filter)
    if owner_id:
        query = query.where(Decision.owner_id == owner_id)
    if decision_maker_id:
        query = query.where(Decision.decision_maker_id == decision_maker_id)
    decisions = db.scalars(query.order_by(Decision.created_at)).all()

    if search:
        needle = search.lower()
        decisions = [
            d for d in decisions
            if needle in d.title.lower() or needle in d.decision_statement.lower() or needle in d.unique_code.lower()
        ]
    return [_decision_to_out(d) for d in decisions]


@router.get("/{decision_id}", response_model=DecisionOut)
def get_decision(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _decision_to_out(_get_decision_in_project(db, project_id, decision_id))


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
    if _is_locked(decision):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Decision is approved or superseded; its content can no longer be edited in place.",
        )
    _get_decision_type_in_project(db, project_id, payload.decision_type_id)
    _require_org_member_or_none(db, project, payload.owner_id)
    _require_org_member_or_none(db, project, payload.decision_maker_id)

    decision.title = payload.title
    decision.decision_statement = payload.decision_statement
    decision.decision_type_id = payload.decision_type_id
    decision.decision_date = payload.decision_date
    decision.decision_maker_id = payload.decision_maker_id
    decision.owner_id = payload.owner_id
    decision.context = payload.context
    decision.options_considered = payload.options_considered
    decision.chosen_option = payload.chosen_option
    decision.rationale = payload.rationale
    decision.consequences = payload.consequences
    decision.assumptions = payload.assumptions
    decision.constraints = payload.constraints
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/archive", response_model=DecisionOut)
def archive_decision(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Soft-deletes a Decision (never hard-deleted — source overview
    §13/10.6's "remains available for historical purposes" applies to every
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
    return _decision_to_out(decision)


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
    return _decision_to_out(decision)


# --- Lifecycle transitions (Phase 2 service functions) -----------------------


@router.post("/{decision_id}/propose", response_model=DecisionOut)
def propose_decision_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(propose_decision, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/submit-for-review", response_model=DecisionOut)
def submit_decision_for_review_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(submit_decision_for_review, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/approve", response_model=DecisionOut)
def approve_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_approver), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    _apply_value_error_as_conflict(approve_decision, db, decision, current_user.id, comment=payload.comment)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/reject", response_model=DecisionOut)
def reject_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_approver), db: Session = Depends(get_db),
):
    """Rejection requires a comment — mirrors `record_review_outcome`'s
    mandatory-comment-on-`FAILED` rule (`routers.requirements.py`) and
    `reject_requirement`'s mandatory `decision_note`
    (`modules.compliance.project_router`): a rejection must never appear
    with no indication of why."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to reject a Decision.")
    decision = _get_decision_in_project(db, project_id, decision_id)
    _apply_value_error_as_conflict(reject_decision, db, decision, current_user.id, comment=payload.comment)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


# --- Relationships (Phase 3 service functions) -------------------------------


def _resolve_other_artefact_display(db: Session, other_type: str, other_id: UUID) -> tuple[str | None, str | None]:
    """Best-effort resolution of an artefact's own display code/name for
    `DecisionLinkOut` — see that schema's own docstring."""
    if other_type == DECISION_ARTEFACT_TYPE:
        other_decision = db.get(Decision, other_id)
        if other_decision is not None:
            return other_decision.unique_code, other_decision.title
    elif other_type == ArtefactType.REQUIREMENT.value:
        other_requirement = db.get(Requirement, other_id)
        if other_requirement is not None:
            version = get_current_version(db, other_requirement.id)
            return other_requirement.unique_code, version.name
    return None, None


def _link_to_out(db: Session, link, decision_id: UUID) -> DecisionLinkOut:
    is_outgoing = link.source_type == DECISION_ARTEFACT_TYPE and link.source_id == decision_id
    other_type = link.target_type if is_outgoing else link.source_type
    other_id = link.target_id if is_outgoing else link.source_id
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id) if link.link_type_id else None
    if link_type is not None:
        display_name = link_type.forward_name if is_outgoing else link_type.reverse_name
    else:
        display_name = ""
    other_code, other_name = _resolve_other_artefact_display(db, other_type, other_id)
    return DecisionLinkOut(
        id=link.id, source_type=link.source_type, source_id=link.source_id,
        target_type=link.target_type, target_id=link.target_id, link_type_id=link.link_type_id,
        direction="outgoing" if is_outgoing else "incoming", display_name=display_name,
        other_type=other_type, other_id=other_id,
        other_display_code=other_code, other_display_name=other_name,
        created_by=link.created_by, created_at=link.created_at,
    )


@router.get("/{decision_id}/relationships", response_model=list[DecisionLinkOut])
def list_decision_relationships(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every relationship touching this Decision, in either
    direction — `services.relationships.get_all_links`, the generic
    equivalent of `routers.requirements.list_links`."""
    decision = _get_decision_in_project(db, project_id, decision_id)
    links = get_all_links(db, DECISION_ARTEFACT_TYPE, decision.id)
    return [_link_to_out(db, link, decision.id) for link in links]


@router.post("/{decision_id}/supersessions", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED)
def create_decision_supersession(
    project_id: UUID, decision_id: UUID, payload: DecisionSupersessionCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`decision_id` (the new Decision) supersedes `payload.
    old_decision_id`. Gated on `decision_owner`, mirroring `routers.
    requirements.create_link`'s own precedent of requiring an edit-capable
    role to create a traceability relationship, not just view access."""
    project = db.get(Project, project_id)
    new_decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    old_decision = _get_decision_in_project(db, project_id, payload.old_decision_id)
    link = _apply_value_error_as_conflict(
        create_supersession, db, new_decision=new_decision, old_decision=old_decision, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, new_decision.id)


@router.post(
    "/{decision_id}/requirement-links", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_decision_requirement_link_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionRequirementLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    requirement = db.get(Requirement, payload.requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    link = _apply_value_error_as_conflict(
        create_decision_requirement_link, db, decision=decision, requirement=requirement,
        kind=payload.kind, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, decision.id)


@router.post(
    "/{decision_id}/decision-links", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_decision_decision_link_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionDecisionLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    source_decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    target_decision = _get_decision_in_project(db, project_id, payload.target_decision_id)
    link = _apply_value_error_as_conflict(
        create_decision_decision_link, db, source_decision=source_decision, target_decision=target_decision,
        kind=payload.kind, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, source_decision.id)


# --- Comments ----------------------------------------------------------------


def _comment_to_out(db: Session, comment: DecisionComment) -> DecisionCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(DecisionCommentFile, DecisionCommentFile.file_id == FileAsset.id)
        .where(DecisionCommentFile.comment_id == comment.id)
    ).all()
    return DecisionCommentOut(
        id=comment.id, decision_id=comment.decision_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post("/{decision_id}/comments", response_model=DecisionCommentOut, status_code=status.HTTP_201_CREATED)
def add_decision_comment(
    project_id: UUID, decision_id: UUID, payload: DecisionCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    comment = DecisionComment(decision_id=decision.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.get("/{decision_id}/comments", response_model=list[DecisionCommentOut])
def list_decision_comments(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    comments = db.scalars(
        select(DecisionComment).where(DecisionComment.decision_id == decision.id).order_by(DecisionComment.created_at)
    ).all()
    return [_comment_to_out(db, c) for c in comments]


@router.patch("/{decision_id}/comments/{comment_id}", response_model=DecisionCommentOut)
def edit_decision_comment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, payload: DecisionCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only — mirrors `routers.requirements.edit_comment`'s
    identical rule (not even a Decision Owner may edit someone else's
    words)."""
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.post(
    "/{decision_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED,
)
async def upload_decision_comment_attachment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Mirrors `routers.requirements.upload_comment_attachment`'s pattern
    exactly: author-only, never subject to the Decision's own content lock
    (a comment thread isn't governed content, same reasoning as that
    endpoint's own docstring)."""
    project = db.get(Project, project_id)
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(DecisionCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{decision_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_decision_comment_attachment(
    project_id: UUID, decision_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only, same reasoning as `upload_decision_comment_attachment`.
    Always a direct upload (never a shared org resource, unlike a Decision's
    own direct attachments), so the underlying `FileAsset` is deleted
    outright — mirrors `routers.requirements.remove_comment_attachment`."""
    _get_decision_in_project(db, project_id, decision_id)
    comment = db.get(DecisionComment, comment_id)
    if comment is None or comment.decision_id != decision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(DecisionCommentFile).where(DecisionCommentFile.comment_id == comment.id, DecisionCommentFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        # Unlike `routers.requirements.remove_comment_attachment` (which
        # plain-deletes the `FileAsset` row without freeing its storage
        # backend bytes), this uses `delete_file` so the underlying object
        # is actually removed, not just its metadata row — a same-shape
        # improvement kept local to this module rather than editing that
        # unrelated core file as part of this phase. **Decided by: Agent.**
        delete_file(db, asset)
    db.commit()


# --- File attachments ---------------------------------------------------------


@router.post("/{decision_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_decision_file(
    project_id: UUID, decision_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Mirrors `routers.requirements.upload_requirement_attachment`'s
    pattern exactly: `decision_owner`-gated, and rejected once the
    Decision is locked."""
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    if _is_locked(decision):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Decision is approved or superseded; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(DecisionFile(decision_id=decision.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{decision_id}/files", response_model=list[FileAssetOut])
def list_decision_files(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    return db.scalars(
        select(FileAsset).join(DecisionFile, DecisionFile.file_id == FileAsset.id).where(DecisionFile.decision_id == decision.id)
    ).all()


@router.delete("/{decision_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_decision_file(
    project_id: UUID, decision_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    link = db.scalar(select(DecisionFile).where(DecisionFile.decision_id == decision.id, DecisionFile.file_id == file_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Decision.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


