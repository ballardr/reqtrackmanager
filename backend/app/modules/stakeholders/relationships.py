"""
Module: modules.stakeholders.relationships

The remaining overview §10.5 relationships a Stakeholder or Persona has with
other artefacts (Phase 3), as one declarative table of `RelationshipKind`s over
Module 0's polymorphic `ArtefactLink`. "Represents Persona" and "Has need"
shipped earlier with their own endpoints; this covers the rest.

Responsibilities:
- Declare each kind: its org link-type names, which holder kinds (Stakeholder,
  Persona) may use it, and which target artefact types it points at.
- Resolve a target without importing the module that owns it: `requirement` is
  core, every other type goes through `registry.get_artefact_summary` (so Pain
  Points and Decisions stay Context & Strategy's and Decision Management's own).
- Create/list/delete links, enforcing that a target belongs to the same project
  as the request and that a kind's holder/target types are respected.

Design decisions:
- A kind whose target types no installed module provides (Design/System
  Element, until Module 6 exists) is *declared but unavailable*: it is listed
  with `available=False` and creating it is a 409. When the owning module later
  registers an `artefact_summary_provider` for that type it goes live with no
  change here — the reservation costs nothing, as the plan intended.
- Links live in `ArtefactLink` with one org `RequirementLinkTypeDefinition` per
  kind, created on first use (the helper "Represents"/"Has need" use), so
  nothing is seeded and a renamed or deleted default is harmless.
- Listing is always per project: a holder can be org-wide, so only targets in
  the requesting project are shown, never another project's.

Dependencies: `services.relationships` (link storage), `modules.registry`
(summary providers), core `Requirement`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.registry import (
    ArtefactSummary,
    LinkTypeSeed,
    get_artefact_summary,
    has_artefact_summary_provider,
    list_artefact_summaries,
)
from app.modules.stakeholders.models import Persona, Stakeholder
from app.modules.stakeholders.service import (
    GIVES_RISE_TO_FORWARD,
    GIVES_RISE_TO_REVERSE,
    HAS_NEED_FORWARD,
    HAS_NEED_REVERSE,
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    get_or_create_link_type,
)
from app.services.relationships import create_link, delete_link, get_all_links, get_link_between
from app.services.requirements import get_current_version as get_current_requirement_version

REQUIREMENT_TARGET = "requirement"
PAIN_POINT_TARGET = "pain_point"
DECISION_TARGET = "decision"
DESIGN_TARGET = "design"
SYSTEM_ELEMENT_TARGET = "system_element"

_BOTH = (STAKEHOLDER_ARTEFACT_TYPE, PERSONA_ARTEFACT_TYPE)
_STAKEHOLDER_ONLY = (STAKEHOLDER_ARTEFACT_TYPE,)


@dataclass(frozen=True)
class RelationshipKind:
    """One kind of relationship from a Stakeholder/Persona to another artefact.

    Attributes:
        key: Stable API identifier, e.g. `"experiences_pain_point"`.
        forward: The org link type's forward name (holder → target), also the
            label shown on the holder's page.
        reverse: The link type's reverse name (target → holder).
        holder_types: Artefact types (`stakeholder`/`persona`) that may be the source.
        target_types: Artefact types that may be the target.
    """

    key: str
    forward: str
    reverse: str
    holder_types: tuple[str, ...]
    target_types: tuple[str, ...]


# Personas are archetypes, not people: they can experience a pain point, be
# affected by or (directly) provide a requirement, and use a design, but they
# are never consulted, never approve and never review (Decided by: Agent).
RELATIONSHIP_KINDS: tuple[RelationshipKind, ...] = (
    RelationshipKind("experiences_pain_point", "Experiences", "Is experienced by", _BOTH, (PAIN_POINT_TARGET,)),
    RelationshipKind("provides_requirement", "Provides", "Is provided by", _BOTH, (REQUIREMENT_TARGET,)),
    RelationshipKind("affected_by_requirement", "Is affected by", "Affects", _BOTH, (REQUIREMENT_TARGET,)),
    RelationshipKind("consulted_on_decision", "Consulted on", "Consulted", _STAKEHOLDER_ONLY, (DECISION_TARGET,)),
    RelationshipKind("approves", "Approves", "Is approved by", _STAKEHOLDER_ONLY, (REQUIREMENT_TARGET, DECISION_TARGET)),
    RelationshipKind("reviews", "Reviews", "Is reviewed by", _STAKEHOLDER_ONLY, (REQUIREMENT_TARGET, DECISION_TARGET)),
    # Reserved: no installed module provides these targets yet (Module 6).
    RelationshipKind("uses_design_element", "Uses", "Is used by", _BOTH, (DESIGN_TARGET, SYSTEM_ELEMENT_TARGET)),
)

_KIND_BY_KEY = {kind.key: kind for kind in RELATIONSHIP_KINDS}


def get_kind(key: str) -> RelationshipKind | None:
    """The declared kind with this key, or `None`."""
    return _KIND_BY_KEY.get(key)


def target_type_available(target_type: str) -> bool:
    """Whether `target_type` can be linked to right now: core Requirements
    always, anything else only while an installed module provides it."""
    return target_type == REQUIREMENT_TARGET or has_artefact_summary_provider(target_type)


def available_target_types(kind: RelationshipKind) -> tuple[str, ...]:
    """The subset of `kind.target_types` that can be linked to right now."""
    return tuple(t for t in kind.target_types if target_type_available(t))


def _requirement_summary(db: Session, requirement: Requirement) -> ArtefactSummary:
    return ArtefactSummary(
        id=requirement.id, project_id=requirement.project_id,
        label=f"{requirement.unique_code} {get_current_requirement_version(db, requirement.id).name}",
        status=None, is_archived=False,
    )


def resolve_target(db: Session, project: Project, target_type: str, target_id: uuid.UUID) -> ArtefactSummary | None:
    """The summary of the target, or `None` unless it exists, belongs to
    `project` and (for a module's artefact) its module is enabled there — so a
    caller can answer "another project's id" and "not found" identically."""
    if target_type == REQUIREMENT_TARGET:
        requirement = db.get(Requirement, target_id)
        if requirement is None or requirement.project_id != project.id:
            return None
        return _requirement_summary(db, requirement)
    summary = get_artefact_summary(db, target_type, target_id)
    if summary is None or summary.project_id != project.id:
        return None
    return summary


def list_targets(db: Session, project: Project, target_type: str) -> list[ArtefactSummary]:
    """The records of `target_type` a picker can offer for `project`."""
    if target_type == REQUIREMENT_TARGET:
        rows = db.scalars(
            select(Requirement).where(Requirement.project_id == project.id).order_by(Requirement.unique_code)
        ).all()
        return [_requirement_summary(db, r) for r in rows]
    return list_artefact_summaries(db, project.id, target_type)


def _link_type_ids(db: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, RelationshipKind]:
    """`{link_type_id: kind}` for the kinds whose org link type exists."""
    rows = db.execute(
        select(RequirementLinkTypeDefinition.id, RequirementLinkTypeDefinition.forward_name).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name.in_([k.forward for k in RELATIONSHIP_KINDS]),
        )
    ).all()
    by_forward = {k.forward: k for k in RELATIONSHIP_KINDS}
    return {row.id: by_forward[row.forward_name] for row in rows}


def add_relationship(
    db: Session, holder_type: str, holder_id: uuid.UUID, kind: RelationshipKind, summary: ArtefactSummary,
    target_type: str, actor: User, *, organization_id: uuid.UUID, project_id: uuid.UUID | None = None,
) -> Any:
    """Records that a Stakeholder/Persona has `kind` to the target. The caller
    has authorised the holder and resolved `summary` within the request's project.

    Raises:
        ValueError: If the holder or target type is not allowed for `kind`, the
            target type is not available yet, or the link already exists.
    """
    if holder_type not in kind.holder_types:
        raise ValueError(f"A {holder_type} cannot have the \"{kind.forward}\" relationship.")
    if target_type not in kind.target_types:
        raise ValueError(f"\"{kind.forward}\" cannot point at a {target_type}.")
    if not target_type_available(target_type):
        raise ValueError(f"\"{kind.forward}\" a {target_type} is not available until that module is installed.")
    link_type = get_or_create_link_type(db, organization_id, kind.forward, kind.reverse)
    if get_link_between(
        db, source_type=holder_type, source_id=holder_id, target_type=target_type, target_id=summary.id,
        link_type_id=link_type.id,
    ) is not None:
        raise ValueError("That relationship already exists.")
    return create_link(
        db, source_type=holder_type, source_id=holder_id, target_type=target_type, target_id=summary.id,
        link_type_id=link_type.id, created_by=actor.id, project_id=project_id,
    )


def list_relationships(
    db: Session, project: Project, holder_type: str, holder_id: uuid.UUID
) -> list[tuple[Any, RelationshipKind, ArtefactSummary]]:
    """`(link, kind, target)` for every relationship the holder has to a record
    of this project (targets elsewhere, deleted, or whose module is disabled are
    left out)."""
    kinds = _link_type_ids(db, project.organization_id)
    rows = []
    for link in get_all_links(db, holder_type, holder_id):
        kind = kinds.get(link.link_type_id) if link.link_type_id else None
        if kind is None or link.source_id != holder_id or link.source_type != holder_type:
            continue
        if link.target_type not in kind.target_types:
            continue
        summary = resolve_target(db, project, link.target_type, link.target_id)
        if summary is not None:
            rows.append((link, kind, summary))
    return rows


def list_incoming(
    db: Session, project: Project, target_type: str, target_id: uuid.UUID
) -> list[tuple[Any, RelationshipKind, str, Stakeholder | Persona]]:
    """`(link, kind, holder_type, holder)` for every Stakeholder/Persona that has
    one of these relationships to the target. The caller has resolved the target
    within `project`; holders the project cannot see are left out."""
    kinds = _link_type_ids(db, project.organization_id)
    models = {STAKEHOLDER_ARTEFACT_TYPE: Stakeholder, PERSONA_ARTEFACT_TYPE: Persona}
    rows = []
    for link in get_all_links(db, target_type, target_id):
        kind = kinds.get(link.link_type_id) if link.link_type_id else None
        if kind is None or link.target_id != target_id or link.target_type != target_type:
            continue
        if link.source_type not in models or link.source_type not in kind.holder_types:
            continue
        holder = db.get(models[link.source_type], link.source_id)
        if holder is not None:
            rows.append((link, kind, link.source_type, holder))
    return rows


def find_link(db: Session, project: Project, holder_type: str, holder_id: uuid.UUID, link_id: uuid.UUID) -> Any | None:
    """The holder's relationship link with this id (from `list_relationships`),
    or `None` — so a link id from another holder or project can never be removed."""
    for link, _kind, _summary in list_relationships(db, project, holder_type, holder_id):
        if link.id == link_id:
            return link
    return None


def remove_relationship(db: Session, link: Any) -> None:
    """Deletes a relationship link. The caller commits."""
    delete_link(db, link)


LINK_TYPE_SEEDS: tuple[LinkTypeSeed, ...] = (
    *(
        LinkTypeSeed(
            forward_name=kind.forward, reverse_name=kind.reverse,
            allowed_source_types=kind.holder_types, allowed_target_types=kind.target_types,
        )
        for kind in RELATIONSHIP_KINDS
    ),
    LinkTypeSeed(
        "Represents", "Is represented by",
        allowed_source_types=(STAKEHOLDER_ARTEFACT_TYPE,), allowed_target_types=(PERSONA_ARTEFACT_TYPE,),
    ),
    LinkTypeSeed(
        HAS_NEED_FORWARD, HAS_NEED_REVERSE,
        allowed_source_types=_BOTH, allowed_target_types=(NEED_ARTEFACT_TYPE,),
    ),
    LinkTypeSeed(
        GIVES_RISE_TO_FORWARD, GIVES_RISE_TO_REVERSE,
        allowed_source_types=(NEED_ARTEFACT_TYPE,), allowed_target_types=(REQUIREMENT_TARGET,),
    ),
)
"""Link types the Stakeholders module ships (`ModuleDefinition.link_type_seeds`),
derived from the relationship-kind table plus the three bespoke ones, so the
vocabulary has one definition."""
