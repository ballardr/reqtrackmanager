"""
Module: schemas.lifecycle

Request and response models for lifecycle configuration (`routers.lifecycles`): the optional states a project uses,
the states an organisation requires and the projects it exempts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LifecycleStateOut(BaseModel):
    """One state of a record type's path.

    Attributes:
        key: The state's stored value.
        label: Its formal label.
        optional: Whether a project may turn it off.
        gated: Whether moving into it needs a permission or a second person's decision.
    """

    key: str
    label: str
    optional: bool = False
    gated: bool = False


class ProjectLifecycleOut(BaseModel):
    """One record type's lifecycle as it applies to a project.

    Attributes:
        artefact_type: The registered record type.
        label: The record type's singular name.
        module_key: The module that owns the type.
        module_name: That module's display name.
        path: The main path in order.
        off_path: States outside the main path (rejected, retired and similar).
        own_disabled: The project's own turned-off states, or `None` when it follows its ancestor (or the default).
        disabled: The states that are off here (own or inherited, without the states the organisation requires).
        required: The states that must stay on in this project: the organisation's (unless it is exempt) and those the
            governance profiles that apply to the project require.
        exempt: Whether the organisation's requirement does not bind this project.
        required_by_profiles: `{state: names of the governance profiles requiring it}`, so a screen names the source.
        source: Where the project's choice comes from: `project`, `parent_project` or `default`.
        transitions: Every state's legal next states with the turned-off states stepped over.
        skip_transitions: `{state: {target: [states passed over]}}` for the later steps a record may be moved to by
            skipping steps; empty unless the project allows skipping and the type supports it.
    """

    artefact_type: str
    label: str
    module_key: str
    module_name: str
    path: list[LifecycleStateOut]
    off_path: list[LifecycleStateOut]
    own_disabled: list[str] | None
    disabled: list[str]
    required: list[str]
    exempt: bool
    required_by_profiles: dict[str, list[str]] = Field(default_factory=dict)
    source: Literal["project", "parent_project", "default"]
    transitions: dict[str, list[str]]
    skip_transitions: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


class ProjectSkipOut(BaseModel):
    """Whether records of a project may skip steps of their lifecycle.

    Attributes:
        allowed: Whether skipping is possible now (the project's choice and not forbidden by the organisation).
        own: The project's own choice, or `None` when it has none.
        chosen: The project's choice (own, else the nearest ancestor's, else off).
        source: Where `chosen` comes from: `project`, `parent_project` or `default`.
        forbidden: Whether skipping is forbidden for this project, by the organisation or by a governance profile.
        exempt: Whether the organisation forbids skipping but this project is exempt (and no profile forbids it).
        forbidden_by_profiles: Names of the governance profiles that forbid skipping for this project.
    """

    allowed: bool
    own: bool | None
    chosen: bool
    source: Literal["project", "parent_project", "default"]
    forbidden: bool
    exempt: bool
    forbidden_by_profiles: list[str] = Field(default_factory=list)


class ProjectLifecyclesOut(BaseModel):
    """A project's lifecycles and whether the caller may change them."""

    can_manage: bool
    has_parent: bool
    skip: ProjectSkipOut
    lifecycles: list[ProjectLifecycleOut]


class ProjectSkipSet(BaseModel):
    """The project's own choice on skipping steps; `null` follows the nearest ancestor project (else off)."""

    allowed: bool | None = None


class ProjectLifecycleSet(BaseModel):
    """The project's own turned-off states for one type; `null` follows the nearest ancestor project (else every
    state on)."""

    disabled_states: list[str] | None = Field(default=None, max_length=50)


class ExemptionOut(BaseModel):
    """A project the organisation's requirement does not bind."""

    project_id: UUID
    project_name: str
    project_code: str
    include_children: bool


class OrgLifecycleOut(BaseModel):
    """One record type's organisation-level view.

    Attributes:
        artefact_type: The registered record type.
        label: The record type's singular name.
        module_key: The module that owns the type.
        module_name: That module's display name.
        states: The optional states the organisation may require, in path order.
        required: The states it requires.
        exemptions: The projects exempt from the requirement.
    """

    artefact_type: str
    label: str
    module_key: str
    module_name: str
    states: list[LifecycleStateOut]
    required: list[str]
    exemptions: list[ExemptionOut]


class OrgLifecycleSet(BaseModel):
    """The states the organisation requires for one type."""

    required_states: list[str] = Field(default_factory=list, max_length=50)


class ExemptionSet(BaseModel):
    """A project to exempt, and whether its nested child projects are exempt too."""

    project_id: UUID
    include_children: bool = False


class OrgSkipOut(BaseModel):
    """The organisation's rule on skipping steps.

    Attributes:
        forbidden: Whether no project may skip steps (except the exempt ones).
        exemptions: The projects the ban does not bind.
    """

    forbidden: bool
    exemptions: list[ExemptionOut]


class OrgSkipSet(BaseModel):
    """Whether the organisation forbids skipping steps."""

    forbidden: bool


class ProjectSeparationOut(BaseModel):
    """One record type's approval separation rule as it applies to a project.

    Attributes:
        artefact_type: The registered record type with an approval gate.
        label: The record type's singular name.
        module_key: The module that owns the type, empty for a core type.
        module_name: That module's display name, empty for a core type.
        own: The project's own choice, or `None` when it follows its ancestor (or the default).
        chosen: The choice the project resolves to (own, else the nearest ancestor's, else the default).
        source: Where the project's choice comes from: `project`, `parent_project` or `default`.
        required: Whether the organisation requires a separate approver and binds this project.
        exempt: Whether the organisation requires one but this project is exempt.
        separate: Whether a person other than the creator must approve now.
    """

    artefact_type: str
    label: str
    module_key: str
    module_name: str
    own: bool | None
    chosen: bool
    source: Literal["project", "parent_project", "default"]
    required: bool
    exempt: bool
    separate: bool


class ProjectSeparationsOut(BaseModel):
    """A project's approval separation rules and whether the caller may change them."""

    can_manage: bool
    has_parent: bool
    types: list[ProjectSeparationOut]


class ProjectSeparationSet(BaseModel):
    """A project's choice for one type: `true` requires a separate approver, `false` lets the creator approve and
    `null` follows the nearest ancestor project (else the default)."""

    separate_approver: bool | None = None


class OrgSeparationOut(BaseModel):
    """One record type's organisation-level approval separation view.

    Attributes:
        artefact_type: The registered record type with an approval gate.
        label: The record type's singular name.
        module_key: The module that owns the type, empty for a core type.
        module_name: That module's display name, empty for a core type.
        required: Whether a separate approver is required in every project that is not exempt.
        exemptions: The projects the requirement does not bind.
    """

    artefact_type: str
    label: str
    module_key: str
    module_name: str
    required: bool
    exemptions: list[ExemptionOut]


class OrgSeparationSet(BaseModel):
    """Whether the organisation requires a separate approver for one type."""

    required: bool


class ApprovalStatusOut(BaseModel):
    """What a record's page shows about approval separation.

    Attributes:
        self_approved: Whether the record's latest approval was given by the person who created it.
        approved_by_name: Who gave it.
        approved_at: When (UTC).
        needs_other_approver: Whether the caller created the record and a separate approver is required, so approval
            is unavailable to them.
    """

    self_approved: bool
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    needs_other_approver: bool
