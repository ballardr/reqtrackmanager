"""
Module: services.link_types

The rules that decide which links may be created: link types (an org-managed
vocabulary) and the two optional restrictions around them.

Responsibilities:
- Create an organisation's link types from registered seeds (core defaults and
  `ModuleDefinition.link_type_seeds`), lazily and only when absent
  (`ensure_org_link_type`, `ensure_org_seeds`).
- Validate a link at creation (`validate_link_allowed`): the link type's own
  source/target artefact-type restriction, and each end's artefact-type rule
  (the closed list of link types that artefact type may use). Either side can
  veto; the message names which rule failed.
- Work out which link types are usable from a given artefact
  (`list_usable_link_types`), for the link authoring pickers.
- Read and write artefact-type rules (`get_artefact_rules`, `set_artefact_rule`,
  `clear_artefact_rule`).

Design decisions:
- Any two registered artefact types can be linked by default; a restriction only
  narrows. Everything is checked at creation only, so editing a restriction or
  rule never deletes or invalidates existing links.
- Restrictions are plain strings checked against the registry-merged artefact
  types on write and tolerated on read, so uninstalling a module never breaks a
  stored restriction (it simply matches nothing).
- A seed is only ever used when the organisation has no type with that forward
  name, so an admin's edits are never overwritten.

Dependencies: `modules.registry` (seeds, artefact types, labels, enablement).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ArtefactTypeLinkRuleEntry,
    RequirementLinkTypeDefinition,
)
from app.modules.registry import (
    get_all_link_type_seeds,
    get_all_registered_artefact_types,
    get_artefact_type_label,
    get_link_type_seed_owners,
    is_module_enabled,
)


class LinkRuleError(ValueError):
    """A link that a link type's restriction or an artefact type's rule forbids."""


def normalise_artefact_types(types: Iterable[str] | None, *, field_name: str) -> list[str] | None:
    """Validates a restriction list for writing.

    Args:
        types: Artefact types, or `None`/empty for "any".
        field_name: Name used in the error message.

    Returns:
        The de-duplicated list in the given order, or `None` for any.

    Raises:
        ValueError: If a value is not a registered artefact type.
    """
    if not types:
        return None
    valid = get_all_registered_artefact_types()
    cleaned = list(dict.fromkeys(types))
    unknown = [t for t in cleaned if t not in valid]
    if unknown:
        raise ValueError(f"{field_name} contains unknown artefact type(s): {', '.join(sorted(unknown))}.")
    return cleaned


def get_org_link_type(db: Session, organization_id: uuid.UUID, forward_name: str) -> RequirementLinkTypeDefinition | None:
    """The organisation's link type with this forward name, or `None`."""
    return db.scalar(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == forward_name,
        )
    )


def ensure_org_link_type(
    db: Session, organization_id: uuid.UUID, forward_name: str, reverse_name: str | None = None
) -> RequirementLinkTypeDefinition:
    """The organisation's link type named `forward_name`, created from the
    registered seed (or, for an unregistered name, from `reverse_name`) on first
    use. An existing type is returned untouched.

    Args:
        db: Active session; the new row is flushed, not committed.
        organization_id: The owning organisation.
        forward_name: The forward phrase identifying the type.
        reverse_name: Reverse phrase when no seed declares one; defaults to the
            forward phrase (a symmetric type).

    Returns:
        The existing or newly created link type.
    """
    existing = get_org_link_type(db, organization_id, forward_name)
    if existing is not None:
        return existing
    seed = get_all_link_type_seeds().get(forward_name)
    count = db.scalar(
        select(func.count()).select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
    ) or 0
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=forward_name,
        reverse_name=seed.reverse_name if seed is not None else (reverse_name or forward_name),
        sort_order=count,
    )
    if seed is not None:
        link_type.flow = seed.flow
        link_type.allowed_source_types = list(seed.allowed_source_types) if seed.allowed_source_types else None
        link_type.allowed_target_types = list(seed.allowed_target_types) if seed.allowed_target_types else None
        link_type.dedicated_endpoint = seed.dedicated_endpoint
    try:
        with db.begin_nested():
            db.add(link_type)
            db.flush()
    except IntegrityError:
        # A concurrent request created the same type first; use theirs.
        existing = get_org_link_type(db, organization_id, forward_name)
        if existing is None:
            raise
        return existing
    return link_type


def ensure_org_seeds(db: Session, organization_id: uuid.UUID) -> None:
    """Creates every module-seeded link type the organisation lacks, for the
    modules enabled in it, so the pickers can offer them before first use.

    Types an admin deleted are recreated here, as they already were on first
    use by the module that needs them; restrict a type rather than deleting it
    to keep it out of the pickers.
    """
    enabled: dict[str, bool] = {}
    for forward_name, owners in get_link_type_seed_owners().items():
        for key in owners:
            if key not in enabled:
                enabled[key] = is_module_enabled(db, organization_id, key)
        if any(enabled[key] for key in owners):
            ensure_org_link_type(db, organization_id, forward_name)


def list_org_artefact_types(db: Session, organization_id: uuid.UUID) -> list[str]:
    """The artefact types that exist in the organisation: the core types plus
    those of every module enabled in it, sorted by display label."""
    from app.models.enums import ArtefactType
    from app.modules.registry import get_module_registry

    types = {ArtefactType.REQUIREMENT.value, ArtefactType.REQUIREMENT_ACTION.value}
    for definition in get_module_registry().values():
        if definition.artefact_types and is_module_enabled(db, organization_id, definition.key):
            types.update(definition.artefact_types)
    return sorted(types, key=lambda t: get_artefact_type_label(t).lower())


def get_artefact_rules(db: Session, organization_id: uuid.UUID) -> dict[str, set[uuid.UUID]]:
    """`{artefact_type: permitted link type ids}` for every rule of the organisation."""
    rules = db.scalars(
        select(ArtefactTypeLinkRule).where(ArtefactTypeLinkRule.organization_id == organization_id)
    ).all()
    return {rule.artefact_type: {entry.link_type_id for entry in rule.allowed_link_types} for rule in rules}


def validate_link_allowed(
    db: Session,
    *,
    link_type: RequirementLinkTypeDefinition,
    source_type: str,
    target_type: str,
    rules: dict[str, set[uuid.UUID]] | None = None,
) -> None:
    """Checks a link of `link_type` from `source_type` to `target_type` against
    the link type's own restriction and both ends' artefact-type rules.

    Args:
        db: Active session.
        link_type: The link type being used.
        source_type: The link's source artefact type.
        target_type: The link's target artefact type.
        rules: Pre-loaded `get_artefact_rules` result, to avoid a query per call.

    Raises:
        LinkRuleError: If any of the three rules forbids it; the message says which.
    """
    name = link_type.forward_name
    if link_type.allowed_source_types is not None and source_type not in link_type.allowed_source_types:
        raise LinkRuleError(
            f'"{name}" links cannot start from a {get_artefact_type_label(source_type).lower()} '
            f"(allowed: {_labels(link_type.allowed_source_types)})."
        )
    if link_type.allowed_target_types is not None and target_type not in link_type.allowed_target_types:
        raise LinkRuleError(
            f'"{name}" links cannot point at a {get_artefact_type_label(target_type).lower()} '
            f"(allowed: {_labels(link_type.allowed_target_types)})."
        )
    held = rules if rules is not None else get_artefact_rules(db, link_type.organization_id)
    for artefact_type in dict.fromkeys((source_type, target_type)):
        permitted = held.get(artefact_type)
        if permitted is not None and link_type.id not in permitted:
            raise LinkRuleError(
                f"{get_artefact_type_label(artefact_type)} links are limited to specific link types, "
                f'and "{name}" is not one of them.'
            )


def _labels(types: Iterable[str]) -> str:
    """Comma-separated display labels of artefact types, for error messages."""
    return ", ".join(get_artefact_type_label(t) for t in types)


@dataclass(frozen=True)
class LinkTypeOption:
    """One way to use a link type from an artefact's page.

    Attributes:
        link_type: The link type.
        outgoing: True when the page's artefact is the link's source (read with
            the forward phrase), false when it is the target (reverse phrase).
        phrase: The phrase to show for this orientation.
        other_types: Artefact types that may sit at the other end, after the link
            type's restriction and both ends' rules.
    """

    link_type: RequirementLinkTypeDefinition
    outgoing: bool
    phrase: str
    other_types: tuple[str, ...]


def list_usable_link_types(
    db: Session,
    organization_id: uuid.UUID,
    artefact_type: str,
    *,
    candidate_types: Collection[str],
    other_type: str | None = None,
) -> list[LinkTypeOption]:
    """The link types usable from an artefact of `artefact_type`, with the
    orientation and the artefact types they can reach.

    Dedicated types (fixed meaning, own action) are never offered. A symmetric
    type is offered once, from the source side, unless only the other
    orientation can reach some type.

    Args:
        db: Active session.
        organization_id: The organisation whose link types and rules apply.
        artefact_type: The page's artefact type.
        candidate_types: Artefact types that can exist at the other end (those
            whose module is enabled for the project).
        other_type: Narrow to options that can reach this type.

    Returns:
        Options in the organisation's link-type order.
    """
    rules = get_artefact_rules(db, organization_id)

    def permits(side_type: str, link_type: RequirementLinkTypeDefinition) -> bool:
        """Whether `side_type`'s rule (if any) lets it use `link_type`."""
        permitted = rules.get(side_type)
        return permitted is None or link_type.id in permitted

    link_types = db.scalars(
        select(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
        .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
    ).all()
    options: list[LinkTypeOption] = []
    for link_type in link_types:
        if link_type.dedicated_endpoint or not permits(artefact_type, link_type):
            continue
        reach: dict[bool, tuple[str, ...]] = {}
        for outgoing in (True, False):
            near = link_type.allowed_source_types if outgoing else link_type.allowed_target_types
            far = link_type.allowed_target_types if outgoing else link_type.allowed_source_types
            if near is not None and artefact_type not in near:
                continue
            reach[outgoing] = tuple(
                t for t in sorted(candidate_types) if (far is None or t in far) and permits(t, link_type)
            )
        for outgoing, others in reach.items():
            if not others or (other_type is not None and other_type not in others):
                continue
            if (
                not outgoing
                and link_type.forward_name == link_type.reverse_name
                and reach.get(True)
                and set(others) <= set(reach[True])
            ):
                continue
            options.append(
                LinkTypeOption(
                    link_type=link_type, outgoing=outgoing,
                    phrase=link_type.forward_name if outgoing else link_type.reverse_name, other_types=others,
                )
            )
    return options


def set_artefact_rule(
    db: Session, organization_id: uuid.UUID, artefact_type: str, link_type_ids: Collection[uuid.UUID]
) -> ArtefactTypeLinkRule:
    """Creates or replaces the rule for `artefact_type`.

    Args:
        db: Active session; flushed, not committed.
        organization_id: The owning organisation.
        artefact_type: A registered artefact type.
        link_type_ids: The permitted link types; must be a non-empty set of the
            organisation's own link types.

    Returns:
        The rule.

    Raises:
        ValueError: If the type is unregistered, the list is empty, or an id is not
            one of the organisation's link types.
    """
    if artefact_type not in get_all_registered_artefact_types():
        raise ValueError(f"Unknown artefact type: {artefact_type}.")
    wanted = set(link_type_ids)
    if not wanted:
        raise ValueError("A rule must allow at least one link type; remove the rule to allow any.")
    owned = set(
        db.scalars(
            select(RequirementLinkTypeDefinition.id).where(
                RequirementLinkTypeDefinition.organization_id == organization_id,
                RequirementLinkTypeDefinition.id.in_(wanted),
            )
        ).all()
    )
    if owned != wanted:
        raise ValueError("Every link type must be a link type of this organisation.")
    rule = db.scalar(
        select(ArtefactTypeLinkRule).where(
            ArtefactTypeLinkRule.organization_id == organization_id, ArtefactTypeLinkRule.artefact_type == artefact_type
        )
    )
    if rule is None:
        rule = ArtefactTypeLinkRule(organization_id=organization_id, artefact_type=artefact_type)
        db.add(rule)
    rule.allowed_link_types = [ArtefactTypeLinkRuleEntry(link_type_id=i) for i in sorted(wanted, key=str)]
    db.flush()
    return rule


def clear_artefact_rule(db: Session, organization_id: uuid.UUID, artefact_type: str) -> bool:
    """Removes the rule for `artefact_type` (any link type allowed again).

    Returns:
        Whether a rule existed.
    """
    rule = db.scalar(
        select(ArtefactTypeLinkRule).where(
            ArtefactTypeLinkRule.organization_id == organization_id, ArtefactTypeLinkRule.artefact_type == artefact_type
        )
    )
    if rule is None:
        return False
    db.delete(rule)
    db.flush()
    return True
