"""
Module: modules.traceability.rules

Traceability rules of governance: which links a record of one type is expected to carry, owned by a governance profile or by
a project. Registered as the `traceability_rules` part's profile contributor and project bundle entries.

Responsibilities:
- Validate and store a rule (`create_rule`, `update_rule`, `delete_rule`): the record type and sub-type, the `applies_when`
  and `requires` trees (`rule_tree`) against what the owner may name, the enforcement level, and one audit event each (keys
  and names only).
- Resolve the rules in effect for a project (`effective_rules`): the rules of the profiles that apply, then the project's
  own, or when it has none the nearest ancestor's, with where each came from, whether an Enforced profile binds it and
  whether the project has hidden it.
- Hide a rule an optional profile gives a project and restore it (`hide_rule`, `restore_rules`).
- Derive the requirement hierarchy a project's rules describe (`hierarchy`).
- Describe a rule's problems (`rule_problems`) and evaluate it (`evaluate`).
- Count, export and import a profile's rules and a project's own rules and hidden rules, naming link types by name.

Design decisions:
- Rules are the only hierarchy: "X must trace to Y" is a rule, a multi-level chain is one rule per level and the hierarchy is
  derived from the rules, never stored. An edge runs from the record that links (the child) to the record it links to (the
  parent), following the link's own direction.
- Rules accumulate: a project holds the rules of every profile that applies and its own, and each is evaluated on its own. A
  project's own rules replace the nearest ancestor's (the nested fallback used by every project-scoped definition), so a child
  with no rules follows its parent's and a child that sets any sets all of its own.
- A project hides a rule only when an optional profile (Default or Opt-in) gave it; a rule of an Enforced profile binds the
  project and cannot be hidden (an organisation's requirement is not the project's to waive). The tombstone is a
  `ProjectDefinitionSuppression` row, removed with the rule.
- A rule that names something no longer available (a record type, a link type, a field) is kept and reported as a problem; it
  is never evaluated and never fails the page.
- A rule owned by a profile names only organisation-wide link types, since a project-local type exists in one project's tree.
- Link types are stored by id and travel in bundles by name; a rule whose link type is unknown in the target organisation is
  reported and not imported, since importing it without the link type would make the rule weaker.
- Import writes rules without per-rule audit events: the import itself is the recorded act.

Dependencies: `rule_tree`, `rule_evaluation`, `profile_resolution`, `modules.registry`,
`services.definition_suppression`, `services.link_type_scope`, `services.project_hierarchy`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules import registry
from app.modules.traceability import rule_evaluation, rule_tree
from app.modules.traceability.enums import ProfileMode, RuleLevel
from app.modules.traceability.models import (
    RULE_DESCRIPTION_MAX_LENGTH,
    RULE_NAME_MAX_LENGTH,
    GovernanceProfile,
    GovernanceTraceabilityRule,
    TraceabilityException,
)
from app.modules.traceability.profile_resolution import applicable_profiles
from app.modules.traceability.rule_tree import Node, RuleTreeError
from app.services import definition_suppression, record_summaries, requirement_types
from app.services.audit import log_event
from app.services.link_type_scope import usable_type_ids
from app.services.project_hierarchy import get_project_chain_ids

RULE_AUDIT_ENTITY_TYPE = "governance_traceability_rule"
RULE_KIND = "traceability_rule"
KIND_RULES = "traceability_rules"
PROJECT_ROWS_KEY = "governance_traceability_rules"
HIDDEN_KEY = "governance_traceability_hidden_rules"

definition_suppression.register_definition_kind(RULE_KIND)

#: How many rules one owner may hold (a guard against a runaway import, not a design limit).
MAX_RULES_PER_OWNER = 200

Source = Literal["profile", "project", "parent_project"]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


@dataclass(frozen=True)
class EffectiveRule:
    """One rule in effect for a project with where it came from.

    Attributes:
        rule: The rule row.
        source: `profile` (a governance profile's), `project` (the project's own) or `parent_project` (the nearest ancestor's).
        source_name: The profile's name, or the ancestor project's name; `None` for the project's own.
        enforced: An Enforced profile gave the rule, so the project cannot hide or relax it.
        hidden: The project has hidden the rule.
    """

    rule: GovernanceTraceabilityRule
    source: Source
    source_name: str | None
    enforced: bool
    hidden: bool

    @property
    def active(self) -> bool:
        """Whether the rule is evaluated: enabled and not hidden."""
        return self.rule.enabled and not self.hidden


# --- validation ------------------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise _unprocessable("A rule needs a name.")
    if len(cleaned) > RULE_NAME_MAX_LENGTH:
        raise _unprocessable(f"A rule name may be at most {RULE_NAME_MAX_LENGTH} characters.")
    return cleaned


def _clean_description(description: str) -> str:
    cleaned = description.strip()
    if len(cleaned) > RULE_DESCRIPTION_MAX_LENGTH:
        raise _unprocessable(f"A rule description may be at most {RULE_DESCRIPTION_MAX_LENGTH} characters.")
    return cleaned


def _clean_level(value: str) -> str:
    try:
        return RuleLevel(value).value
    except ValueError:
        raise _unprocessable("The enforcement level must be informational, warning or required.") from None


def _clean_subtype(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if len(cleaned) > rule_tree.MAX_TEXT_VALUE:
        raise _unprocessable(f"A sub-type may be at most {rule_tree.MAX_TEXT_VALUE} characters.")
    return cleaned


def _check_source(source_type: str) -> None:
    """Raises 422 unless `source_type` is a registered record type whose records can be listed."""
    if source_type not in registry.get_linkable_artefact_types() or not record_summaries.has_summaries(source_type):
        raise _unprocessable(f"{source_type!r} is not a record type a rule can apply to.")


def link_type_ids_for(db: Session, organization_id: uuid.UUID, project: Project | None) -> set[uuid.UUID]:
    """The link types a rule of this owner may name: a project's usable types, or an organisation profile's organisation-wide ones."""
    if project is not None:
        return usable_type_ids(db, project)
    return set(db.scalars(select(RequirementLinkTypeDefinition.id).where(
        RequirementLinkTypeDefinition.organization_id == organization_id, RequirementLinkTypeDefinition.project_id.is_(None),
    )))


def vocabulary(db: Session, organization_id: uuid.UUID, project: Project | None, source_type: str) -> rule_tree.Vocabulary:
    """What a rule of this owner and source type may name, for `rule_tree` validation."""
    return rule_tree.Vocabulary(
        artefact_types=registry.get_linkable_artefact_types(),
        fields={key: (f.value_kind, f.artefact_types) for key, (_module, f) in registry.get_rule_condition_fields().items()},
        link_type_ids=link_type_ids_for(db, organization_id, project), source_type=source_type,
    )


def parse_trees(
    db: Session, organization_id: uuid.UUID, project: Project | None, source_type: str, applies_when: Any, requires: Any,
) -> tuple[Node | None, Node]:
    """Parses and validates a rule's two trees against what its owner may name.

    Raises:
        HTTPException: 422 with the fault and its place in the tree.
    """
    vocab = vocabulary(db, organization_id, project, source_type)
    try:
        return rule_tree.parse_applies_when(applies_when, vocab), rule_tree.parse_requires(requires, vocab)
    except RuleTreeError as error:
        where = f" (part {error.path})" if error.path else ""
        raise _unprocessable(f"{error}{where}") from None


def _require_unique_name(
    db: Session, *, profile_id: uuid.UUID | None, project_id: uuid.UUID | None, name: str, except_id: uuid.UUID | None = None,
) -> None:
    query = select(GovernanceTraceabilityRule.id).where(func.lower(GovernanceTraceabilityRule.name) == name.lower())
    query = query.where(
        GovernanceTraceabilityRule.profile_id == profile_id if profile_id is not None
        else GovernanceTraceabilityRule.project_id == project_id
    )
    if except_id is not None:
        query = query.where(GovernanceTraceabilityRule.id != except_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A rule named {name!r} already exists here.")


def _owner_count(db: Session, *, profile_id: uuid.UUID | None, project_id: uuid.UUID | None) -> int:
    query = select(func.count()).select_from(GovernanceTraceabilityRule)
    return db.scalar(
        query.where(GovernanceTraceabilityRule.profile_id == profile_id if profile_id is not None
                    else GovernanceTraceabilityRule.project_id == project_id)
    ) or 0


# --- writes ----------------------------------------------------------------------------------------


def _detail(rule: GovernanceTraceabilityRule, **extra: Any) -> dict[str, Any]:
    """Audit detail: the rule's name, type, level and state (never record content)."""
    return {
        "name": rule.name, "source_type": rule.source_type, "source_subtype": rule.source_subtype, "level": rule.level,
        "enabled": rule.enabled, **extra,
    }


def _audit(
    db: Session, rule: GovernanceTraceabilityRule, action: str, actor_id: uuid.UUID | None, organization_id: uuid.UUID, **extra: Any,
) -> None:
    log_event(
        db, entity_type=RULE_AUDIT_ENTITY_TYPE, entity_id=rule.id, action=action, actor_id=actor_id,
        organization_id=organization_id, project_id=rule.project_id,
        detail=_detail(rule, owner="profile" if rule.profile_id is not None else "project", **extra),
    )


def create_rule(
    db: Session, *, profile: GovernanceProfile | None = None, project: Project | None = None, actor_id: uuid.UUID | None, name: str,
    description: str, source_type: str, source_subtype: str | None, level: str, enabled: bool, applies_when: Any, requires: Any,
    audited: bool = True,
) -> GovernanceTraceabilityRule:
    """Creates a rule owned by a profile or by a project (exactly one).

    Args:
        db: Active session (not committed).
        profile: The owning profile, or `None`.
        project: The owning project, or `None`.
        actor_id: The acting user.
        name: Unique among the owner's rules, ignoring case.
        description: A short summary.
        source_type: The record type the rule applies to.
        source_subtype: A sub-type to limit it to, or `None`.
        level: A `RuleLevel` value.
        enabled: Whether the rule is evaluated.
        applies_when: The scope tree document, or `None`.
        requires: The requirement tree document.
        audited: Whether to record an audit event; a bundle import passes `False` because the import is the recorded act.

    Returns:
        The stored rule.

    Raises:
        HTTPException: 422 for a name, type, level or tree that is not valid; 409 for a duplicate name or an owner at the limit.
    """
    if profile is not None and project is None:
        organization_id = profile.organization_id
    elif project is not None and profile is None:
        organization_id = project.organization_id
    else:
        raise ValueError("A rule has exactly one owner.")
    owner = {"profile_id": profile.id if profile is not None else None, "project_id": project.id if project is not None else None}
    cleaned = _clean_name(name)
    _check_source(source_type)
    _require_unique_name(db, name=cleaned, **owner)
    if _owner_count(db, **owner) >= MAX_RULES_PER_OWNER:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_RULES_PER_OWNER} rules can be held here.")
    scope, requirement = parse_trees(db, organization_id, project, source_type, applies_when, requires)
    last = db.scalar(select(func.max(GovernanceTraceabilityRule.sort_order)).where(
        GovernanceTraceabilityRule.profile_id == owner["profile_id"] if profile is not None
        else GovernanceTraceabilityRule.project_id == owner["project_id"]
    ))
    rule = GovernanceTraceabilityRule(
        **owner, name=cleaned, description=_clean_description(description), source_type=source_type,
        source_subtype=_clean_subtype(source_subtype), level=_clean_level(level), enabled=enabled,
        sort_order=0 if last is None else last + 1,
        applies_when=None if scope is None else rule_tree.to_json(scope), requires=rule_tree.to_json(requirement),
        schema_version=rule_tree.SCHEMA_VERSION,
    )
    db.add(rule)
    db.flush()
    if audited:
        _audit(db, rule, "created", actor_id, organization_id)
    return rule


def _owner_project(db: Session, rule: GovernanceTraceabilityRule) -> tuple[uuid.UUID, Project | None]:
    """The organisation and, for a project's rule, the project that own `rule`."""
    if rule.project_id is not None:
        project = db.get(Project, rule.project_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
        return project.organization_id, project
    profile = db.get(GovernanceProfile, rule.profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    return profile.organization_id, None


def update_rule(db: Session, *, rule: GovernanceTraceabilityRule, actor_id: uuid.UUID, changes: Mapping[str, Any]) -> GovernanceTraceabilityRule:
    """Changes the fields named in `changes` (`name`, `description`, `source_type`, `source_subtype`, `level`, `enabled`,
    `sort_order`, `applies_when`, `requires`); a field left out is kept, and `applies_when` set to `None` removes the scope.

    Raises:
        HTTPException: As `create_rule`.
    """
    organization_id, project = _owner_project(db, rule)
    new_type = changes.get("source_type", rule.source_type)
    if "source_type" in changes:
        _check_source(new_type)
    if "name" in changes:
        cleaned = _clean_name(changes["name"])
        _require_unique_name(db, profile_id=rule.profile_id, project_id=rule.project_id, name=cleaned, except_id=rule.id)
        rule.name = cleaned
    if "description" in changes:
        rule.description = _clean_description(changes["description"])
    if "level" in changes:
        rule.level = _clean_level(changes["level"])
    if "enabled" in changes:
        rule.enabled = bool(changes["enabled"])
    if "sort_order" in changes:
        rule.sort_order = int(changes["sort_order"])
    if "source_subtype" in changes:
        rule.source_subtype = _clean_subtype(changes["source_subtype"])
    trees_changed = {"source_type", "applies_when", "requires"} & set(changes)
    if trees_changed:
        scope, requirement = parse_trees(
            db, organization_id, project, new_type,
            changes["applies_when"] if "applies_when" in changes else rule.applies_when,
            changes["requires"] if "requires" in changes else rule.requires,
        )
        rule.source_type = new_type
        rule.applies_when = None if scope is None else rule_tree.to_json(scope)
        rule.requires = rule_tree.to_json(requirement)
        rule.schema_version = rule_tree.SCHEMA_VERSION
    db.flush()
    _audit(db, rule, "updated", actor_id, organization_id, changed=sorted(changes))
    return rule


def delete_rule(db: Session, *, rule: GovernanceTraceabilityRule, actor_id: uuid.UUID) -> None:
    """Deletes a rule and every project's hiding of it."""
    organization_id, _project = _owner_project(db, rule)
    _audit(db, rule, "deleted", actor_id, organization_id)
    _keep_rule_names(db, [rule.id])
    definition_suppression.forget_definition(db, RULE_KIND, rule.id)
    db.delete(rule)
    db.flush()


def forget_profile_rules(db: Session, profile_id: uuid.UUID) -> None:
    """Removes every project's hiding of the rules a profile owns, before the profile (and so its rules) is deleted."""
    owned = list(db.scalars(select(GovernanceTraceabilityRule.id).where(GovernanceTraceabilityRule.profile_id == profile_id)))
    _keep_rule_names(db, owned)
    for rule_id in owned:
        definition_suppression.forget_definition(db, RULE_KIND, rule_id)


def _keep_rule_names(db: Session, rule_ids: Sequence[uuid.UUID]) -> None:
    """Writes each rule's current name onto the exceptions to it, which outlive the rule and read it by that name."""
    if not rule_ids:
        return
    db.execute(
        update(TraceabilityException).where(TraceabilityException.rule_id.in_(rule_ids)).values(
            rule_name=select(GovernanceTraceabilityRule.name)
            .where(GovernanceTraceabilityRule.id == TraceabilityException.rule_id).scalar_subquery(),
            updated_at=TraceabilityException.updated_at,
        )
    )


# --- reading ---------------------------------------------------------------------------------------


def profile_rules(db: Session, profile_id: uuid.UUID) -> list[GovernanceTraceabilityRule]:
    """A profile's rules in display order."""
    return list(db.scalars(
        select(GovernanceTraceabilityRule).where(GovernanceTraceabilityRule.profile_id == profile_id)
        .order_by(GovernanceTraceabilityRule.sort_order, func.lower(GovernanceTraceabilityRule.name))
    ))


def own_rules(db: Session, project_id: uuid.UUID) -> list[GovernanceTraceabilityRule]:
    """A project's own rules in display order."""
    return list(db.scalars(
        select(GovernanceTraceabilityRule).where(GovernanceTraceabilityRule.project_id == project_id)
        .order_by(GovernanceTraceabilityRule.sort_order, func.lower(GovernanceTraceabilityRule.name))
    ))


def effective_rules(db: Session, project: Project) -> list[EffectiveRule]:
    """Every rule in effect for a project, hidden ones included and flagged.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        The rules of the profiles that apply (Enforced first, then Default, then Opt-in, each by name), then the project's own
        rules or, when it has none, the nearest ancestor's that has any; each in display order.
    """
    applied = applicable_profiles(db, project.id)
    out: list[EffectiveRule] = []
    if applied:
        hidden = definition_suppression.get_suppressed_ids(db, project.id, RULE_KIND)
        rows = db.scalars(
            select(GovernanceTraceabilityRule).where(GovernanceTraceabilityRule.profile_id.in_([a.profile_id for a in applied]))
            .order_by(GovernanceTraceabilityRule.sort_order, func.lower(GovernanceTraceabilityRule.name))
        )
        by_profile: dict[uuid.UUID, list[GovernanceTraceabilityRule]] = defaultdict(list)
        for row in rows:
            if row.profile_id is not None:
                by_profile[row.profile_id].append(row)
        for profile in applied:
            enforced = profile.mode == ProfileMode.ENFORCED.value
            out.extend(
                EffectiveRule(rule, "profile", profile.name, enforced, not enforced and rule.id in hidden)
                for rule in by_profile.get(profile.profile_id, [])
            )
    for depth, owner_id in enumerate(get_project_chain_ids(db, project.id)):
        found = own_rules(db, owner_id)
        if found:
            name = None if depth == 0 else db.scalar(select(Project.name).where(Project.id == owner_id))
            source: Source = "project" if depth == 0 else "parent_project"
            out.extend(EffectiveRule(rule, source, name, False, False) for rule in found)
            break
    return out


def get_rule_in_project(db: Session, project: Project, rule_id: uuid.UUID) -> EffectiveRule | None:
    """The effective entry for a rule id among the project's rules, or `None`."""
    return next((e for e in effective_rules(db, project) if e.rule.id == rule_id), None)


def get_profile_rule(db: Session, profile_id: uuid.UUID, rule_id: uuid.UUID) -> GovernanceTraceabilityRule | None:
    """A profile's rule by id, or `None` (also for a rule of another owner)."""
    rule = db.get(GovernanceTraceabilityRule, rule_id)
    return rule if rule is not None and rule.profile_id == profile_id else None


def get_own_rule(db: Session, project_id: uuid.UUID, rule_id: uuid.UUID) -> GovernanceTraceabilityRule | None:
    """A project's own rule by id, or `None` (also for a rule of another owner)."""
    rule = db.get(GovernanceTraceabilityRule, rule_id)
    return rule if rule is not None and rule.project_id == project_id else None


def parsed(rule: GovernanceTraceabilityRule) -> tuple[Node | None, Node] | None:
    """The rule's trees parsed structurally (no vocabulary check), or `None` for a stored document that no longer parses."""
    try:
        return rule_tree.parse_applies_when(rule.applies_when), rule_tree.parse_requires(rule.requires)
    except RuleTreeError:
        return None


def problems_for_rules(
    db: Session, rules: Sequence[GovernanceTraceabilityRule], organization_id: uuid.UUID, project: Project | None,
) -> dict[uuid.UUID, list[str]]:
    """Why each stored rule cannot be evaluated or does not match what exists: an unregistered record type or field, a link
    type its owner cannot use, or a document that does not parse.

    Args:
        db: Active session (read only).
        rules: The rules, all of one owner.
        organization_id: The owner's organisation.
        project: The owning project, or `None` for a profile's rules (organisation-wide link types only).

    Returns:
        `{rule id: problems}`; a rule with none is absent. The owner's vocabulary is read once for all the rules.
    """
    base = vocabulary(db, organization_id, project, "")
    found: dict[uuid.UUID, list[str]] = {}
    for rule in rules:
        vocab = replace(base, source_type=rule.source_type)
        try:
            rule_tree.parse_applies_when(rule.applies_when, vocab)
            rule_tree.parse_requires(rule.requires, vocab)
        except RuleTreeError as error:
            found[rule.id] = [f"{error}" + (f" (part {error.path})" if error.path else "")]
            continue
        if not record_summaries.has_summaries(rule.source_type):
            found[rule.id] = [f"The record type {rule.source_type!r} is not available."]
    return found


def evaluate(
    db: Session, project: Project, rule: GovernanceTraceabilityRule, *, record_ids: Collection[uuid.UUID] | None = None,
) -> rule_evaluation.RuleEvaluation:
    """Evaluates one rule for the project's records, or only `record_ids` (`rule_evaluation.evaluate_rule`); a stored rule
    that no longer parses is reported as a problem."""
    trees = parsed(rule)
    if trees is None:
        return rule_evaluation.RuleEvaluation(source_total=0, problems=("The rule's definition can no longer be read.",))
    scope, requirement = trees
    return rule_evaluation.evaluate_rule(
        db, project.id, source_type=rule.source_type, source_subtype=rule.source_subtype, applies_when=scope,
        requires=requirement, record_ids=record_ids,
    )


# --- hide and restore ------------------------------------------------------------------------------


def hide_rule(db: Session, *, project: Project, rule_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Hides a rule an optional profile gives the project.

    Raises:
        HTTPException: 404 for a rule that is not one of the project's profile rules; 409 for a rule of an Enforced profile.
    """
    entry = get_rule_in_project(db, project, rule_id)
    if entry is None or entry.source != "profile":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    if entry.enforced:
        raise HTTPException(status.HTTP_409_CONFLICT, "A rule of an enforced profile cannot be hidden by a project.")
    if definition_suppression.hide_definition(db, project.id, RULE_KIND, rule_id):
        _audit(db, entry.rule, "hidden", actor_id, project.organization_id, hidden_in=str(project.id))


def restore_rules(db: Session, *, project: Project, rule_ids: set[uuid.UUID] | None, actor_id: uuid.UUID) -> int:
    """Shows hidden profile rules in the project again.

    Args:
        rule_ids: The rules to restore, or `None` for every hidden rule.

    Returns:
        How many were restored.
    """
    restored = definition_suppression.restore_definitions(db, project.id, RULE_KIND, rule_ids)
    for rule_id in sorted(restored, key=str):
        rule = db.get(GovernanceTraceabilityRule, rule_id)
        if rule is not None:
            _audit(db, rule, "restored", actor_id, project.organization_id, restored_in=str(project.id))
    return len(restored)


# --- the hierarchy ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class HierarchyNode:
    """A record type, or a sub-type of one, that rules relate.

    Attributes:
        artefact_type: The record type.
        subtype: The sub-type, or `None` for the type as a whole.
        rank: The rank of the requirement type of that name (lower is higher), or `None`.
    """

    artefact_type: str
    subtype: str | None
    rank: int | None = None


@dataclass(frozen=True)
class HierarchyEdge:
    """A rule's requirement that one kind of record links to another.

    Attributes:
        child: The kind of record whose link is required, following the link's direction (its source).
        parent: The kind of record linked to (the link's target).
        rule_id: The rule.
        rule_name: The rule's name.
        level: The rule's enforcement level.
        minimum: The leaf's minimum.
        optional: The leaf sits in an `any` group, so it is one of several ways to satisfy the rule.
        rank_conflict: Both ends are ranked requirement types and the child outranks its parent.
    """

    child: HierarchyNode
    parent: HierarchyNode
    rule_id: uuid.UUID
    rule_name: str
    level: str
    minimum: int
    optional: bool
    rank_conflict: bool


@dataclass(frozen=True)
class Hierarchy:
    """The traceability hierarchy a project's rules describe.

    Attributes:
        nodes: Every kind of record the rules relate, in a stable order.
        edges: One per leaf and target of an active rule.
        roots: The kinds that are linked to and link to nothing.
    """

    nodes: tuple[HierarchyNode, ...]
    edges: tuple[HierarchyEdge, ...]
    roots: tuple[HierarchyNode, ...]


def _leaf_edges(
    node: Node, source: HierarchyNode, ranks: Mapping[str, int], rule: GovernanceTraceabilityRule, *, optional: bool = False,
) -> list[HierarchyEdge]:
    """The edges of one requirement tree: one per target of each link leaf."""
    if isinstance(node, rule_tree.Group):
        inner = optional or node.op == "any"
        return [e for child in node.children for e in _leaf_edges(child, source, ranks, rule, optional=inner)]
    if not isinstance(node, rule_tree.LinkLeaf):
        return []
    edges = []
    for target in node.targets:
        other = HierarchyNode(target.artefact_type, target.subtype, _rank(ranks, target.artefact_type, target.subtype))
        child, parent = (source, other) if node.direction == "outgoing" else (other, source)
        conflict = child.rank is not None and parent.rank is not None and child.rank < parent.rank
        edges.append(HierarchyEdge(child, parent, rule.id, rule.name, rule.level, node.minimum, optional, conflict))
    return edges


def _rank(ranks: Mapping[str, int], artefact_type: str, subtype: str | None) -> int | None:
    return ranks.get(subtype.casefold()) if artefact_type == "requirement" and subtype else None


def hierarchy(db: Session, project: Project) -> Hierarchy:
    """The hierarchy the project's active rules describe.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        The kinds of record the rules relate and an edge per required link, child to parent; a rule that no longer parses is
        left out.
    """
    ranks = {
        t.name.casefold(): int(t.extras["rank"])
        for t in requirement_types.REQUIREMENT_TYPES.resolve_effective(db, project.id, project.organization_id)
        if t.extras.get("rank") is not None
    }
    edges: list[HierarchyEdge] = []
    for entry in effective_rules(db, project):
        trees = parsed(entry.rule) if entry.active else None
        if trees is None:
            continue
        source = HierarchyNode(entry.rule.source_type, entry.rule.source_subtype, _rank(ranks, entry.rule.source_type, entry.rule.source_subtype))
        edges.extend(_leaf_edges(trees[1], source, ranks, entry.rule))
    nodes = sorted({n for e in edges for n in (e.child, e.parent)}, key=lambda n: (n.artefact_type, n.subtype or ""))
    parents = {e.parent for e in edges}
    children = {e.child for e in edges}
    roots = tuple(n for n in nodes if n in parents and n not in children)
    return Hierarchy(tuple(nodes), tuple(edges), roots)


# --- bundles ---------------------------------------------------------------------------------------


def _link_type_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {row_id: name for row_id, name in db.execute(
        select(RequirementLinkTypeDefinition.id, RequirementLinkTypeDefinition.forward_name)
        .where(RequirementLinkTypeDefinition.id.in_(ids))
    ).tuples()}


def _walk_link_types(doc: Any, fn: Callable[[list[Any]], list[Any]]) -> Any:
    """A copy of a requirement document with each leaf's link type list passed through `fn`."""
    if not isinstance(doc, Mapping):
        return doc
    copy = dict(doc)
    if copy.get("op") == "link":
        types = copy.get("link_types")
        if isinstance(types, Mapping) and types.get("mode") == "types":
            copy["link_types"] = {"mode": "types", "ids": fn(list(types.get("ids") or []))}
    if isinstance(copy.get("children"), list):
        copy["children"] = [_walk_link_types(c, fn) for c in copy["children"]]
    return copy


def _export_rule(rule: GovernanceTraceabilityRule, names: Mapping[uuid.UUID, str]) -> dict[str, Any]:
    def to_names(ids: list[Any]) -> list[Any]:
        return [names.get(uuid.UUID(str(i)), "") for i in ids]

    return {
        "name": rule.name, "description": rule.description, "source_type": rule.source_type,
        "source_subtype": rule.source_subtype, "level": rule.level, "enabled": rule.enabled, "sort_order": rule.sort_order,
        "applies_when": rule.applies_when, "requires": _walk_link_types(rule.requires, to_names),
    }


def _link_type_ids_in(doc: Any) -> set[uuid.UUID]:
    """Every link type id a requirement document names."""
    found: set[uuid.UUID] = set()

    def collect(ids: list[Any]) -> list[Any]:
        found.update(uuid.UUID(str(i)) for i in ids)
        return ids

    _walk_link_types(doc, collect)
    return found


def _export(db: Session, rules: Sequence[GovernanceTraceabilityRule]) -> list[dict[str, Any]]:
    names = _link_type_names(db, {i for rule in rules for i in _link_type_ids_in(rule.requires)})
    return [_export_rule(rule, names) for rule in rules]


def _import_rule(
    db: Session, entry: Mapping[str, Any], *, organization_id: uuid.UUID, profile: GovernanceProfile | None,
    project: Project | None, warn: Callable[[str], None],
) -> None:
    """Writes one bundled rule, translating link type names to this organisation's ids. A rule that cannot be written is
    reported and left out."""
    name = str(entry.get("name", ""))
    by_name = {
        n.casefold(): i for i, n in _link_type_names(db, link_type_ids_for(db, organization_id, project)).items()
    }
    missing: list[str] = []

    def to_ids(names: list[Any]) -> list[Any]:
        ids = []
        for n in names:
            found = by_name.get(str(n).casefold())
            if found is None:
                missing.append(str(n))
            else:
                ids.append(str(found))
        return ids

    requires = _walk_link_types(entry.get("requires"), to_ids)
    if missing:
        warn(f"The traceability rule {name!r} was not imported: the link type {missing[0]!r} does not exist here.")
        return
    try:
        create_rule(
            db, profile=profile, project=project, actor_id=None, audited=False, name=name,
            description=str(entry.get("description") or ""),
            source_type=str(entry.get("source_type", "")), source_subtype=entry.get("source_subtype"),
            level=str(entry.get("level", "")), enabled=bool(entry.get("enabled", True)), applies_when=entry.get("applies_when"),
            requires=requires,
        )
    except HTTPException as error:
        warn(f"The traceability rule {name!r} was not imported: {error.detail}")


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: per profile, the traceability rules it owns."""
    return {
        profile_id: count
        for profile_id, count in db.execute(
            select(GovernanceTraceabilityRule.profile_id, func.count())
            .where(GovernanceTraceabilityRule.profile_id.in_(profile_ids)).group_by(GovernanceTraceabilityRule.profile_id)
        ).tuples()
        if profile_id is not None
    }


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one `traceability_rules` entry per rule of the profile, in display order."""
    return [{"kind": KIND_RULES, **entry} for entry in _export(db, profile_rules(db, profile_id))]


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes the bundle's rules into the profile; one that cannot be written is reported."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return
    for entry in rows:
        if entry.get("kind") != KIND_RULES:
            warn("A traceability rule entry of an unknown kind was not imported.")
            continue
        _import_rule(db, entry, organization_id=profile.organization_id, profile=profile, project=None, warn=warn)


def export_project_rows(db: Session, project: Project) -> list[dict[str, Any]]:
    """The project's own rules as bundle entries, in display order."""
    return _export(db, own_rules(db, project.id))


def import_project_rows(db: Session, project: Project, rows: Sequence[Mapping[str, Any]], warn: Callable[[str], None]) -> None:
    """Writes the bundle's entries as the project's own rules; one that cannot be written is reported."""
    for entry in rows:
        _import_rule(db, entry, organization_id=project.organization_id, profile=None, project=project, warn=warn)


def export_hidden(db: Session, project: Project) -> list[dict[str, str]]:
    """The profile rules the project hides, by profile and rule name."""
    hidden = definition_suppression.get_suppressed_ids(db, project.id, RULE_KIND)
    if not hidden:
        return []
    rows = db.execute(
        select(GovernanceProfile.name, GovernanceTraceabilityRule.name)
        .join(GovernanceTraceabilityRule, GovernanceTraceabilityRule.profile_id == GovernanceProfile.id)
        .where(GovernanceTraceabilityRule.id.in_(hidden), GovernanceProfile.organization_id == project.organization_id)
        .order_by(GovernanceProfile.name, GovernanceTraceabilityRule.name)
    ).tuples().all()
    return [{"profile": profile, "rule": rule} for profile, rule in rows]


def import_hidden(db: Session, project: Project, rows: Sequence[Mapping[str, Any]], warn: Callable[[str], None]) -> None:
    """Hides the bundle's rules in the project. A rule or profile the organisation lacks, and a rule of an Enforced profile,
    are reported and left visible."""
    for entry in rows:
        profile_name, rule_name = str(entry.get("profile", "")), str(entry.get("rule", ""))
        found = db.scalar(
            select(GovernanceTraceabilityRule).join(GovernanceProfile, GovernanceProfile.id == GovernanceTraceabilityRule.profile_id)
            .where(
                GovernanceProfile.organization_id == project.organization_id,
                func.lower(GovernanceProfile.name) == profile_name.lower(),
                func.lower(GovernanceTraceabilityRule.name) == rule_name.lower(),
            )
        )
        profile = None if found is None else db.get(GovernanceProfile, found.profile_id)
        if found is None or profile is None:
            warn(f"The traceability rule {rule_name!r} of the profile {profile_name!r} does not exist here; it was not hidden.")
        elif profile.mode == ProfileMode.ENFORCED.value:
            warn(f"The traceability rule {rule_name!r} belongs to an enforced profile and was not hidden.")
        else:
            definition_suppression.hide_definition(db, project.id, RULE_KIND, found.id)
