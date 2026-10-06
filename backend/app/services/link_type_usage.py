"""
Module: services.link_type_usage

Deleting a link type that is in use: what depends on it, and the two ways out
(move its links to another type, or delete them too).

Responsibilities:
- `compute_usage`: how many links, projects, pending change requests and
  approved-requirement links depend on a type; which artefact-type rules name
  it; and, for every other type, whether it could take over (with the reason it
  cannot, never silently skipped).
- `delete_link_type`: the single delete path, in one transaction, writing one
  audit event per link touched plus one for the type itself.

Design decisions:
- Moving links merges duplicates: a moved link that would repeat an existing
  link of the target type between the same two records is dropped, and the
  count is reported, rather than failing the whole move.
- A pending change request that proposes the type is repointed by a move and
  *blocks* link removal; the foreign key's `SET NULL` would otherwise strip the
  type and leave a request that can no longer be applied.
- An artefact-type rule naming the type gets the replacement substituted by a
  move; removal drops it from the rule and is refused when that would empty the
  rule, never silently widening one to "any link type".
- Project and approved-link figures are best effort (projects are resolved
  per artefact, so large sets report `None` for the project count).

Dependencies: `services.link_types` (rules and validation), `services.requirements`
(lock state), `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ArtefactType, ChangeRequestStatus
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ArtefactTypeLinkRuleEntry,
    RequirementLinkTypeDefinition,
)
from app.modules.registry import get_artefact_summary, get_artefact_type_label
from app.services.audit import log_event
from app.services.link_types import get_artefact_rules
from app.services.requirements import LOCKED_STATUSES, requires_change_request_for_links

# Above this many links the per-artefact project lookup is skipped.
MAX_PROJECT_SCAN = 1000

_PENDING_STATUSES = (ChangeRequestStatus.DRAFT, ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)

DeleteMode = Literal["reassign", "remove_links"]


@dataclass(frozen=True)
class Candidate:
    """Another link type, and whether it can take over the links of the type being deleted.

    Attributes:
        link_type: The candidate.
        compatible: True when every affected link could move to it.
        reason: Why not, when `compatible` is false.
        flow_differs: True when its `flow` differs, so a move changes what the links mean.
    """

    link_type: RequirementLinkTypeDefinition
    compatible: bool
    reason: str | None
    flow_differs: bool


@dataclass(frozen=True)
class LinkTypeUsage:
    """What depends on a link type (see `compute_usage`).

    Attributes:
        link_count: Links of the type.
        project_count: Distinct projects holding them, or `None` when too many to resolve.
        pending_change_requests: Open change requests proposing the type.
        approved_requirement_links: Links touching an approved requirement in a project
            that requires a change request for such links.
        rule_artefact_types: Artefact types whose rule names the type.
        emptied_rule_artefact_types: The subset whose rule would become empty on removal.
        is_dedicated: The type has a fixed meaning with its own action.
        candidates: Every other link type of the organisation, assessed.
        is_last: The organisation's only link type (cannot be deleted).
    """

    link_count: int
    project_count: int | None
    pending_change_requests: int
    approved_requirement_links: int
    rule_artefact_types: list[str]
    emptied_rule_artefact_types: list[str]
    is_dedicated: bool
    candidates: list[Candidate]
    is_last: bool


@dataclass
class DeleteOutcome:
    """What a delete did: links moved to the replacement, merged into existing
    ones, or removed."""

    moved: int = 0
    merged: int = 0
    removed: int = 0
    rules_updated: list[str] = field(default_factory=list)


def _affected_pairs(db: Session, link_type_id: uuid.UUID) -> list[tuple[str, str]]:
    """The distinct `(source_type, target_type)` pairs of the type's links."""
    return [
        (row.source_type, row.target_type)
        for row in db.execute(
            select(ArtefactLink.source_type, ArtefactLink.target_type)
            .where(ArtefactLink.link_type_id == link_type_id)
            .distinct()
        ).all()
    ]


def _assess_candidate(
    candidate: RequirementLinkTypeDefinition,
    old: RequirementLinkTypeDefinition,
    pairs: list[tuple[str, str]],
    rules: dict[str, set[uuid.UUID]],
) -> Candidate:
    """Whether `candidate` could take over every link of `old` (see `Candidate`).

    Checks the candidate's own restriction against each affected pair, and each
    end's rule, treating a rule that names `old` as one the candidate will be
    substituted into."""
    flow_differs = candidate.flow != old.flow
    if candidate.dedicated_endpoint or old.dedicated_endpoint:
        return Candidate(candidate, False, "Links of this type have a fixed meaning and cannot be converted.", flow_differs)
    for source_type, target_type in pairs:
        if candidate.allowed_source_types is not None and source_type not in candidate.allowed_source_types:
            return Candidate(
                candidate, False,
                f"It cannot start from a {get_artefact_type_label(source_type).lower()}, which some links do.",
                flow_differs,
            )
        if candidate.allowed_target_types is not None and target_type not in candidate.allowed_target_types:
            return Candidate(
                candidate, False,
                f"It cannot point at a {get_artefact_type_label(target_type).lower()}, which some links do.",
                flow_differs,
            )
        for artefact_type in dict.fromkeys((source_type, target_type)):
            permitted = rules.get(artefact_type)
            # A rule naming the old type gets the candidate substituted in, so it still permits it.
            if permitted is not None and candidate.id not in permitted and old.id not in permitted:
                return Candidate(
                    candidate, False,
                    f"{get_artefact_type_label(artefact_type)} links are limited to other link types.",
                    flow_differs,
                )
    return Candidate(candidate, True, None, flow_differs)


def _artefact_project_ids(db: Session, ends: set[tuple[str, uuid.UUID]]) -> dict[tuple[str, uuid.UUID], uuid.UUID | None]:
    """Best-effort project of each `(type, id)`: core types in one query each, others via their provider."""
    result: dict[tuple[str, uuid.UUID], uuid.UUID | None] = {}
    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for artefact_type, artefact_id in ends:
        by_type[artefact_type].append(artefact_id)
    for artefact_type, ids in by_type.items():
        if artefact_type == ArtefactType.REQUIREMENT.value:
            rows = db.execute(select(Requirement.id, Requirement.project_id).where(Requirement.id.in_(ids))).all()
        elif artefact_type == ArtefactType.REQUIREMENT_ACTION.value:
            rows = db.execute(select(RequirementAction.id, RequirementAction.project_id).where(RequirementAction.id.in_(ids))).all()
        else:
            rows = []
            for artefact_id in ids:
                summary = get_artefact_summary(db, artefact_type, artefact_id)
                rows.append((artefact_id, summary.project_id if summary is not None else None))
        for artefact_id, project_id in rows:
            result[(artefact_type, artefact_id)] = project_id
    return result


def _approved_requirement_links(db: Session, links: list[ArtefactLink]) -> int:
    """Links with an approved requirement end in a project that requires a change request for them."""
    requirement_value = ArtefactType.REQUIREMENT.value
    requirement_ids = {
        i for link in links for t, i in ((link.source_type, link.source_id), (link.target_type, link.target_id))
        if t == requirement_value
    }
    if not requirement_ids:
        return 0
    rows = db.execute(
        select(Requirement.id, Requirement.project_id)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.id.in_(requirement_ids), RequirementVersion.valid_to.is_(None),
            RequirementVersion.status.in_(LOCKED_STATUSES),
        )
    ).all()
    locked_project = {requirement_id: project_id for requirement_id, project_id in rows}
    gated: dict[uuid.UUID, bool] = {}
    count = 0
    for link in links:
        for artefact_type, artefact_id in ((link.source_type, link.source_id), (link.target_type, link.target_id)):
            project_id = locked_project.get(artefact_id) if artefact_type == requirement_value else None
            if project_id is None:
                continue
            if project_id not in gated:
                project = db.get(Project, project_id)
                gated[project_id] = project is not None and requires_change_request_for_links(db, project)
            if gated[project_id]:
                count += 1
                break
    return count


def _pending_change_request_count(db: Session, link_type_id: uuid.UUID) -> int:
    """Open (draft, submitted, in review) change requests proposing the type."""
    return db.scalar(
        select(func.count(func.distinct(ChangeRequest.id)))
        .select_from(ChangeRequestVersion)
        .join(ChangeRequest, ChangeRequest.id == ChangeRequestVersion.change_request_id)
        .where(ChangeRequestVersion.proposed_link_type_id == link_type_id, ChangeRequest.status.in_(_PENDING_STATUSES))
    ) or 0


def _rule_ids_naming(db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID) -> list[ArtefactTypeLinkRule]:
    """The organisation's artefact-type rules that name the link type."""
    return list(
        db.scalars(
            select(ArtefactTypeLinkRule)
            .join(ArtefactTypeLinkRuleEntry, ArtefactTypeLinkRuleEntry.rule_id == ArtefactTypeLinkRule.id)
            .where(ArtefactTypeLinkRule.organization_id == organization_id, ArtefactTypeLinkRuleEntry.link_type_id == link_type_id)
            .order_by(ArtefactTypeLinkRule.artefact_type)
        ).all()
    )


def _get_link_type(db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID) -> RequirementLinkTypeDefinition:
    """The link type, or 404 unless it belongs to the organisation."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    return link_type


def compute_usage(db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID) -> LinkTypeUsage:
    """Everything the delete dialog needs to know about a link type.

    Args:
        db: Active session (read only).
        organization_id: The organisation the type must belong to.
        link_type_id: The type.

    Returns:
        The usage report.

    Raises:
        HTTPException: 404 if the type is not in the organisation.
    """
    link_type = _get_link_type(db, organization_id, link_type_id)
    links = list(db.scalars(select(ArtefactLink).where(ArtefactLink.link_type_id == link_type_id)).all())
    project_count: int | None = None
    if len(links) <= MAX_PROJECT_SCAN:
        ends = {(link.source_type, link.source_id) for link in links} | {(link.target_type, link.target_id) for link in links}
        projects = _artefact_project_ids(db, ends)
        project_count = len({p for p in projects.values() if p is not None})
    rules = get_artefact_rules(db, organization_id)
    rule_types = sorted(t for t, ids in rules.items() if link_type_id in ids)
    pairs = _affected_pairs(db, link_type_id)
    others = db.scalars(
        select(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id, RequirementLinkTypeDefinition.id != link_type_id)
        .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
    ).all()
    return LinkTypeUsage(
        link_count=len(links), project_count=project_count,
        pending_change_requests=_pending_change_request_count(db, link_type_id),
        approved_requirement_links=_approved_requirement_links(db, links),
        rule_artefact_types=rule_types,
        emptied_rule_artefact_types=[t for t in rule_types if rules[t] == {link_type_id}],
        is_dedicated=link_type.dedicated_endpoint,
        candidates=[_assess_candidate(other, link_type, pairs, rules) for other in others],
        is_last=not others,
    )


def delete_link_type(
    db: Session,
    *,
    organization_id: uuid.UUID,
    link_type_id: uuid.UUID,
    mode: DeleteMode | None,
    reassign_to_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> DeleteOutcome:
    """Deletes a link type, in one transaction, dealing with whatever uses it.

    An unused type is simply deleted. A type in use needs `mode`: `reassign`
    (with `reassign_to_id`) moves its links, merging duplicates, repointing
    pending change requests and substituting into artefact-type rules;
    `remove_links` deletes the links. Passing `reassign_to_id` without a mode
    means `reassign`. Writes one audit event per link moved, merged or removed
    and one for the type. Does not commit.

    Args:
        db: Active session.
        organization_id: The organisation the type must belong to.
        link_type_id: The type to delete.
        mode: `"reassign"`, `"remove_links"` or `None`.
        reassign_to_id: The replacement type for `reassign`.
        actor_id: The acting user, for audit.

    Returns:
        Counts of what happened.

    Raises:
        HTTPException: 404 unknown type; 409 last type, in use with no mode,
            pending change requests block removal, a rule would be emptied, or
            the replacement cannot take every link; 400 invalid replacement.
    """
    link_type = _get_link_type(db, organization_id, link_type_id)
    others = db.scalar(
        select(func.count()).select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
    ) or 0
    if others <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "An organisation must always have at least one requirement link type.")

    links = list(db.scalars(select(ArtefactLink).where(ArtefactLink.link_type_id == link_type_id)).all())
    if mode is None and reassign_to_id is not None:
        mode = "reassign"
    if links and mode is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This link type is used by {len(links)} link(s). Pass reassign_to_id to convert them to another "
            "link type before deleting, or mode=remove_links to delete them.",
        )

    rules = _rule_ids_naming(db, organization_id, link_type_id)
    outcome = DeleteOutcome()
    replacement: RequirementLinkTypeDefinition | None = None

    if mode == "reassign":
        if reassign_to_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id is required for mode=reassign.")
        if reassign_to_id == link_type_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id must be different from the item being deleted.")
        replacement = db.get(RequirementLinkTypeDefinition, reassign_to_id)
        if replacement is None or replacement.organization_id != organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id must be an existing link type in the same scope.")
        assessment = _assess_candidate(
            replacement, link_type, _affected_pairs(db, link_type_id), get_artefact_rules(db, organization_id)
        )
        if not assessment.compatible:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f'"{replacement.forward_name}" cannot take these links: {assessment.reason}'
            )
        _move_links(db, links, link_type, replacement, actor_id, organization_id, outcome)
        db.execute(
            update(ChangeRequestVersion)
            .where(ChangeRequestVersion.proposed_link_type_id == link_type_id)
            .values(proposed_link_type_id=replacement.id)
        )
        for rule in rules:
            ids = {entry.link_type_id for entry in rule.allowed_link_types}
            ids.discard(link_type_id)
            ids.add(replacement.id)
            rule.allowed_link_types = [ArtefactTypeLinkRuleEntry(link_type_id=i) for i in sorted(ids, key=str)]
            outcome.rules_updated.append(rule.artefact_type)
    else:
        if _pending_change_request_count(db, link_type_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{_pending_change_request_count(db, link_type_id)} pending change request(s) propose this link type; "
                "resolve them before deleting it.",
            )
        emptied = [rule.artefact_type for rule in rules if {e.link_type_id for e in rule.allowed_link_types} == {link_type_id}]
        if emptied:
            names = ", ".join(get_artefact_type_label(t) for t in emptied)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The link rule for {names} allows only this link type; edit or remove that rule first.",
            )
        for link in links:
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="deleted", actor_id=actor_id,
                organization_id=organization_id,
                detail={
                    "source_type": link.source_type, "source_id": str(link.source_id),
                    "target_type": link.target_type, "target_id": str(link.target_id),
                    "link_type_id": str(link_type_id), "reason": "link_type_deleted",
                },
            )
            db.delete(link)
            outcome.removed += 1
        for rule in rules:
            rule.allowed_link_types = [e for e in rule.allowed_link_types if e.link_type_id != link_type_id]
            outcome.rules_updated.append(rule.artefact_type)
    db.flush()

    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="deleted", actor_id=actor_id,
        organization_id=organization_id,
        detail={
            "name": link_type.forward_name, "mode": mode, "moved": outcome.moved, "merged": outcome.merged,
            "removed": outcome.removed,
            "reassigned_to": str(replacement.id) if replacement is not None else None,
        },
    )
    db.execute(delete(ArtefactTypeLinkRuleEntry).where(ArtefactTypeLinkRuleEntry.link_type_id == link_type_id))
    db.delete(link_type)
    db.flush()
    return outcome


def _move_links(
    db: Session,
    links: list[ArtefactLink],
    old: RequirementLinkTypeDefinition,
    replacement: RequirementLinkTypeDefinition,
    actor_id: uuid.UUID,
    organization_id: uuid.UUID,
    outcome: DeleteOutcome,
) -> None:
    """Repoints `links` at `replacement`, dropping any that would duplicate an existing link of it."""
    existing = {
        (row.source_type, row.source_id, row.target_type, row.target_id)
        for row in db.execute(
            select(ArtefactLink.source_type, ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id)
            .where(ArtefactLink.link_type_id == replacement.id)
        ).all()
    }
    for link in links:
        key = (link.source_type, link.source_id, link.target_type, link.target_id)
        base = {
            "source_type": link.source_type, "source_id": str(link.source_id),
            "target_type": link.target_type, "target_id": str(link.target_id),
            "from_link_type_id": str(old.id), "to_link_type_id": str(replacement.id),
        }
        if key in existing:
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="deleted", actor_id=actor_id,
                organization_id=organization_id, detail={**base, "reason": "merged_into_existing"},
            )
            db.delete(link)
            outcome.merged += 1
        else:
            link.link_type_id = replacement.id
            existing.add(key)
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="link_type_changed", actor_id=actor_id,
                organization_id=organization_id, detail=base,
            )
            outcome.moved += 1
