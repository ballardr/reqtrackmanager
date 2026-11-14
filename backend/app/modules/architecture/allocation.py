"""
Module: modules.architecture.allocation

Allocating requirements to elements: the suggestions a placement implies, accepting and dismissing them, and the
coverage figures the project overview shows.

Responsibilities:
- Compute suggestions: for a project-owned element placed in a component, every requirement of that component that is
  not yet linked to it and has not had the suggestion dismissed (`suggestions`).
- Read what is allocated (the requirement-to-element links) and what is dismissed, for one requirement or one element
  (`requirement_view`, `element_view`).
- Accept suggestions through the generic link authoring path, one request for any number of pairs, each in its own
  savepoint (`accept`); dismiss and restore one (`dismiss`, `restore`), with an audit event each.
- Count coverage (`coverage`).

Design decisions (Decided by: Agent unless stated):
- **A suggestion is never stored** (Decided by: User): it is computed from the shared placement table and the
  requirement's own component, so it appears and disappears with the placement and nothing can drift.
- **Only project-owned elements are suggested.** A component belongs to one project, so an element another owner
  shares is allocated manually and never appears as a suggestion.
- **A dismissal applies while the element has stayed in the requirement's component since the dismissal**
  (`dismissal_applies`): the stored row carries only its time, and a placement made later than it voids it. No hook
  into the placement code is needed, and removing the element from the component and placing it again suggests it
  afresh, as the plan requires; the stale row is deleted the next time a person dismisses, restores or accepts it.
- **Any existing link between the two records ends a suggestion**, of whatever type, so accepting never creates a
  second link and an allocation made by hand is never suggested again.
- **Authority** is the authority to change the requirement's links (`link_authoring.require_link_authority`), the same
  authority the accepted link needs; dismissing and restoring are decisions about those links, so they need it too.
- **An approved requirement** follows the project's rule for its links (a change request where required): the accept
  of that pair fails with that reason and the other pairs of a bulk accept still apply.

Dependencies: `models.placement`, `models.requirement`, `models.relationship`, `services.link_authoring`,
`services.link_type_scope`, `services.audit`, this module's models and `visibility`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.placement import ArtefactPlacement
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.models import ArchitectureAllocationDismissal, ArchitectureElement
from app.modules.architecture.service import ELEMENT_ARTEFACT_TYPE
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.services.audit import log_event
from app.services.current_versions import current_versions
from app.services.link_authoring import create_link_for_artefact, require_link_authority
from app.services.link_graph import ArtefactResolver
from app.services.link_type_scope import resolve_link_type_scope

REQUIREMENT_TYPE = "requirement"
#: The core link type an allocation is (a requirement "Allocated to" an element).
ALLOCATION_LINK_NAME = "Allocated to"


@dataclass(frozen=True)
class RequirementRef:
    """A requirement as the allocation screens name it."""

    id: uuid.UUID
    unique_code: str
    name: str
    status: str


@dataclass(frozen=True)
class ElementRef:
    """An element as the allocation screens name it; `organization_id` is set for an organisation-owned one."""

    id: uuid.UUID
    unique_code: str
    name: str
    status: str
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None


@dataclass(frozen=True)
class Pair:
    """One requirement and one element, as a suggestion, an allocation or a dismissal."""

    requirement: RequirementRef
    element: ElementRef
    link_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Coverage:
    """Allocation counts for a project; every figure counts live (not archived, not retired) records.

    Attributes:
        requirements: Requirements of the project.
        allocated_requirements: Those linked to at least one element.
        elements: Elements the project owns.
        allocated_elements: Those with at least one requirement linked.
        suggestions: Suggested allocations awaiting a decision.
    """

    requirements: int
    allocated_requirements: int
    elements: int
    allocated_elements: int
    suggestions: int


def allocation_link_type(db: Session, project: Project) -> RequirementLinkTypeDefinition | None:
    """The "Allocated to" link type the project can use, or `None` when it is hidden or absent."""
    for scoped in resolve_link_type_scope(db, project):
        if scoped.link_type.forward_name == ALLOCATION_LINK_NAME and scoped.shadowed_by is None and not scoped.hidden:
            return scoped.link_type
    return None


def _live_elements(db: Session, project: Project, element_ids: set[uuid.UUID] | None = None) -> dict[uuid.UUID, ArchitectureElement]:
    """The project's own elements that can be allocated to: not archived and not retired."""
    query = select(ArchitectureElement).where(
        ArchitectureElement.project_id == project.id, ArchitectureElement.is_archived.is_(False),
        ArchitectureElement.status.not_in(INACTIVE_STATUSES),
    )
    if element_ids is not None:
        query = query.where(ArchitectureElement.id.in_(element_ids))
    return {e.id: e for e in db.scalars(query)}


def _requirement_refs(db: Session, requirement_ids: set[uuid.UUID]) -> dict[uuid.UUID, RequirementRef]:
    """Requirement references in two statements."""
    if not requirement_ids:
        return {}
    rows = {r.id: r for r in db.scalars(select(Requirement).where(Requirement.id.in_(requirement_ids)))}
    versions = current_versions(db, RequirementVersion, "requirement_id", list(rows))
    return {
        rid: RequirementRef(rid, row.unique_code, versions[rid].name, versions[rid].status.value)
        for rid, row in rows.items()
    }


def _element_ref(element: ArchitectureElement) -> ElementRef:
    return ElementRef(
        element.id, element.unique_code, element.name, element.status, element.project_id, element.organization_id,
    )


def dismissal_applies(dismissed_at: datetime, placed_at: list[datetime]) -> bool:
    """Whether a dismissal still hides its suggestion.

    Args:
        dismissed_at: When the dismissal was made (UTC).
        placed_at: When the element was placed in the requirement's component, one entry per placement row (a
            category under the component is a second row); empty when it is not placed there.

    Returns:
        True when the element is placed there and the earliest placement is not later than the dismissal, so the
        element has stayed in the component since. False once it left the component, which also covers a placement
        made later (the same element placed there again is suggested afresh).
    """
    return bool(placed_at) and min(placed_at) <= dismissed_at


def _placed_in(db: Session, project: Project, element_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[uuid.UUID, list[datetime]]]:
    """`{element id: {component id: placement times}}` for the elements, in one statement."""
    found: dict[uuid.UUID, dict[uuid.UUID, list[datetime]]] = {}
    if not element_ids:
        return found
    for element_id, component_id, created_at in db.execute(
        select(ArtefactPlacement.artefact_id, ArtefactPlacement.component_id, ArtefactPlacement.created_at).where(
            ArtefactPlacement.project_id == project.id, ArtefactPlacement.artefact_type == ELEMENT_ARTEFACT_TYPE,
            ArtefactPlacement.artefact_id.in_(element_ids),
        )
    ).tuples():
        found.setdefault(element_id, {}).setdefault(component_id, []).append(created_at)
    return found


def _linked(db: Session, requirement_ids: set[uuid.UUID], element_ids: set[uuid.UUID]) -> dict[tuple[uuid.UUID, uuid.UUID], ArtefactLink]:
    """The links from a requirement to an element, in either direction, keyed `(requirement id, element id)`."""
    found: dict[tuple[uuid.UUID, uuid.UUID], ArtefactLink] = {}
    if not requirement_ids or not element_ids:
        return found
    for link in db.scalars(
        select(ArtefactLink).where(
            ((ArtefactLink.source_type == REQUIREMENT_TYPE) & ArtefactLink.source_id.in_(requirement_ids)
             & (ArtefactLink.target_type == ELEMENT_ARTEFACT_TYPE) & ArtefactLink.target_id.in_(element_ids))
            | ((ArtefactLink.target_type == REQUIREMENT_TYPE) & ArtefactLink.target_id.in_(requirement_ids)
               & (ArtefactLink.source_type == ELEMENT_ARTEFACT_TYPE) & ArtefactLink.source_id.in_(element_ids))
        )
    ):
        requirement_id, element_id = (
            (link.source_id, link.target_id) if link.source_type == REQUIREMENT_TYPE else (link.target_id, link.source_id)
        )
        found.setdefault((requirement_id, element_id), link)
    return found


def _candidates(
    db: Session, project: Project, *, requirement_id: uuid.UUID | None = None, element_id: uuid.UUID | None = None,
) -> tuple[list[tuple[uuid.UUID, uuid.UUID]], dict[uuid.UUID, dict[uuid.UUID, list[datetime]]]]:
    """Every `(requirement id, element id)` where the element is placed in the requirement's component.

    Returns the pairs (live elements, requirements not archived) and the placement times they came from. With neither
    argument every pair of the project is returned, which only the coverage count asks for.
    """
    elements = _live_elements(db, project, {element_id} if element_id else None)
    placed = _placed_in(db, project, set(elements))
    by_component: dict[uuid.UUID, list[uuid.UUID]] = {}
    for eid, components in placed.items():
        for component_id in components:
            by_component.setdefault(component_id, []).append(eid)
    if not by_component:
        return [], placed
    query = select(Requirement.id, Requirement.component_id).where(
        Requirement.project_id == project.id, Requirement.is_archived.is_(False), Requirement.component_id.in_(by_component),
    )
    if requirement_id is not None:
        query = query.where(Requirement.id == requirement_id)
    pairs = [(rid, eid) for rid, component_id in db.execute(query).tuples() for eid in by_component[component_id]]
    return pairs, placed


def _split(
    db: Session, project: Project, pairs: list[tuple[uuid.UUID, uuid.UUID]], placed: dict[uuid.UUID, dict[uuid.UUID, list[datetime]]],
) -> tuple[list[tuple[uuid.UUID, uuid.UUID]], list[tuple[uuid.UUID, uuid.UUID]]]:
    """Splits candidate pairs into `(suggested, dismissed)`; a pair already linked is neither."""
    if not pairs:
        return [], []
    requirement_ids, element_ids = {p[0] for p in pairs}, {p[1] for p in pairs}
    linked = _linked(db, requirement_ids, element_ids)
    components = {
        rid: cid for rid, cid in db.execute(
            select(Requirement.id, Requirement.component_id).where(Requirement.id.in_(requirement_ids))
        ).tuples()
    }
    dismissals = {
        (d.requirement_id, d.element_id): d
        for d in db.scalars(
            select(ArchitectureAllocationDismissal).where(
                ArchitectureAllocationDismissal.requirement_id.in_(requirement_ids),
                ArchitectureAllocationDismissal.element_id.in_(element_ids),
            )
        )
    }
    suggested: list[tuple[uuid.UUID, uuid.UUID]] = []
    dismissed: list[tuple[uuid.UUID, uuid.UUID]] = []
    for pair in pairs:
        if pair in linked:
            continue
        row = dismissals.get(pair)
        if row is not None and dismissal_applies(row.created_at, placed.get(pair[1], {}).get(components[pair[0]], [])):
            dismissed.append(pair)
        else:
            suggested.append(pair)
    return suggested, dismissed


def _pairs_out(
    db: Session, project: Project, pairs: list[tuple[uuid.UUID, uuid.UUID]], links: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] | None = None,
) -> list[Pair]:
    """The pairs with their requirement and element named, in requirement then element code order."""
    requirements = _requirement_refs(db, {p[0] for p in pairs})
    elements = {
        e.id: _element_ref(e)
        for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_({p[1] for p in pairs})))
    } if pairs else {}
    out = [
        Pair(requirements[r], elements[e], (links or {}).get((r, e)))
        for r, e in pairs if r in requirements and e in elements
    ]
    return sorted(out, key=lambda p: (p.requirement.unique_code, p.element.unique_code))


def suggestions(
    db: Session, project: Project, *, requirement_id: uuid.UUID | None = None, element_id: uuid.UUID | None = None,
) -> tuple[list[Pair], list[Pair]]:
    """The suggested and the dismissed allocations of one requirement, of one element, or of the whole project.

    Returns:
        `(suggested, dismissed)`, each ordered by requirement code then element code.
    """
    pairs, placed = _candidates(db, project, requirement_id=requirement_id, element_id=element_id)
    suggested, dismissed = _split(db, project, pairs, placed)
    return _pairs_out(db, project, suggested), _pairs_out(db, project, dismissed)


def allocated(
    db: Session, project: Project, viewer: Viewer, *, requirement_id: uuid.UUID | None = None, element_id: uuid.UUID | None = None,
) -> list[Pair]:
    """The requirement-to-element links of a requirement or an element, restricted to what the viewer may read.

    An element another owner shares appears only when the viewer can see it (the visibility rules), so a hidden
    element is indistinguishable from a missing one.
    """
    clauses = (ArtefactLink.source_type == REQUIREMENT_TYPE, ArtefactLink.target_type == ELEMENT_ARTEFACT_TYPE)
    query = select(ArtefactLink).where(*clauses, ArtefactLink.source_project_id.is_(None))
    if requirement_id is not None:
        query = query.where(ArtefactLink.source_id == requirement_id)
    if element_id is not None:
        query = query.where(ArtefactLink.target_id == element_id)
    links = list(db.scalars(query))
    if not links:
        return []
    allowed = visible_element_ids(db, viewer, {link.target_id for link in links})
    own_requirements = {
        r for r in db.scalars(select(Requirement.id).where(
            Requirement.project_id == project.id, Requirement.id.in_({link.source_id for link in links})
        ))
    }
    links = [link for link in links if link.target_id in allowed and link.source_id in own_requirements]
    link_ids = {(link.source_id, link.target_id): link.id for link in links}
    return _pairs_out(db, project, list(link_ids), link_ids)


def _audit(
    db: Session, project: Project, actor_id: uuid.UUID, requirement_id: uuid.UUID, action: str, element: ArchitectureElement,
) -> None:
    """Writes the audit event against the requirement; the detail names the element by code only."""
    log_event(
        db, entity_type=REQUIREMENT_TYPE, entity_id=requirement_id, action=action, actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail={"element": element.unique_code},
    )


def _require_suggested_pair(db: Session, project: Project, requirement_id: uuid.UUID, element_id: uuid.UUID) -> ArchitectureElement:
    """The element, after checking it is a live element of the project placed in the requirement's component.

    Raises:
        HTTPException: 404 the requirement or element is not one of the project's live records; 409 the element is not
            placed in the requirement's component.
    """
    requirement = db.get(Requirement, requirement_id)
    elements = _live_elements(db, project, {element_id})
    if requirement is None or requirement.project_id != project.id or requirement.is_archived or element_id not in elements:
        raise HTTPException(404, "Requirement or element not found.")
    pairs, _ = _candidates(db, project, requirement_id=requirement_id, element_id=element_id)
    if (requirement_id, element_id) not in pairs:
        raise HTTPException(409, "The element is not placed in the requirement's component.")
    return elements[element_id]


def _drop_stale_dismissal(db: Session, requirement_id: uuid.UUID, element_id: uuid.UUID) -> ArchitectureAllocationDismissal | None:
    """Deletes and returns the pair's stored dismissal, so a fresh decision starts from no row."""
    row = db.scalar(select(ArchitectureAllocationDismissal).where(
        ArchitectureAllocationDismissal.requirement_id == requirement_id, ArchitectureAllocationDismissal.element_id == element_id,
    ))
    if row is not None:
        db.delete(row)
        db.flush()
    return row


def dismiss(db: Session, project: Project, user: User, requirement_id: uuid.UUID, element_id: uuid.UUID) -> None:
    """Hides a suggested allocation (a no-op when it is already dismissed).

    Raises:
        HTTPException: 403 the user cannot change the requirement's links; 404/409 as `_require_suggested_pair`.
    """
    require_link_authority(ArtefactResolver(db, project, user.id), REQUIREMENT_TYPE)
    element = _require_suggested_pair(db, project, requirement_id, element_id)
    suggested, dismissed = suggestions(db, project, requirement_id=requirement_id, element_id=element_id)
    if not suggested and any(p.element.id == element_id for p in dismissed):
        return
    _drop_stale_dismissal(db, requirement_id, element_id)
    db.add(ArchitectureAllocationDismissal(
        project_id=project.id, requirement_id=requirement_id, element_id=element_id, dismissed_by=user.id,
    ))
    db.flush()
    _audit(db, project, user.id, requirement_id, "allocation_dismissed", element)


def restore(db: Session, project: Project, user: User, requirement_id: uuid.UUID, element_id: uuid.UUID) -> None:
    """Brings a dismissed suggestion back (a no-op when nothing is dismissed).

    Raises:
        HTTPException: 403 the user cannot change the requirement's links; 404 the requirement or element is not one
            of the project's.
    """
    require_link_authority(ArtefactResolver(db, project, user.id), REQUIREMENT_TYPE)
    element = db.get(ArchitectureElement, element_id)
    requirement = db.get(Requirement, requirement_id)
    if element is None or requirement is None or element.project_id != project.id or requirement.project_id != project.id:
        raise HTTPException(404, "Requirement or element not found.")
    if _drop_stale_dismissal(db, requirement_id, element_id) is not None:
        _audit(db, project, user.id, requirement_id, "allocation_restored", element)


@dataclass(frozen=True)
class AcceptResult:
    """What `accept` did: how many links were made and why each other pair was not."""

    accepted: int
    failed: list[tuple[uuid.UUID, uuid.UUID, str]]


def accept(db: Session, project: Project, user: User, pairs: list[tuple[uuid.UUID, uuid.UUID]]) -> AcceptResult:
    """Makes each suggested pair an "Allocated to" link through the generic link authoring path.

    Each pair is its own savepoint, so one refused pair (an approved requirement that needs a change request, a link
    that already exists) does not stop the others.

    Raises:
        HTTPException: 403 the user cannot change requirement links; 400 the project has no usable "Allocated to" type.
    """
    require_link_authority(ArtefactResolver(db, project, user.id), REQUIREMENT_TYPE)
    link_type = allocation_link_type(db, project)
    if link_type is None:
        raise HTTPException(400, f'The "{ALLOCATION_LINK_NAME}" link type is not available in this project.')
    done = 0
    failed: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    for requirement_id, element_id in dict.fromkeys(pairs):
        try:
            with db.begin_nested():
                element = _require_suggested_pair(db, project, requirement_id, element_id)
                create_link_for_artefact(
                    db, project=project, user_id=user.id, artefact_type=REQUIREMENT_TYPE, artefact_id=requirement_id,
                    link_type_id=link_type.id, outgoing=True, other_type=ELEMENT_ARTEFACT_TYPE, other_id=element_id,
                )
                _drop_stale_dismissal(db, requirement_id, element_id)
                _audit(db, project, user.id, requirement_id, "allocation_accepted", element)
            done += 1
        except HTTPException as exc:
            failed.append((requirement_id, element_id, str(exc.detail)))
    return AcceptResult(done, failed)


@dataclass(frozen=True)
class CoverageGaps:
    """What the allocation figures count, as records: the lists behind `Coverage` (the allocation report names them).

    Attributes:
        requirements: Every live requirement of the project.
        unallocated_requirements: Those with no element linked.
        elements: Every live element the project owns.
        unallocated_elements: Those with no requirement linked.
        suggestions: Suggested allocations awaiting a decision, by requirement then element code.
    """

    requirements: int
    unallocated_requirements: list[RequirementRef]
    elements: int
    unallocated_elements: list[ElementRef]
    suggestions: list[Pair]


def coverage_gaps(db: Session, project: Project) -> CoverageGaps:
    """The records behind the project's allocation figures, in a fixed number of statements."""
    requirement_ids = set(db.scalars(select(Requirement.id).where(
        Requirement.project_id == project.id, Requirement.is_archived.is_(False)
    )))
    elements = _live_elements(db, project)
    links = _linked(db, requirement_ids, set(elements))
    pairs, placed = _candidates(db, project)
    suggested, _ = _split(db, project, pairs, placed)
    open_requirements = requirement_ids - {r for r, _ in links}
    allocated_elements = {e for _, e in links}
    refs = _requirement_refs(db, open_requirements)
    return CoverageGaps(
        requirements=len(requirement_ids),
        unallocated_requirements=sorted(refs.values(), key=lambda r: r.unique_code),
        elements=len(elements),
        unallocated_elements=sorted(
            (_element_ref(e) for i, e in elements.items() if i not in allocated_elements), key=lambda e: e.unique_code,
        ),
        suggestions=_pairs_out(db, project, suggested),
    )


def coverage(db: Session, project: Project) -> Coverage:
    """The project's allocation figures (see `Coverage`), in a fixed number of statements."""
    found = coverage_gaps(db, project)
    return Coverage(
        requirements=found.requirements,
        allocated_requirements=found.requirements - len(found.unallocated_requirements),
        elements=found.elements,
        allocated_elements=found.elements - len(found.unallocated_elements),
        suggestions=len(found.suggestions),
    )
