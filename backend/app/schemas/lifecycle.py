"""
Module: schemas.lifecycle

Request and response models for lifecycle configuration (`routers.lifecycles`): the optional states a project uses,
the states an organisation requires and the projects it exempts.
"""

from __future__ import annotations

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
        required: The states the organisation requires and that bind this project.
        exempt: Whether the organisation's requirement does not bind this project.
        source: Where the project's choice comes from: `project`, `parent_project` or `default`.
        transitions: Every state's legal next states with the turned-off states stepped over.
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
    source: Literal["project", "parent_project", "default"]
    transitions: dict[str, list[str]]


class ProjectLifecyclesOut(BaseModel):
    """A project's lifecycles and whether the caller may change them."""

    can_manage: bool
    has_parent: bool
    lifecycles: list[ProjectLifecycleOut]


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
