"""
Module: modules.compliance.router.standard_versions

A standard's own versions (Phase 6): create (optionally cloning
another version's full requirement tree), list, get, update the
editable summary (Phase 24), and the one-way publish/retire lifecycle
(§4) — no endpoint here ever moves a version backwards or deletes one.
"""

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import NotificationType
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import (
    ComplianceRequiredAction,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
)
from app.modules.compliance.router._shared import (
    _get_standard_or_404,
    _get_version_or_404,
    _require_standard_manage,
    _require_standard_manage_or_contribute,
    _require_view,
)
from app.modules.compliance.schemas import ComplianceStandardVersionCreate, ComplianceStandardVersionOut, ComplianceStandardVersionUpdate
from app.modules.compliance.service import get_effective_compliance_officers
from app.services import notifications
from app.services.audit import log_event

router = APIRouter(tags=["compliance-org-standard-versions"])


def _clone_requirement_tree(
    db: Session, *, source_version_id: UUID, new_version_id: UUID, creator_id: UUID
) -> None:
    """Deep-copies `source_version_id`'s full `ComplianceRequirement` tree
    (preserving parent/child structure via an old-id -> new-id remap) and
    each requirement's `ComplianceRequiredAction`s into `new_version_id`.

    Used by `create_standard_version` when `clone_from_version_id` is given
    — see that endpoint's docstring for why this exists. Processes
    requirements breadth-first from the roots down (`_clone_level`,
    recursive), so a child is never cloned before its own remapped parent
    id exists to point at.

    Also stamps every new requirement's `cloned_from_requirement_id` at the
    source requirement's own id (Phase 11, §27) — the durable lineage link
    `service.py::diff_standard_versions` walks to tell an unchanged/
    modified requirement apart from a genuinely added one; see `models.py`'s
    own Phase 11 notes for why this column was added and `models.py`'s
    docstring on the pre-existing in-memory old-id -> new-id remap this
    function already performed for parent/child structure, which persisting
    `cloned_from_requirement_id` piggybacks on directly."""
    source_requirements = db.scalars(
        select(ComplianceRequirement)
        .where(ComplianceRequirement.standard_version_id == source_version_id)
        .order_by(ComplianceRequirement.sort_order)
    ).all()
    children_by_parent: dict[uuid.UUID | None, list[ComplianceRequirement]] = {}
    for req in source_requirements:
        children_by_parent.setdefault(req.parent_requirement_id, []).append(req)

    def _clone_level(parent_old_id: uuid.UUID | None, parent_new_id: uuid.UUID | None) -> None:
        for old_req in children_by_parent.get(parent_old_id, []):
            new_req = ComplianceRequirement(
                standard_version_id=new_version_id,
                parent_requirement_id=parent_new_id,
                cloned_from_requirement_id=old_req.id,
                reference=old_req.reference,
                name=old_req.name,
                description=old_req.description,
                reasoning=old_req.reasoning,
                sort_order=old_req.sort_order,
                created_by=creator_id,
            )
            db.add(new_req)
            db.flush()

            old_actions = db.scalars(
                select(ComplianceRequiredAction)
                .where(ComplianceRequiredAction.requirement_id == old_req.id)
                .order_by(ComplianceRequiredAction.sort_order)
            ).all()
            for old_action in old_actions:
                db.add(
                    ComplianceRequiredAction(
                        requirement_id=new_req.id,
                        action_type_id=old_action.action_type_id,
                        name=old_action.name,
                        description=old_action.description,
                        is_mandatory=old_action.is_mandatory,
                        sort_order=old_action.sort_order,
                        created_by=creator_id,
                    )
                )

            _clone_level(old_req.id, new_req.id)

    _clone_level(None, None)


@router.post(
    "/standards/{standard_id}/versions", response_model=ComplianceStandardVersionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_standard_version(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardVersionCreate,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Creates a new (always `DRAFT`) version of a standard (§4).
    `version_number` is always the next sequential number for this
    standard — never caller-supplied.

    `clone_from_version_id`, when given, deep-copies that version's full
    requirement tree and required actions into the new draft version. This
    is a deliberate Phase 6 design decision beyond what the plan's own spec
    text spells out: §4 requires that "changes to a standard should result
    in a new version rather than modifying requirements historical
    assessments depend upon," but without a way to version existing content
    forward, every new version would have to be rebuilt from scratch,
    defeating the point of versioning an evolving standard rather than
    starting over each time."""
    standard = _get_standard_or_404(db, organization_id, standard_id)

    last_version_number = db.scalar(
        select(ComplianceStandardVersion.version_number)
        .where(ComplianceStandardVersion.standard_id == standard.id)
        .order_by(ComplianceStandardVersion.version_number.desc())
        .limit(1)
    )
    next_version_number = (last_version_number or 0) + 1

    version = ComplianceStandardVersion(
        standard_id=standard.id,
        version_number=next_version_number,
        version_label=payload.version_label,
        effective_date=payload.effective_date,
        change_note=payload.change_note,
        created_by=current_user.id,
    )
    db.add(version)
    db.flush()

    if payload.clone_from_version_id is not None:
        _, source_version = _get_version_or_404(db, organization_id, standard_id, payload.clone_from_version_id)
        _clone_requirement_tree(
            db, source_version_id=source_version.id, new_version_id=version.id, creator_id=current_user.id
        )

    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"version_label": version.version_label, "cloned_from": str(payload.clone_from_version_id)
                      if payload.clone_from_version_id else None})
    db.commit()
    db.refresh(version)
    return version


@router.get("/standards/{standard_id}/versions", response_model=list[ComplianceStandardVersionOut])
def list_standard_versions(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a standard's versions, ordered by `version_number` — every
    version, published or retired, remains listed (Phase 5's "never
    superseded/deleted" design)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    return db.scalars(
        select(ComplianceStandardVersion)
        .where(ComplianceStandardVersion.standard_id == standard.id)
        .order_by(ComplianceStandardVersion.version_number)
    ).all()


@router.get("/standards/{standard_id}/versions/{version_id}", response_model=ComplianceStandardVersionOut)
def get_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single standard version."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    return version


@router.patch("/standards/{standard_id}/versions/{version_id}", response_model=ComplianceStandardVersionOut)
def update_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID, payload: ComplianceStandardVersionUpdate,
    request: Request,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Updates a version's own `summary` (Phase 24) — the version's
    *current* standing, distinct from `change_note`. Unlike every other
    field on this row, editable at **any** lifecycle stage (`DRAFT`/
    `PUBLISHED`/`RETIRED` alike, never `_require_draft_version`-gated) —
    the motivating example is marking an already-retired version's summary
    to note it's deprecated (see `models.py`'s own Phase 24 notes).

    RBAC is stage-dependent: a `standards_contributor` may call this while
    the version is still `DRAFT` (this is the ordinary contributor-level
    field-write `_require_standard_manage_or_contribute` already permits
    everywhere else), but once the version is `PUBLISHED`/`RETIRED`, only
    `standards_manager`-or-override may — checked explicitly here rather
    than by depending on the stricter gate outright, since a contributor
    must still pass for the `DRAFT` case."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    if version.status != ComplianceStandardVersionStatus.DRAFT:
        current_user = _require_standard_manage(request=request, current_user=current_user, db=db)
    version.summary = payload.summary
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"summary": version.summary})
    db.commit()
    db.refresh(version)
    return version


def _notify_projects_of_standard_update(
    db: Session, standard: ComplianceStandard, *, new_version: ComplianceStandardVersion, actor_id: UUID
) -> None:
    """Notifies the compliance officers of every project currently (non-
    archived-ly) assigned to an *older* version of `standard` that a new
    version has been published (§18's "A compliance standard being updated
    where affected projects require review") — those projects stay pinned
    to their own assigned version (Phase 7's own design; publishing never
    moves an existing assignment), so this is purely informational: a
    project's Compliance Manager decides separately whether/when to
    actually migrate (Phase 11)."""
    other_version_ids = set(
        db.scalars(
            select(ComplianceStandardVersion.id).where(
                ComplianceStandardVersion.standard_id == standard.id,
                ComplianceStandardVersion.id != new_version.id,
            )
        ).all()
    )
    if not other_version_ids:
        return
    affected_assignments = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.standard_version_id.in_(other_version_ids), ProjectCompliance.is_archived.is_(False)
        )
    ).all()
    for assignment in affected_assignments:
        for recipient_id in get_effective_compliance_officers(db, assignment.project_id):
            recipient = db.get(User, recipient_id)
            if recipient is None:
                continue
            notifications.notify(
                db, recipient, notification_type=NotificationType.COMPLIANCE_STANDARD_UPDATE_REVIEW_NEEDED,
                title=f"New version published: {standard.name}",
                body=f'"{standard.name}" has a new version ({new_version.version_label}); '
                     "this project's assignment may need review.",
                project_id=assignment.project_id, entity_type="compliance_standard", entity_id=str(standard.id),
                actor_id=actor_id,
            )


@router.post(
    "/standards/{standard_id}/versions/{version_id}/publish", response_model=ComplianceStandardVersionOut
)
def publish_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Publishes a `DRAFT` version (§4) — after this, its requirements and
    required actions become immutable (`_require_draft_version`). 409 if
    the version isn't currently `DRAFT` (already published or retired)."""
    standard, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    if version.status != ComplianceStandardVersionStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft version can be published.")
    version.status = ComplianceStandardVersionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    version.published_by = current_user.id
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="published",
              actor_id=current_user.id, organization_id=organization_id)
    _notify_projects_of_standard_update(db, standard, new_version=version, actor_id=current_user.id)
    db.commit()
    db.refresh(version)
    return version


@router.post(
    "/standards/{standard_id}/versions/{version_id}/retire", response_model=ComplianceStandardVersionOut
)
def retire_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Retires a version — from either `DRAFT` or `PUBLISHED` (§4). 409 if
    already retired. A retired version is never deleted and stays
    addressable indefinitely (Phase 5's own design)."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    if version.status == ComplianceStandardVersionStatus.RETIRED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This version is already retired.")
    version.status = ComplianceStandardVersionStatus.RETIRED
    version.retired_at = datetime.now(UTC)
    version.retired_by = current_user.id
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="retired",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(version)
    return version
