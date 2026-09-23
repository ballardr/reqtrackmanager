"""
Module: modules.compliance.router.version_requirements

A standard version's own hierarchical requirements (Phase 6):
create/list/get/update/delete/reorder, all `DRAFT`-version-only
(`_require_draft_version`) except `clarify_requirement` (Phase 24), a
narrow published-version, mandatory-note exception. Required actions
nested under a requirement are `version_required_actions.py`'s own
sibling bucket, split out separately since this one was still large
on its own.
"""

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import ComplianceRequirement
from app.modules.compliance.router._shared import (
    _get_requirement_or_404,
    _get_version_or_404,
    _require_draft_version,
    _require_standard_manage,
    _require_standard_manage_or_contribute,
    _require_view,
)
from app.modules.compliance.schemas import (
    ComplianceRequirementClarifyRequest,
    ComplianceRequirementCreate,
    ComplianceRequirementOut,
    ComplianceRequirementUpdate,
)
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.ordering import move_ordered

router = APIRouter(tags=["compliance-org-version-requirements"])


def _flatten_requirements_dfs(requirements: list[ComplianceRequirement]) -> list[ComplianceRequirement]:
    """Orders a version's requirements as a flat list in depth-first,
    parent-before-children order (each sibling group internally ordered by
    its own `sort_order`) — a flat list with `parent_requirement_id`
    populated, matching how this codebase already returns other
    parent-referencing hierarchies flatly rather than pre-nesting them
    server-side, while still presenting them in a sensible reading order
    rather than an arbitrary one."""
    children_by_parent: dict[uuid.UUID | None, list[ComplianceRequirement]] = {}
    for req in requirements:
        children_by_parent.setdefault(req.parent_requirement_id, []).append(req)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda r: r.sort_order)

    ordered: list[ComplianceRequirement] = []

    def _visit(parent_id: uuid.UUID | None) -> None:
        for req in children_by_parent.get(parent_id, []):
            ordered.append(req)
            _visit(req.id)

    _visit(None)
    return ordered


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements",
    response_model=ComplianceRequirementOut, status_code=status.HTTP_201_CREATED,
)
def create_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, payload: ComplianceRequirementCreate,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Creates a requirement under a version (§5). 409 if the version is no
    longer a draft. `sort_order` is always append-to-end within the
    requirement's sibling group (same `standard_version_id` AND same
    `parent_requirement_id` — top-level requirements and each parent's own
    children are each their own separately-ordered sibling group)."""
    standard, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    _require_draft_version(version)

    parent_id = payload.parent_requirement_id
    if parent_id is not None:
        parent = db.get(ComplianceRequirement, parent_id)
        if parent is None or parent.standard_version_id != version.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_requirement_id must be a requirement in this version.")

    count = len(
        db.scalars(
            select(ComplianceRequirement.id).where(
                ComplianceRequirement.standard_version_id == version.id,
                ComplianceRequirement.parent_requirement_id == parent_id,
            )
        ).all()
    )
    requirement = ComplianceRequirement(
        standard_version_id=version.id,
        parent_requirement_id=parent_id,
        reference=payload.reference,
        name=payload.name,
        description=payload.description,
        reasoning=payload.reasoning,
        sort_order=count,
        created_by=current_user.id,
    )
    db.add(requirement)
    db.flush()
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"name": requirement.name})
    db.commit()
    db.refresh(requirement)
    return requirement


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements", response_model=list[ComplianceRequirementOut]
)
def list_requirements(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a version's requirements as a flat, depth-first-ordered list
    with `parent_requirement_id` populated (§5's hierarchy) — see
    `_flatten_requirements_dfs`."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    requirements = db.scalars(
        select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
    ).all()
    return _flatten_requirements_dfs(list(requirements))


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    response_model=ComplianceRequirementOut,
)
def get_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single requirement."""
    _, _, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    return requirement


@router.patch(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    response_model=ComplianceRequirementOut,
)
def update_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    payload: ComplianceRequirementUpdate,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Updates a requirement's reference/name/description/reasoning. 409 if
    the owning version is no longer a draft. Does not support reparenting
    — see `schemas.py`'s module docstring."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    requirement.reference = payload.reference
    requirement.name = payload.name
    requirement.description = payload.description
    requirement.reasoning = payload.reasoning
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": requirement.name})
    db.commit()
    db.refresh(requirement)
    return requirement


@router.patch(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/clarify",
    response_model=ComplianceRequirementOut,
)
def clarify_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    payload: ComplianceRequirementClarifyRequest,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Applies a non-substantive correction/elaboration to a requirement
    already belonging to a **`PUBLISHED`** version (Phase 24) — a distinct,
    narrower sibling of `update_requirement` above, for exactly the one
    case that endpoint's own `_require_draft_version` gate forbids.

    This is a deliberate, explicitly-flagged revision of Phase 6's "a
    published version's requirements become immutable" rule
    (`_require_draft_version`, still governing every other requirement
    mutation unchanged), not a reopening of it — §4/§31 forbid *silently*/
    *unexpectedly* altering a published version's historical compliance
    assessment, not *every* change outright. What makes this endpoint
    satisfy the letter and spirit of that rule, rather than violate it:

    - **409** if the version is `DRAFT` (use the ordinary `update_requirement`
      endpoint instead — this endpoint's whole reason to exist is the one
      case that endpoint forbids) or `RETIRED` (retired stays fully frozen,
      per this module's Phase 4 design — a clarification is only ever
      offered on the version projects are actively being assessed against).
    - **400** if `clarification_note` is blank — mandatory, mirroring every
      other conditionally-mandatory-justification field in this module
      (Not Applicable, Non-Compliant, Rejection). There is no reliable way
      to detect "substantive" vs. "non-substantive" from a text diff alone
      (see `models.py`'s own Phase 24 notes) — the note is what makes this
      human-asserted distinction accountable and auditable, never silent.
    - Gated to `standards_manager`-or-override only (`_require_standard_manage`,
      composing with org-scoped `compliance_manager`/`OrgRole.ORG_ADMIN`/
      `is_server_admin`) — **not** `_require_standard_manage_or_contribute`:
      a `standards_contributor`'s role is deliberately scoped to
      draft-stage authoring (Phase 22's own definition); extending it to
      also touch published content would quietly widen that boundary.
    - Every call stamps `last_clarified_at`/`last_clarified_by`/
      `last_clarification_note` and increments `clarification_count`, and
      is logged via `services.audit.log_event` (action `"clarified"`,
      before/after values for every field this endpoint can change) —
      exactly the "explicit, restricted, and fully audited" shape that
      keeps this compliant with §4/§31 rather than in tension with them.

    Per this phase's own explicitly-flagged open question (docs/compliance-
    module-plan.md's Phase 24 spec): a clarification deliberately does
    **not** call `service.invalidate_approval_if_in_flight` — a
    clarification never changes the compliance obligation itself, so an
    already-in-flight approval is not invalidated by one, unlike an
    applicability or assessment change."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    if version.status != ComplianceStandardVersionStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a requirement on a published version can be clarified. Use the ordinary edit endpoint for a "
            "draft version; a retired version's requirements are fully frozen.",
        )
    if not payload.clarification_note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A clarification note is required.")

    before = {
        "reference": requirement.reference, "name": requirement.name,
        "description": requirement.description, "reasoning": requirement.reasoning,
    }
    requirement.reference = payload.reference
    requirement.name = payload.name
    requirement.description = payload.description
    requirement.reasoning = payload.reasoning
    requirement.clarification_count += 1
    requirement.last_clarified_at = datetime.now(UTC)
    requirement.last_clarified_by = current_user.id
    requirement.last_clarification_note = payload.clarification_note
    log_event(
        db, entity_type="compliance_requirement", entity_id=requirement.id, action="clarified",
        actor_id=current_user.id, organization_id=organization_id,
        detail={
            "before": before,
            "after": {
                "reference": requirement.reference, "name": requirement.name,
                "description": requirement.description, "reasoning": requirement.reasoning,
            },
            "clarification_note": payload.clarification_note,
        },
    )
    db.commit()
    db.refresh(requirement)
    return requirement


@router.delete(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Deletes a requirement (and, via the database's own `ON DELETE
    CASCADE`, its child requirements and their required actions — no
    manual cascade code needed, per Phase 5's schema). 409 if the owning
    version is no longer a draft."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": requirement.name})
    db.delete(requirement)
    db.commit()


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/move",
    response_model=ComplianceRequirementOut,
)
def move_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Moves a requirement up/down among its siblings — same
    `standard_version_id` AND same `parent_requirement_id`. 409 if the
    owning version is no longer a draft (see `_require_draft_version`'s
    docstring for why reordering is treated as a content mutation too)."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    result = move_ordered(
        db, ComplianceRequirement,
        [
            ComplianceRequirement.standard_version_id == version.id,
            ComplianceRequirement.parent_requirement_id == requirement.parent_requirement_id,
        ],
        requirement_id, payload.direction,
    )
    log_event(db, entity_type="compliance_requirement", entity_id=requirement_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result
