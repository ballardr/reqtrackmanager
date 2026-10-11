"""
Module: services.link_type_scope

Which link types, and which artefact-type link rules, a project sees: the
organisation-wide vocabulary plus the local types of the project and every
ancestor, minus what the project (or an ancestor) hid, with the org lock
(`Organization.project_customisation_locks`) able to switch every project-level
addition off.

Responsibilities:
- Resolve the full scope of a project (`resolve_link_type_scope`), annotated with
  where each type comes from, whether it is hidden, and whether another type of
  the same name shadows it.
- Resolve the types a user may be *offered* (`resolve_effective_link_types`),
  optionally narrowed by the artefact types at the two ends.
- Resolve the artefact-type rules in force for a project (`resolve_artefact_rules`):
  the nearest rule for an artefact type wins and replaces the farther one.
- Decide whether a specific type may be *used* for a new link in a project
  (`assert_link_type_usable`), the single multi-tenant isolation check every
  link creator goes through.

Design decisions:
- Nested projects are additive here (own + ancestors' local types over the
  always-present org base), unlike Action Types' "own else nearest ancestor's",
  because a child adding one type must not lose its parent's. Always on,
  independent of `role_inheritance_mode`.
- Names are compared case-insensitively and the ancestor wins: precedence runs
  organisation, then root-most ancestor, down to the project itself. A loser is
  *shadowed* (not offered) but never deleted, so links already using it keep
  resolving by id.
- Reading versus using: *using* a type (create, picker) requires it to be currently
  usable; *displaying* a link never does. That is what makes the lock, hiding,
  reparenting and detaching non-destructive.
- Fixed-semantic actions (the "Supersedes" flow, the legacy typed endpoints) are
  exempt from hiding and shadowing (`enforce_offered=False`) but never from the
  tenant check.

Dependencies: `services.project_hierarchy` (ancestor chain), the link-type models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ProjectLinkTypeVisibility,
    RequirementLinkTypeDefinition,
)
from app.services.project_hierarchy import get_project_chain_ids

LINK_TYPES_LOCK = "link_types"
PROJECT_CUSTOMISATION_LOCK_KEYS: tuple[str, ...] = (LINK_TYPES_LOCK,)
"""Vocabularies an organisation can forbid projects from customising. Only
`link_types` is wired; the other vocabularies are not retrofitted yet."""

UNAVAILABLE_MESSAGE = "link_type_id must be a link type available to this project."


class LinkRuleError(ValueError):
    """A link that a link type's restriction, an artefact type's rule, or the
    project's link-type scope forbids."""


@dataclass(frozen=True)
class ScopedLinkType:
    """One link type as a project sees it.

    Attributes:
        link_type: The type.
        owner_project_id: The project that owns it, or `None` for an organisation-wide type.
        hidden: The nearest visibility row up the project chain hides it.
        hidden_by_project_id: The project whose row decided `hidden` (or a re-show);
            `None` when no row exists.
        own_visibility: The project's own row (`True` hidden, `False` shown), or
            `None` when it has none, for the admin toggle.
        shadowed_by: A same-named type that wins by precedence, or `None`.
    """

    link_type: RequirementLinkTypeDefinition
    owner_project_id: uuid.UUID | None
    hidden: bool
    hidden_by_project_id: uuid.UUID | None
    own_visibility: bool | None
    shadowed_by: RequirementLinkTypeDefinition | None

    @property
    def offered(self) -> bool:
        """Whether the type is offered for new links (neither hidden nor shadowed)."""
        return not self.hidden and self.shadowed_by is None


def is_customisation_locked(db: Session, organization_id: uuid.UUID, key: str = LINK_TYPES_LOCK) -> bool:
    """Whether the organisation forbids projects from customising the vocabulary `key`."""
    locks = db.scalar(select(Organization.project_customisation_locks).where(Organization.id == organization_id))
    return key in (locks or [])


def resolve_link_type_scope(db: Session, project: Project) -> list[ScopedLinkType]:
    """Every link type reachable from `project`, annotated.

    Order is precedence order: organisation-wide types (by `sort_order`), then each
    ancestor's local types root-first, then the project's own. When the
    organisation locks link-type customisation only the organisation-wide types
    are returned, none hidden or shadowed.

    Args:
        db: Active session (read only).
        project: The project whose scope to resolve.

    Returns:
        The scoped types in precedence order.
    """
    org_types = list(
        db.scalars(
            select(RequirementLinkTypeDefinition)
            .where(
                RequirementLinkTypeDefinition.organization_id == project.organization_id,
                RequirementLinkTypeDefinition.project_id.is_(None),
            )
            .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
        ).all()
    )
    if is_customisation_locked(db, project.organization_id):
        return [ScopedLinkType(t, None, False, None, None, None) for t in org_types]

    chain = get_project_chain_ids(db, project.id)  # nearest first
    local_by_owner: dict[uuid.UUID, list[RequirementLinkTypeDefinition]] = {pid: [] for pid in chain}
    for local in db.scalars(
        select(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.project_id.in_(chain))
        .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
    ).all():
        if local.project_id is not None:
            local_by_owner[local.project_id].append(local)
    visibility = {
        (row.project_id, row.link_type_id): row.hidden
        for row in db.scalars(
            select(ProjectLinkTypeVisibility).where(ProjectLinkTypeVisibility.project_id.in_(chain))
        ).all()
    }

    ordered: list[tuple[RequirementLinkTypeDefinition, uuid.UUID | None]] = [(t, None) for t in org_types]
    for owner in reversed(chain):
        ordered.extend((t, owner) for t in local_by_owner[owner])

    winners: dict[str, RequirementLinkTypeDefinition] = {}
    scoped: list[ScopedLinkType] = []
    for link_type, owner in ordered:
        key = link_type.forward_name.casefold()
        shadowed_by = winners.get(key)
        if shadowed_by is None:
            winners[key] = link_type
        hidden, hidden_by = False, None
        for pid in chain:
            if (pid, link_type.id) in visibility:
                hidden, hidden_by = visibility[(pid, link_type.id)], pid
                break
        scoped.append(
            ScopedLinkType(
                link_type, owner, hidden, hidden_by, visibility.get((project.id, link_type.id)), shadowed_by
            )
        )
    return scoped


def resolve_artefact_rule_rows(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> dict[str, ArtefactTypeLinkRule]:
    """The rule row in force for each artefact type that has one.

    With no `project_id` (or when the organisation locks link-type
    customisation) only the organisation's rules apply. Otherwise the nearest
    rule for each artefact type wins (the project, then each ancestor, then the
    organisation) and replaces the farther one entirely, so a project can widen
    as well as narrow.

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        project_id: The project whose rules to resolve, or `None` for the organisation's.

    Returns:
        The winning rule per artefact type; `rule.project_id` says which scope it is from.
    """
    chain: list[uuid.UUID] = []
    if project_id is not None and not is_customisation_locked(db, organization_id):
        chain = get_project_chain_ids(db, project_id)
    condition = ArtefactTypeLinkRule.project_id.is_(None)
    if chain:
        condition = or_(condition, ArtefactTypeLinkRule.project_id.in_(chain))
    rules = db.scalars(
        select(ArtefactTypeLinkRule).where(ArtefactTypeLinkRule.organization_id == organization_id, condition)
    ).all()
    rank = {pid: index for index, pid in enumerate(chain)}
    best: dict[str, tuple[int, ArtefactTypeLinkRule]] = {}
    for rule in rules:
        position = len(chain) if rule.project_id is None else rank.get(rule.project_id, len(chain))
        if rule.artefact_type not in best or position < best[rule.artefact_type][0]:
            best[rule.artefact_type] = (position, rule)
    return {artefact_type: rule for artefact_type, (_, rule) in best.items()}


def resolve_artefact_rules(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> dict[str, set[uuid.UUID]]:
    """`{artefact_type: permitted link type ids}` in force
    (see `resolve_artefact_rule_rows` for the nearest-wins resolution)."""
    return {
        artefact_type: {entry.link_type_id for entry in rule.allowed_link_types}
        for artefact_type, rule in resolve_artefact_rule_rows(db, organization_id, project_id).items()
    }


def resolve_effective_link_types(
    db: Session,
    project: Project,
    *,
    source_type: str | None = None,
    target_type: str | None = None,
) -> list[RequirementLinkTypeDefinition]:
    """The link types offered for new links in `project`.

    Organisation-wide types plus the local types of the project and its
    ancestors, minus hidden and shadowed ones; when `source_type` and/or
    `target_type` are given, also minus types whose own restriction or either
    end's artefact-type rule excludes them. Everything that lists link types for
    a user calls this rather than querying the table.

    Args:
        db: Active session (read only).
        project: The project.
        source_type: The artefact type at the link's source end, to filter by.
        target_type: The artefact type at the link's target end, to filter by.

    Returns:
        The offered types in precedence order (dedicated types included; callers filter).
    """
    rules = resolve_artefact_rules(db, project.organization_id, project.id) if (source_type or target_type) else {}
    offered: list[RequirementLinkTypeDefinition] = []
    for scoped in resolve_link_type_scope(db, project):
        if not scoped.offered:
            continue
        link_type = scoped.link_type
        if source_type is not None and (
            (link_type.allowed_source_types is not None and source_type not in link_type.allowed_source_types)
            or (source_type in rules and link_type.id not in rules[source_type])
        ):
            continue
        if target_type is not None and (
            (link_type.allowed_target_types is not None and target_type not in link_type.allowed_target_types)
            or (target_type in rules and link_type.id not in rules[target_type])
        ):
            continue
        offered.append(link_type)
    return offered


def assert_link_type_usable(
    db: Session, project: Project, link_type: RequirementLinkTypeDefinition, *, enforce_offered: bool = False
) -> None:
    """Raises unless `link_type` may be used for a new link in `project`.

    The one isolation check every link creator calls: the type is in the
    project's organisation and is organisation-wide, or owned by the project or
    an ancestor (and the organisation has not locked customisation). With
    `enforce_offered` the type must also be offered (not hidden, not shadowed);
    fixed-semantic actions pass `False`.

    The message never says which of "other organisation" / "another project's
    type" applies, so a probe learns nothing about types it cannot use.

    Args:
        db: Active session (read only).
        project: The project the link is created in.
        link_type: The type being used.
        enforce_offered: Also reject a hidden or shadowed type.

    Raises:
        LinkRuleError: If the type is not usable.
    """
    if link_type.organization_id != project.organization_id:
        raise LinkRuleError(UNAVAILABLE_MESSAGE)
    if link_type.project_id is not None and (
        is_customisation_locked(db, project.organization_id)
        or link_type.project_id not in get_project_chain_ids(db, project.id)
    ):
        raise LinkRuleError(UNAVAILABLE_MESSAGE)
    if not enforce_offered:
        return
    scoped = next((s for s in resolve_link_type_scope(db, project) if s.link_type.id == link_type.id), None)
    if scoped is None:
        raise LinkRuleError(UNAVAILABLE_MESSAGE)
    if scoped.shadowed_by is not None:
        raise LinkRuleError(
            f'"{link_type.forward_name}" is not offered here: a link type with the same name takes precedence.'
        )
    if scoped.hidden:
        raise LinkRuleError(f'"{link_type.forward_name}" is hidden in this project.')


def usable_type_ids(db: Session, project: Project, *, include_hidden: bool = True) -> set[uuid.UUID]:
    """Ids of the link types `project` can reach and use (shadowed ones excluded;
    hidden ones included unless `include_hidden` is false)."""
    return {
        s.link_type.id
        for s in resolve_link_type_scope(db, project)
        if s.shadowed_by is None and (include_hidden or not s.hidden)
    }

