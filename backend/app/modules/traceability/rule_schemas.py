"""
Module: modules.traceability.rule_schemas

Request and response models of the traceability rule API: the rule tree as it crosses the wire, a rule with the facts the
screens need (its problems, where it came from, whether the project may change or hide it), the editor's options, the
preset builder, a rule's evaluation counts and the derived hierarchy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.traceability.enums import RuleLevel
from app.modules.traceability.models import RULE_DESCRIPTION_MAX_LENGTH, RULE_NAME_MAX_LENGTH


class RuleLinkTypesModel(BaseModel):
    """The links a link leaf counts: `any`, `untyped` or the listed link types (`types`, with `ids`)."""

    mode: Literal["any", "untyped", "types"] = "any"
    ids: list[UUID] | None = None


class RuleTargetModel(BaseModel):
    """A record type, optionally narrowed to a sub-type, at the other end of a link."""

    artefact_type: str
    subtype: str | None = None


class RuleNodeModel(BaseModel):
    """One part of a rule tree. `all` and `any` use `children`, `not` uses `child`, `condition` uses `field`, `operator` and
    `value`, and `link` uses `link_types`, `direction`, `targets`, `min`, `max` and `label`. The service validates which
    parts each kind may carry, against what the owner may name."""

    op: Literal["all", "any", "not", "condition", "link"]
    children: list[RuleNodeModel] | None = None
    child: RuleNodeModel | None = None
    field: str | None = None
    operator: str | None = None
    value: str | int | list[str | int] | None = None
    link_types: RuleLinkTypesModel | None = None
    direction: Literal["outgoing", "incoming"] | None = None
    targets: list[RuleTargetModel] | None = None
    min: int | None = None
    max: int | None = None
    label: str | None = None

    def document(self) -> dict[str, Any]:
        """The node as the plain document `rule_tree` parses."""
        return self.model_dump(mode="json", exclude_none=True)


class RuleCreate(BaseModel):
    """A rule to create. `level` defaults to informational, which never blocks anything."""

    name: str = Field(max_length=RULE_NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=RULE_DESCRIPTION_MAX_LENGTH)
    source_type: str
    source_subtype: str | None = None
    level: RuleLevel = RuleLevel.INFORMATIONAL
    enabled: bool = True
    applies_when: RuleNodeModel | None = None
    requires: RuleNodeModel


class RuleUpdate(BaseModel):
    """Changes to a rule: a field left out is kept; `applies_when` sent as null removes the scope."""

    name: str | None = Field(default=None, max_length=RULE_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=RULE_DESCRIPTION_MAX_LENGTH)
    source_type: str | None = None
    source_subtype: str | None = None
    level: RuleLevel | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    applies_when: RuleNodeModel | None = None
    requires: RuleNodeModel | None = None


class RuleOut(BaseModel):
    """A rule. The trees are the canonical documents (`RuleNodeModel` shape); `problems` says why a rule that no longer matches
    what exists is not evaluated."""

    id: UUID
    name: str
    description: str
    source_type: str
    source_type_label: str
    source_subtype: str | None
    level: RuleLevel
    enabled: bool
    sort_order: int
    applies_when: dict[str, Any] | None
    requires: dict[str, Any]
    problems: list[str]
    created_at: datetime
    updated_at: datetime


class EffectiveRuleOut(RuleOut):
    """A rule in effect for a project.

    Attributes:
        source: `profile`, `project` (its own) or `parent_project` (the nearest ancestor's).
        source_name: The profile or ancestor project name; null for the project's own.
        enforced: An Enforced profile gave it.
        hidden: The project has hidden it.
        can_edit: The project owns it and the caller may change it.
        can_hide: An optional profile gave it and the caller may hide it.
    """

    source: Literal["profile", "project", "parent_project"]
    source_name: str | None
    enforced: bool
    hidden: bool
    can_edit: bool
    can_hide: bool


class ProjectRulesOut(BaseModel):
    """A project's traceability rules."""

    can_manage: bool
    rules: list[EffectiveRuleOut]


class RuleRestoreSet(BaseModel):
    """The hidden rules to show again; null restores every hidden rule."""

    rule_ids: list[UUID] | None = None


class RuleFieldOptionOut(BaseModel):
    """A record property an `applies_when` condition may test."""

    key: str
    label: str
    value_kind: Literal["text", "number"]
    operators: list[str]
    artefact_types: list[str]
    options: list[str] | None


class RuleTypeOptionOut(BaseModel):
    """A record type a rule may apply to or link to, with its sub-type names."""

    artefact_type: str
    label: str
    subtypes: list[str]
    can_be_source: bool


class RuleLinkTypeOptionOut(BaseModel):
    """A link type a rule may name."""

    id: UUID
    forward_name: str
    reverse_name: str


class PresetOut(BaseModel):
    """A ready-made rule offered beside the editor."""

    key: str
    name: str
    description: str
    needs_target: bool
    needs_alternative: bool


class RuleOptionsOut(BaseModel):
    """What the rule editor may offer: record types, condition fields, link types, levels, limits and presets."""

    types: list[RuleTypeOptionOut]
    fields: list[RuleFieldOptionOut]
    link_types: list[RuleLinkTypeOptionOut]
    levels: list[RuleLevel]
    presets: list[PresetOut]
    max_depth: int
    max_nodes: int


class PresetBuildIn(BaseModel):
    """The choices a preset is built from."""

    target_type: str | None = None
    target_subtype: str | None = None
    alternative_type: str | None = None
    alternative_subtype: str | None = None
    link_type_ids: list[UUID] = Field(default_factory=list)
    minimum: int = Field(default=1, ge=1, le=1000)


class PresetBuiltOut(BaseModel):
    """A preset's `requires` tree; null for the preset that requires nothing."""

    requires: dict[str, Any] | None


class RuleLeafCountOut(BaseModel):
    """How many in-scope records meet one link leaf, and how many do not."""

    path: str
    label: str
    met: int
    unmet: int


class RuleEvaluationOut(BaseModel):
    """What a rule finds in the project: counts only, never record codes or titles.

    Attributes:
        source_total: Records of the source type (and sub-type) the project holds.
        in_scope: Records the rule applies to.
        satisfied: In-scope records that meet the rule.
        unsatisfied: In-scope records that do not.
        leaves: Per requirement leaf, the in-scope records meeting it.
        problems: Why the rule could not be evaluated.
    """

    source_total: int
    in_scope: int
    satisfied: int
    unsatisfied: int
    leaves: list[RuleLeafCountOut]
    problems: list[str]


class HierarchyNodeOut(BaseModel):
    """A kind of record the rules relate."""

    artefact_type: str
    label: str
    subtype: str | None
    rank: int | None


class HierarchyEdgeOut(BaseModel):
    """A required link from a child kind of record to a parent kind."""

    child: HierarchyNodeOut
    parent: HierarchyNodeOut
    rule_id: UUID
    rule_name: str
    level: RuleLevel
    minimum: int
    optional: bool
    rank_conflict: bool


class HierarchyOut(BaseModel):
    """The traceability hierarchy the project's rules describe."""

    nodes: list[HierarchyNodeOut]
    edges: list[HierarchyEdgeOut]
    roots: list[HierarchyNodeOut]


RuleNodeModel.model_rebuild()
