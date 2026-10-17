"""
Module: services.change_request_links

Links proposed on a change request, validated now and merged on approval


Responsibilities:
- Check a proposed link (`check_proposed_link`) with the same rules as creating a link
  directly, but from a requirement that may not exist yet and attributed to the request's
  creator: the far end is a record the actor can view, the link type is usable and not
  hidden, the pair is allowed by the type's restriction, both ends' artefact-type rules
  and the nesting scope, the far end's project is a related one, and (for an existing
  requirement) the link is not a duplicate.
- Describe a request's proposed links (`describe_links`) and what approving would merge
  (`build_preview`): every link re-validated at read time, never trusted from creation.
- Decide and apply the outcome on approval (`resolve_links`): merge the chosen links,
  record `merged` / `declined` / `skipped` (with the reason) on each, and audit every
  created link in both projects with `via: change_request`.

Design decisions:
- A problem is a value (`ProposedLinkProblem`), not an HTTP error, so one check serves
  creation (becomes a 400), the preview (becomes a disabled row with its reason) and
  approval (becomes a 409 with a fresh preview, or a skipped link).
- Two actors are checked on approval: the **creator** (the link is attributed to them, so
  they must still be allowed to create it) and the **approver** (must hold `view` on the
  far end in its own project, so approving can never create a link to a record the
  approver cannot read). The approver's authority to change the requirement is the
  approval itself, so `link` / `manage` is not asked of them.
- A far end the actor cannot see, an unrelated project and a missing record all read the
  same ("not found"), so a probe learns nothing.
- Approval replays an already-validated link, so creation passes `enforce_rules=False`.

Dependencies: `services.link_authoring` (visibility, gates, audit, duplicates),
`services.link_graph` (`ArtefactResolver`), `services.link_nesting`, `services.link_types`,
`services.relationships`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ChangeRequestProposedLink, ChangeRequestVersion
from app.models.enums import ArtefactType, ProposedLinkOutcome
from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import (
    ArtefactSummary,
    get_all_registered_artefact_types,
    get_artefact_type_label,
)
from app.schemas.artefact_links import LinkOrientation
from app.schemas.change_request import ProposedLinkOut, ProposedLinkPreviewRow
from app.services.link_authoring import audit_link, existing_duplicate, gate_requirement
from app.services.link_graph import ArtefactResolver
from app.services.link_nesting import related_projects
from app.services.link_type_scope import UNAVAILABLE_MESSAGE, assert_link_type_usable
from app.services.link_types import LinkRuleError, validate_link_allowed
from app.services.relationships import create_link

_REQUIREMENT = ArtefactType.REQUIREMENT.value

NOT_FOUND = "The linked record was not found."
ALREADY_LINKED = "These records are already linked this way."
ROLE_CHANGED = "The person who proposed this can no longer link requirements."
APPROVER_CANNOT_VIEW = "You cannot view the linked record, so you cannot merge this link."


class ProposedLinkProblem(Exception):
    """A proposed link cannot be created (`message` says why).

    Attributes:
        message: A reason safe to show to the actor it was computed for.
        already_linked: True for the harmless duplicate case, which the preview marks
            separately and approval skips rather than treating as a failure.
    """

    def __init__(self, message: str, *, already_linked: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.already_linked = already_linked


@dataclass(frozen=True)
class CheckedLink:
    """A proposed link that passed every check, ready to create."""

    link_type: RequirementLinkTypeDefinition
    outgoing: bool
    other_type: str
    other: ArtefactSummary
    other_project: Project


def _locate_other(
    db: Session, project: Project, actor_id: uuid.UUID, other_type: str, other_id: uuid.UUID,
    other_project_id: uuid.UUID | None,
) -> tuple[Project, ArtefactSummary]:
    """The far end's project and summary as `actor_id` sees them, else a "not found" problem."""
    if other_type not in get_all_registered_artefact_types():
        raise ProposedLinkProblem(NOT_FOUND)
    other_project = project
    if other_project_id is not None and other_project_id != project.id:
        related, _ = related_projects(db, project, actor_id)
        found = next((entry.project for entry in related if entry.project.id == other_project_id), None)
        if found is None:
            raise ProposedLinkProblem(NOT_FOUND)
        other_project = found
    resolver = ArtefactResolver(db, other_project, actor_id)
    resolver.resolve({other_type: {other_id}})
    other = resolver.visible((other_type, other_id))
    if other is None or (other_project is not project and other.project_id != other_project.id):
        raise ProposedLinkProblem(NOT_FOUND)
    return other_project, other


def check_proposed_link(
    db: Session,
    *,
    project: Project,
    requirement_id: uuid.UUID | None,
    creator_id: uuid.UUID,
    link_type_id: uuid.UUID | None,
    outgoing: bool,
    other_type: str,
    other_id: uuid.UUID,
    other_project_id: uuid.UUID | None,
    approver_id: uuid.UUID | None = None,
) -> CheckedLink:
    """Checks that the creator could create this link now, and that the approver may read its far end.

    Args:
        db: Active session (read only).
        project: The change request's project.
        requirement_id: The requirement being linked; `None` for a `new_requirement`
            request, which skips the self-link and duplicate checks.
        creator_id: Whose link it will be (the request's creator): must hold `link` or
            `manage` on requirements and be able to view the far end.
        link_type_id: The proposed link type (`None` when the type has been deleted).
        outgoing: True when the requirement is the link's source.
        other_type / other_id / other_project_id: The far end and its project (`None` = `project`).
        approver_id: Also require this user to be able to view the far end (set when previewing
            or approving).

    Returns:
        The validated link.

    Raises:
        ProposedLinkProblem: The link cannot be created; the message says why.
    """
    page_resolver = ArtefactResolver(db, project, creator_id)
    if not page_resolver.can_propose_link(_REQUIREMENT):
        raise ProposedLinkProblem(ROLE_CHANGED)
    other_project, other = _locate_other(db, project, creator_id, other_type, other_id, other_project_id)
    if approver_id is not None:
        try:
            _locate_other(db, project, approver_id, other_type, other_id, other_project_id)
        except ProposedLinkProblem as exc:
            raise ProposedLinkProblem(APPROVER_CANNOT_VIEW) from exc
    if other_project is not project and other_project.is_archived:
        raise ProposedLinkProblem("That project is archived, so it cannot take new links.")
    if requirement_id is not None and (other_type, other_id) == (_REQUIREMENT, requirement_id):
        raise ProposedLinkProblem("A record cannot be linked to itself.")
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id) if link_type_id is not None else None
    if link_type is None:
        raise ProposedLinkProblem(UNAVAILABLE_MESSAGE)
    try:
        assert_link_type_usable(db, project, link_type, enforce_offered=True)
    except LinkRuleError as exc:
        raise ProposedLinkProblem(str(exc)) from exc
    if link_type.dedicated_endpoint:
        raise ProposedLinkProblem(f'"{link_type.forward_name}" links are made with their own action, not as a general link.')
    source_type, target_type = (_REQUIREMENT, other_type) if outgoing else (other_type, _REQUIREMENT)
    cross = other_project is not project
    source_project_id = project.id if outgoing else other_project.id
    target_project_id = other_project.id if outgoing else project.id
    try:
        validate_link_allowed(
            db, link_type=link_type, source_type=source_type, target_type=target_type, project_id=project.id,
            enforce_offered=True,
            source_project_id=source_project_id if cross else None, target_project_id=target_project_id if cross else None,
        )
    except LinkRuleError as exc:
        raise ProposedLinkProblem(str(exc)) from exc
    if cross:
        # The far end's own project may require its approved requirements to change via a request.
        try:
            gate_requirement(db, other_project, other_type, other_id, "added")
        except HTTPException as exc:
            raise ProposedLinkProblem(str(exc.detail)) from exc
    if requirement_id is not None:
        source_id, target_id = (requirement_id, other_id) if outgoing else (other_id, requirement_id)
        if existing_duplicate(
            db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
            link_type=link_type,
        ):
            raise ProposedLinkProblem(ALREADY_LINKED, already_linked=True)
    return CheckedLink(link_type=link_type, outgoing=outgoing, other_type=other_type, other=other, other_project=other_project)


def _check_row(
    db: Session, project: Project, cr: ChangeRequest, row: ChangeRequestProposedLink, approver_id: uuid.UUID | None
) -> CheckedLink:
    """`check_proposed_link` for a stored row, as the request's creator (and `approver_id`)."""
    return check_proposed_link(
        db, project=project, requirement_id=cr.requirement_id, creator_id=cr.creator_id, link_type_id=row.link_type_id,
        outgoing=row.direction == LinkOrientation.OUTGOING.value, other_type=row.other_type, other_id=row.other_id,
        other_project_id=row.other_project_id, approver_id=approver_id,
    )


def describe_links(
    db: Session, project: Project, viewer_id: uuid.UUID, rows: list[ChangeRequestProposedLink]
) -> list[ProposedLinkOut]:
    """Proposed links as `viewer_id` may see them: the far end's label only when visible to them."""
    if not rows:
        return []
    resolvers: dict[uuid.UUID, ArtefactResolver] = {}
    related, _ = related_projects(db, project, viewer_id)
    project_by_id = {entry.project.id: entry.project for entry in related}
    project_by_id[project.id] = project

    def resolver_for(project_id: uuid.UUID) -> ArtefactResolver | None:
        if project_id not in project_by_id:
            return None
        if project_id not in resolvers:
            resolvers[project_id] = ArtefactResolver(db, project_by_id[project_id], viewer_id)
        return resolvers[project_id]

    type_ids = {r.link_type_id for r in rows if r.link_type_id}
    link_types = {
        t.id: t for t in db.scalars(
            select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.id.in_(type_ids))
        )
    } if type_ids else {}
    out: list[ProposedLinkOut] = []
    for row in rows:
        far_project_id = row.other_project_id or project.id
        resolver = resolver_for(far_project_id)
        label: str | None = None
        project_name: str | None = None
        if resolver is not None and row.other_type in get_all_registered_artefact_types():
            resolver.resolve({row.other_type: {row.other_id}})
            summary = resolver.visible((row.other_type, row.other_id))
            if summary is not None and (far_project_id == project.id or summary.project_id == far_project_id):
                label = summary.label
                project_name = project_by_id[far_project_id].name if row.other_project_id else None
        link_type = link_types.get(row.link_type_id) if row.link_type_id else None
        outgoing = row.direction == LinkOrientation.OUTGOING.value
        phrase = None
        if link_type is not None:
            phrase = link_type.forward_name if outgoing else link_type.reverse_name
        seen = label is not None
        out.append(ProposedLinkOut(
            id=row.id, link_type_id=row.link_type_id, phrase=phrase, direction=LinkOrientation(row.direction),
            other_type=row.other_type, other_type_label=get_artefact_type_label(row.other_type),
            other_id=row.other_id if seen else None, other_label=label,
            other_project_id=row.other_project_id if seen else None, other_project_name=project_name,
            outcome=row.outcome, outcome_reason=row.outcome_reason,
        ))
    return out


def build_preview(
    db: Session, project: Project, cr: ChangeRequest, version: ChangeRequestVersion, approver_id: uuid.UUID
) -> list[ProposedLinkPreviewRow]:
    """What approving `cr` would merge, each pending link re-validated now.

    Links that already have an outcome (a decided request) are shown as they ended, not selectable."""
    described = {d.id: d for d in describe_links(db, project, approver_id, list(version.proposed_links))}
    rows: list[ProposedLinkPreviewRow] = []
    for row in version.proposed_links:
        link = described[row.id]
        if row.outcome != ProposedLinkOutcome.PENDING:
            rows.append(ProposedLinkPreviewRow(link=link, selectable=False, reason=row.outcome_reason))
            continue
        try:
            _check_row(db, project, cr, row, approver_id)
        except ProposedLinkProblem as problem:
            rows.append(ProposedLinkPreviewRow(
                link=link, selectable=False, already_linked=problem.already_linked, reason=problem.message,
            ))
        else:
            rows.append(ProposedLinkPreviewRow(link=link, selectable=True))
    return rows


@dataclass
class MergeResult:
    """How a request's proposed links ended (counts for the audit event and the notification)."""

    merged: int = 0
    declined: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        """How many proposed links were resolved in all."""
        return self.merged + self.declined + self.skipped


def resolve_links(
    db: Session, project: Project, cr: ChangeRequest, version: ChangeRequestVersion, *, approver_id: uuid.UUID,
    merge_ids: set[uuid.UUID] | None,
) -> MergeResult:
    """Creates the chosen links and records every pending link's outcome.

    Call after the requirement exists (for a new requirement, after it is created and
    `cr.requirement_id` is set). `merge_ids` of `None` merges every link that is valid now;
    otherwise only those named (the caller has already refused a named link that is not valid
    now, see `routers.change_requests.workflow`). A link not merged ends `declined` when it
    was valid and left out, `skipped` (with the reason) when it was not valid.

    Returns:
        The counts per outcome.
    """
    result = MergeResult()
    for row in version.proposed_links:
        if row.outcome != ProposedLinkOutcome.PENDING:
            continue
        try:
            checked = _check_row(db, project, cr, row, approver_id)
        except ProposedLinkProblem as problem:
            row.outcome, row.outcome_reason = ProposedLinkOutcome.SKIPPED, problem.message
            result.skipped += 1
            continue
        if merge_ids is not None and row.id not in merge_ids:
            row.outcome = ProposedLinkOutcome.DECLINED
            result.declined += 1
            continue
        requirement_id = cr.requirement_id
        source_type, target_type = (_REQUIREMENT, checked.other_type) if checked.outgoing else (checked.other_type, _REQUIREMENT)
        source_id, target_id = (requirement_id, row.other_id) if checked.outgoing else (row.other_id, requirement_id)
        cross = checked.other_project is not project
        link = create_link(
            db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
            link_type_id=checked.link_type.id, created_by=cr.creator_id, project_id=project.id, enforce_rules=False,
            source_project_id=(project.id if checked.outgoing else checked.other_project.id) if cross else None,
            target_project_id=(checked.other_project.id if checked.outgoing else project.id) if cross else None,
        )
        audit_link(
            db, link, action="created", actor_id=approver_id, projects=(project, checked.other_project),
            via_detail={
                "link_type_id": str(checked.link_type.id), "authorised_by": "change_request",
                "via": "change_request", "change_request_id": str(cr.id),
            },
        )
        row.outcome = ProposedLinkOutcome.MERGED
        result.merged += 1
    return result


def decline_all(version: ChangeRequestVersion) -> int:
    """Marks every still-pending link `declined` (a rejected or withdrawn request merges nothing).

    Returns:
        How many links were marked.
    """
    count = 0
    for row in version.proposed_links:
        if row.outcome == ProposedLinkOutcome.PENDING:
            row.outcome = ProposedLinkOutcome.DECLINED
            count += 1
    return count
