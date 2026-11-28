"""
Module: modules.traceability.rules_router

API of traceability rules, in two route groups the module's organisation and project routers include: `org_routes` (a
governance profile's rules) and `project_routes` (a project's rules in effect, its own rules, hiding and restoring a
profile's rule, the editor's options and presets, a rule's evaluation counts, records' traceability status and the derived hierarchy).

Design decisions:
- Every route needs the `traceability_rules` part to be in effect. Changing a profile's rules needs `manage_org_traceability`
  and a project's own rules `manage_project_traceability`, with no server-administrator bypass: the rules are the customer's
  process. Reading a project's rules is open to every member, because a person asking why a record is flagged needs the rule.
- A profile of another organisation is a 404, and so is a rule that is not the project's own where only its own may change.
- Hiding and restoring a profile's rule is a project decision (`manage_project_traceability`); an Enforced profile's rule is
  refused (409).
- An evaluation returns counts only and needs the `view` permission on the rule's source type, so a number never reveals
  records the caller cannot open. It evaluates the project's own links.
- A rule or record covered by an approved exception is counted and shown as `excepted`, never as met; the exception is
  named only to a caller who may read exceptions.
- A record's status needs the `view` permission on its type and the record to be one the project holds; the list of a
  type's statuses gives each record's id and counts, never another record's code or title. Neither changes anything.
- A Required rule is returned with where it is enforced, or the reason it is not, so no screen reads it as blocking when
  nothing blocks.

Dependencies: `modules.traceability.rules` (service), `rule_presets`, `services.rbac` (gates).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules import registry
from app.modules.traceability import exception_cover, rule_fields, rule_presets, rule_tree, rules
from app.modules.traceability import status as traceability_status
from app.modules.traceability._shared import (
    EXCEPTION_ARTEFACT_TYPE,
    MANAGE_ORG_TRACEABILITY,
    MANAGE_PROJECT_TRACEABILITY,
    TRACEABILITY_MODULE_KEY,
    TRACEABILITY_RULES,
)
from app.modules.traceability.enums import RuleLevel, TraceabilityState
from app.modules.traceability.models import GovernanceProfile, GovernanceTraceabilityRule
from app.modules.traceability.rule_schemas import (
    EffectiveRuleOut,
    HierarchyEdgeOut,
    HierarchyNodeOut,
    HierarchyOut,
    LeafStatusOut,
    PresetBuildIn,
    PresetBuiltOut,
    PresetOut,
    ProjectRulesOut,
    RecordStatusOut,
    RecordStatusSummaryOut,
    RuleCreate,
    RuleEvaluationOut,
    RuleExceptionOut,
    RuleFieldOptionOut,
    RuleLeafCountOut,
    RuleLinkTypeOptionOut,
    RuleOptionsOut,
    RuleOut,
    RuleRestoreSet,
    RuleStatusOut,
    RuleTypeOptionOut,
    RuleUpdate,
    TypeStatusOut,
)
from app.services import record_summaries
from app.services.lookups import project_or_404
from app.services.permissions import encode_permission
from app.services.rbac import (
    get_effective_permissions,
    permission_satisfied,
    require_org_module_enabled,
    require_org_subcomponent_enabled,
    require_permission,
    require_project_module_enabled,
    require_project_subcomponent_enabled,
)

org_routes = APIRouter()
project_routes = APIRouter()

_org_guards = [
    Depends(require_org_module_enabled(TRACEABILITY_MODULE_KEY)),
    Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, TRACEABILITY_RULES)),
]
_org_manage = require_permission(MANAGE_ORG_TRACEABILITY, server_admin_bypass=False)
_project_view = require_project_module_enabled(TRACEABILITY_MODULE_KEY)
_project_part = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, TRACEABILITY_RULES)
_project_manage = require_permission(MANAGE_PROJECT_TRACEABILITY, server_admin_bypass=False)


def _changes(payload: RuleUpdate) -> dict[str, Any]:
    """The fields a rule update names, as plain values and documents.

    Raises:
        HTTPException: 422 for a field that cannot be removed.
    """
    changes: dict[str, Any] = {}
    for key in payload.model_fields_set:
        value = getattr(payload, key)
        if key == "applies_when":
            changes[key] = None if value is None else value.document()
        elif key in ("source_subtype",):
            changes[key] = value
        elif value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The rule's {key.replace('_', ' ')} cannot be removed.")
        else:
            changes[key] = value.document() if key == "requires" else value.value if key == "level" else value
    return changes


def _rule_out(rule: GovernanceTraceabilityRule, problems: list[str]) -> dict[str, Any]:
    return {
        "id": rule.id, "name": rule.name, "description": rule.description, "source_type": rule.source_type,
        "source_type_label": registry.get_artefact_type_label(rule.source_type), "source_subtype": rule.source_subtype,
        "level": RuleLevel(rule.level), "enabled": rule.enabled, "sort_order": rule.sort_order,
        "applies_when": rule.applies_when, "requires": rule.requires, "problems": problems,
        "created_at": rule.created_at, "updated_at": rule.updated_at,
    }


def _plain_outs(db: Session, rows: list[GovernanceTraceabilityRule], organization_id: UUID, project: Project | None) -> list[RuleOut]:
    problems = rules.problems_for_rules(db, rows, organization_id, project)
    return [RuleOut(**_rule_out(r, problems.get(r.id, []))) for r in rows]


def _project_rules_out(db: Session, project: Project, user: User) -> ProjectRulesOut:
    """The project's rules in effect with their sources and the caller's rights."""
    can_manage = permission_satisfied(get_effective_permissions(db, user.id, project_id=project.id), MANAGE_PROJECT_TRACEABILITY)
    entries = rules.effective_rules(db, project)
    problems = rules.problems_for_rules(db, [e.rule for e in entries if e.source != "profile"], project.organization_id, project)
    from_profiles = [e.rule for e in entries if e.source == "profile"]
    if from_profiles:
        problems.update(rules.problems_for_rules(db, from_profiles, project.organization_id, None))
    context = traceability_status.enforcement_for(db, project)
    outs = []
    for e in entries:
        enforcement = context.for_rule(e) or traceability_status.Enforcement()
        outs.append(EffectiveRuleOut(
            **_rule_out(e.rule, problems.get(e.rule.id, [])), source=e.source, source_name=e.source_name,
            enforced=e.enforced, hidden=e.hidden, can_edit=can_manage and e.source == "project",
            can_hide=can_manage and e.source == "profile" and not e.enforced,
            enforced_at=list(enforcement.points), not_enforced_reason=enforcement.reason,
        ))
    return ProjectRulesOut(can_manage=can_manage, rules=outs)


# --- options and presets ---------------------------------------------------------------------------


def _options(db: Session, organization_id: UUID, project: Project | None) -> RuleOptionsOut:
    """What the editor may offer a rule of this owner."""
    registered = registry.get_linkable_artefact_types()
    project_id = None if project is None else project.id
    types = [
        RuleTypeOptionOut(
            artefact_type=t, label=registry.get_artefact_type_label(t),
            subtypes=rule_fields.subtype_options(db, organization_id, t, project_id),
            can_be_source=record_summaries.has_summaries(t),
        )
        for t in sorted(registered, key=lambda t: registry.get_artefact_type_label(t).casefold())
    ]
    fields = []
    for key, (_module, f) in sorted(registry.get_rule_condition_fields().items()):
        operators = rule_tree.NUMBER_OPERATORS if f.value_kind == "number" else rule_tree.TEXT_OPERATORS
        choices = f.options(db, project_id, "") if f.options is not None and project_id is not None and key != rule_fields.SUBTYPE else None
        fields.append(RuleFieldOptionOut(
            key=key, label=f.label, value_kind=f.value_kind, operators=list(operators), artefact_types=list(f.artefact_types),
            options=None if choices is None else list(choices),
        ))
    link_type_ids = rules.link_type_ids_for(db, organization_id, project)
    link_types = (
        db.scalars(
            select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.id.in_(link_type_ids))
            .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
        ).all()
        if link_type_ids else []
    )
    return RuleOptionsOut(
        types=types, fields=fields,
        link_types=[RuleLinkTypeOptionOut(id=t.id, forward_name=t.forward_name, reverse_name=t.reverse_name) for t in link_types],
        levels=list(RuleLevel),
        presets=[
            PresetOut(
                key=p.key, name=p.name, description=p.description, needs_target=p.needs_target,
                needs_alternative=p.needs_alternative,
            )
            for p in rule_presets.PRESETS
        ],
        max_depth=rule_tree.MAX_DEPTH, max_nodes=rule_tree.MAX_NODES,
    )


def _build_preset(db: Session, organization_id: UUID, project: Project | None, key: str, payload: PresetBuildIn) -> PresetBuiltOut:
    """A preset's tree, validated like a stored rule's against what the owner may name."""
    try:
        tree = rule_presets.build_preset(
            key, target_type=payload.target_type, target_subtype=payload.target_subtype,
            alternative_type=payload.alternative_type, alternative_subtype=payload.alternative_subtype,
            link_type_ids=payload.link_type_ids, minimum=payload.minimum,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    if tree is not None:
        rules.parse_trees(db, organization_id, project, "", None, tree)
    return PresetBuiltOut(requires=tree)


# --- organisation: a profile's rules ---------------------------------------------------------------


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _profile_or_404(db: Session, organization_id: UUID, profile_id: UUID) -> GovernanceProfile:
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None or profile.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    return profile


def _profile_rule_or_404(db: Session, profile: GovernanceProfile, rule_id: UUID) -> GovernanceTraceabilityRule:
    rule = rules.get_profile_rule(db, profile.id, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    return rule


@org_routes.get("/rules/options", response_model=RuleOptionsOut, dependencies=_org_guards)
def get_org_rule_options(organization_id: UUID, current_user: User = Depends(_org_manage), db: Session = Depends(get_db)) -> RuleOptionsOut:
    """What the editor may offer a profile's rule: record types, condition fields, the organisation-wide link types, levels and presets."""
    return _options(db, _org_or_404(db, organization_id).id, None)


@org_routes.post("/rules/presets/{key}", response_model=PresetBuiltOut, dependencies=_org_guards)
def build_org_rule_preset(
    organization_id: UUID, key: str, payload: PresetBuildIn, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> PresetBuiltOut:
    """Builds the `requires` tree of a preset for a profile's rule."""
    return _build_preset(db, _org_or_404(db, organization_id).id, None, key, payload)


@org_routes.get("/profiles/{profile_id}/rules", response_model=list[RuleOut], dependencies=_org_guards)
def list_profile_rules(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> list[RuleOut]:
    """A profile's traceability rules in display order."""
    profile = _profile_or_404(db, organization_id, profile_id)
    return _plain_outs(db, rules.profile_rules(db, profile.id), organization_id, None)


@org_routes.post("/profiles/{profile_id}/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED, dependencies=_org_guards)
def create_profile_rule(
    organization_id: UUID, profile_id: UUID, payload: RuleCreate, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> RuleOut:
    """Creates a rule owned by a profile."""
    profile = _profile_or_404(db, organization_id, profile_id)
    rule = rules.create_rule(
        db, profile=profile, actor_id=current_user.id, name=payload.name, description=payload.description,
        source_type=payload.source_type, source_subtype=payload.source_subtype, level=payload.level.value, enabled=payload.enabled,
        applies_when=None if payload.applies_when is None else payload.applies_when.document(), requires=payload.requires.document(),
    )
    db.commit()
    return _plain_outs(db, [rule], organization_id, None)[0]


@org_routes.get("/profiles/{profile_id}/rules/{rule_id}", response_model=RuleOut, dependencies=_org_guards)
def get_profile_rule(
    organization_id: UUID, profile_id: UUID, rule_id: UUID, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> RuleOut:
    """One of a profile's rules."""
    rule = _profile_rule_or_404(db, _profile_or_404(db, organization_id, profile_id), rule_id)
    return _plain_outs(db, [rule], organization_id, None)[0]


@org_routes.patch("/profiles/{profile_id}/rules/{rule_id}", response_model=RuleOut, dependencies=_org_guards)
def update_profile_rule(
    organization_id: UUID, profile_id: UUID, rule_id: UUID, payload: RuleUpdate,
    current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> RuleOut:
    """Changes a profile's rule."""
    rule = _profile_rule_or_404(db, _profile_or_404(db, organization_id, profile_id), rule_id)
    rules.update_rule(db, rule=rule, actor_id=current_user.id, changes=_changes(payload))
    db.commit()
    return _plain_outs(db, [rule], organization_id, None)[0]


@org_routes.delete("/profiles/{profile_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_org_guards)
def delete_profile_rule(
    organization_id: UUID, profile_id: UUID, rule_id: UUID, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> None:
    """Deletes a profile's rule; every project that hid it shows nothing for it."""
    rule = _profile_rule_or_404(db, _profile_or_404(db, organization_id, profile_id), rule_id)
    rules.delete_rule(db, rule=rule, actor_id=current_user.id)
    db.commit()


# --- project: rules in effect and its own ----------------------------------------------------------


def _own_rule_or_404(db: Session, project: Project, rule_id: UUID) -> GovernanceTraceabilityRule:
    rule = rules.get_own_rule(db, project.id, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    return rule


@project_routes.get("/rules", response_model=ProjectRulesOut, dependencies=[Depends(_project_part)])
def get_project_rules(project_id: UUID, current_user: User = Depends(_project_view), db: Session = Depends(get_db)) -> ProjectRulesOut:
    """The traceability rules in effect for the project, with where each comes from."""
    return _project_rules_out(db, project_or_404(db, project_id), current_user)


@project_routes.get("/rules/options", response_model=RuleOptionsOut, dependencies=[Depends(_project_part)])
def get_project_rule_options(project_id: UUID, current_user: User = Depends(_project_manage), db: Session = Depends(get_db)) -> RuleOptionsOut:
    """What the editor may offer a rule of the project: record types with the project's sub-types, condition fields, the usable
    link types, levels and presets."""
    project = project_or_404(db, project_id)
    return _options(db, project.organization_id, project)


@project_routes.post("/rules/presets/{key}", response_model=PresetBuiltOut, dependencies=[Depends(_project_part)])
def build_project_rule_preset(
    project_id: UUID, key: str, payload: PresetBuildIn, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> PresetBuiltOut:
    """Builds the `requires` tree of a preset for a project's rule."""
    project = project_or_404(db, project_id)
    return _build_preset(db, project.organization_id, project, key, payload)


@project_routes.get("/rules/hierarchy", response_model=HierarchyOut, dependencies=[Depends(_project_part)])
def get_project_rule_hierarchy(project_id: UUID, current_user: User = Depends(_project_view), db: Session = Depends(get_db)) -> HierarchyOut:
    """The requirement hierarchy the project's active rules describe: each kind of record linked to, and the required links between them."""
    project = project_or_404(db, project_id)
    found = rules.hierarchy(db, project)

    def node(n: rules.HierarchyNode) -> HierarchyNodeOut:
        return HierarchyNodeOut(
            artefact_type=n.artefact_type, label=registry.get_artefact_type_label(n.artefact_type), subtype=n.subtype, rank=n.rank,
        )

    return HierarchyOut(
        nodes=[node(n) for n in found.nodes], roots=[node(n) for n in found.roots],
        edges=[
            HierarchyEdgeOut(
                child=node(e.child), parent=node(e.parent), rule_id=e.rule_id, rule_name=e.rule_name, level=RuleLevel(e.level),
                minimum=e.minimum, optional=e.optional, rank_conflict=e.rank_conflict,
            )
            for e in found.edges
        ],
    )


@project_routes.post("/rules/restore", response_model=ProjectRulesOut, dependencies=[Depends(_project_part)])
def restore_project_rules(
    project_id: UUID, payload: RuleRestoreSet, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> ProjectRulesOut:
    """Shows hidden profile rules in the project again (every hidden rule when none is named)."""
    project = project_or_404(db, project_id)
    rules.restore_rules(db, project=project, rule_ids=None if payload.rule_ids is None else set(payload.rule_ids), actor_id=current_user.id)
    db.commit()
    return _project_rules_out(db, project, current_user)


@project_routes.post("/rules", response_model=EffectiveRuleOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_project_part)])
def create_project_rule(
    project_id: UUID, payload: RuleCreate, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> EffectiveRuleOut:
    """Creates a rule the project owns. Once the project has any rule of its own it no longer follows its ancestor's."""
    project = project_or_404(db, project_id)
    rule = rules.create_rule(
        db, project=project, actor_id=current_user.id, name=payload.name, description=payload.description,
        source_type=payload.source_type, source_subtype=payload.source_subtype, level=payload.level.value, enabled=payload.enabled,
        applies_when=None if payload.applies_when is None else payload.applies_when.document(), requires=payload.requires.document(),
    )
    db.commit()
    return _one(db, project, current_user, rule.id)


def _one(db: Session, project: Project, user: User, rule_id: UUID) -> EffectiveRuleOut:
    found = next((r for r in _project_rules_out(db, project, user).rules if r.id == rule_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    return found


@project_routes.get("/rules/{rule_id}", response_model=EffectiveRuleOut, dependencies=[Depends(_project_part)])
def get_project_rule(
    project_id: UUID, rule_id: UUID, current_user: User = Depends(_project_view), db: Session = Depends(get_db),
) -> EffectiveRuleOut:
    """One rule in effect for the project."""
    return _one(db, project_or_404(db, project_id), current_user, rule_id)


@project_routes.patch("/rules/{rule_id}", response_model=EffectiveRuleOut, dependencies=[Depends(_project_part)])
def update_project_rule(
    project_id: UUID, rule_id: UUID, payload: RuleUpdate, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> EffectiveRuleOut:
    """Changes a rule the project owns."""
    project = project_or_404(db, project_id)
    rule = _own_rule_or_404(db, project, rule_id)
    rules.update_rule(db, rule=rule, actor_id=current_user.id, changes=_changes(payload))
    db.commit()
    return _one(db, project, current_user, rule_id)


@project_routes.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(_project_part)])
def delete_project_rule(
    project_id: UUID, rule_id: UUID, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> None:
    """Deletes a rule the project owns."""
    project = project_or_404(db, project_id)
    rules.delete_rule(db, rule=_own_rule_or_404(db, project, rule_id), actor_id=current_user.id)
    db.commit()


@project_routes.post("/rules/{rule_id}/hide", response_model=EffectiveRuleOut, dependencies=[Depends(_project_part)])
def hide_project_rule(
    project_id: UUID, rule_id: UUID, current_user: User = Depends(_project_manage), db: Session = Depends(get_db),
) -> EffectiveRuleOut:
    """Hides a rule a Default or Opt-in profile gives the project (a rule of an Enforced profile cannot be hidden)."""
    project = project_or_404(db, project_id)
    rules.hide_rule(db, project=project, rule_id=rule_id, actor_id=current_user.id)
    db.commit()
    return _one(db, project, current_user, rule_id)


@project_routes.get("/rules/{rule_id}/evaluation", response_model=RuleEvaluationOut, dependencies=[Depends(_project_part)])
def get_project_rule_evaluation(
    project_id: UUID, rule_id: UUID, current_user: User = Depends(_project_view), db: Session = Depends(get_db),
) -> RuleEvaluationOut:
    """What a rule finds in the project: how many records it applies to, how many meet it and, per requirement, how many are met.

    Raises:
        HTTPException: 404 for a rule not in effect; 403 when the caller may not read records of the rule's source type.
    """
    project = project_or_404(db, project_id)
    entry = rules.get_rule_in_project(db, project, rule_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    held = get_effective_permissions(db, current_user.id, project_id=project.id)
    registered = entry.rule.source_type in registry.get_all_registered_artefact_types()
    if registered and not permission_satisfied(held, encode_permission(entry.rule.source_type, "view")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You may not read records of this type.")
    result = rules.evaluate(db, project, entry.rule)
    leaves: dict[str, dict[TraceabilityState, int]] = {}
    labels: dict[str, str] = {}
    for record in result.in_scope:
        for leaf in record.leaves:
            counts = leaves.setdefault(leaf.path, dict.fromkeys(TraceabilityState, 0))
            counts[leaf.state] += 1
            labels[leaf.path] = leaf.label
    covers = exception_cover.covers_for(
        db, project.id, entry.rule.source_type, [r.record_id for r in result.in_scope], {entry.rule.id: entry},
    )
    states = [
        TraceabilityState.EXCEPTED
        if r.state != TraceabilityState.MET and (r.record_id, entry.rule.id) in covers else r.state
        for r in result.in_scope
    ]
    return RuleEvaluationOut(
        source_total=result.source_total, in_scope=len(result.in_scope), satisfied=states.count(TraceabilityState.MET),
        inherited=states.count(TraceabilityState.INHERITED), excepted=states.count(TraceabilityState.EXCEPTED),
        unsatisfied=states.count(TraceabilityState.UNMET),
        leaves=[
            RuleLeafCountOut(
                path=path, label=labels[path], met=c[TraceabilityState.MET], inherited=c[TraceabilityState.INHERITED],
                unmet=c[TraceabilityState.UNMET],
            )
            for path, c in sorted(leaves.items())
        ],
        problems=list(result.problems),
    )


# --- project: records' traceability status ---------------------------------------------------------


def _require_type_view(db: Session, user: User, project: Project, artefact_type: str) -> None:
    """Raises 404 for a type that is not registered and 403 when the caller may not read its records."""
    if artefact_type not in registry.get_all_registered_artefact_types() or not record_summaries.has_summaries(artefact_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    held = get_effective_permissions(db, user.id, project_id=project.id)
    if not permission_satisfied(held, encode_permission(artefact_type, "view")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You may not read records of this type.")


@project_routes.get("/status/{artefact_type}", response_model=TypeStatusOut, dependencies=[Depends(_project_part)])
def get_type_traceability_status(
    project_id: UUID, artefact_type: str, record_id: list[UUID] | None = Query(None, max_length=500),
    current_user: User = Depends(_project_view), db: Session = Depends(get_db),
) -> TypeStatusOut:
    """The traceability status of the project's records of one type, or of the records named by `record_id`.

    Raises:
        HTTPException: 404 for a type that is not registered; 403 when the caller may not read records of it.
    """
    project = project_or_404(db, project_id)
    _require_type_view(db, current_user, project, artefact_type)
    found = traceability_status.record_statuses(db, project, artefact_type, record_id)
    return TypeStatusOut(
        artefact_type=artefact_type,
        records=[
            RecordStatusSummaryOut(
                record_id=r.record_id, status=r.status, highest_level=r.highest_level, applicable=len(r.rules),
                unmet=sum(1 for x in r.rules if x.state == TraceabilityState.UNMET),
                inherited=sum(1 for x in r.rules if x.state == TraceabilityState.INHERITED),
                excepted=sum(1 for x in r.rules if x.state == TraceabilityState.EXCEPTED),
            )
            for _, r in sorted(found.records.items(), key=lambda item: str(item[0]))
        ],
        unevaluated_rules=list(found.unevaluated),
    )


@project_routes.get("/status/{artefact_type}/{record_id}", response_model=RecordStatusOut, dependencies=[Depends(_project_part)])
def get_record_traceability_status(
    project_id: UUID, artefact_type: str, record_id: UUID,
    current_user: User = Depends(_project_view), db: Session = Depends(get_db),
) -> RecordStatusOut:
    """Every rule that applies to one record, whether it meets each requirement, and where Required rules are enforced.

    Raises:
        HTTPException: 404 for a type or record the project does not hold (an archived record has no status); 403 when
            the caller may not read records of the type.
    """
    project = project_or_404(db, project_id)
    _require_type_view(db, current_user, project, artefact_type)
    found = traceability_status.record_statuses(db, project, artefact_type, [record_id])
    record = found.records.get(record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found.")
    context = traceability_status.enforcement_for(db, project)
    held = get_effective_permissions(db, current_user.id, project_id=project.id)
    names_exceptions = permission_satisfied(held, encode_permission(EXCEPTION_ARTEFACT_TYPE, "view"))
    outs = []
    for rule in record.rules:
        enforcement = context.for_rule(rule.entry) or traceability_status.Enforcement()
        outs.append(RuleStatusOut(
            rule_id=rule.entry.rule.id, name=rule.entry.rule.name, level=rule.level, source=rule.entry.source,
            source_name=rule.entry.source_name, state=rule.state, enforced_at=list(enforcement.points),
            not_enforced_reason=enforcement.reason,
            excepted_by=None if rule.exception is None or not names_exceptions else RuleExceptionOut(
                id=rule.exception.exception_id, unique_code=rule.exception.unique_code, title=rule.exception.title,
                expires_on=rule.exception.expires_on, rule_changed=rule.exception.rule_changed,
            ),
            leaves=[
                LeafStatusOut(
                    path=leaf.path, label=leaf.label, count=leaf.count, confirmed=leaf.confirmed, minimum=leaf.minimum,
                    maximum=leaf.maximum, state=leaf.state,
                )
                for leaf in rule.leaves
            ],
        ))
    return RecordStatusOut(
        record_id=record_id, status=record.status, highest_level=record.highest_level, rules=outs,
        unevaluated_rules=list(found.unevaluated),
    )
