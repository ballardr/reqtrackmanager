"""
Module: schemas.report_pack

Request and response models for report packs (`routers.report_packs`).

A summary never carries the definition (it is configuration only a manager needs); the detail and version
responses do. Dates are UTC instants.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.report_framework import ReportVariableOut


class ReportPackCreate(BaseModel):
    """Payload to create a pack with its first version."""

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    definition: dict[str, Any]
    comment: str = ""


class ReportPackUpdate(BaseModel):
    """Renames or re-describes a pack; a field left out is unchanged. The definition is saved separately."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ReportPackSave(BaseModel):
    """Saves a new version. `base_version` is the version the author started from."""

    definition: dict[str, Any]
    base_version: int = Field(ge=1)
    comment: str = ""


class ReportPackVisibilitySet(BaseModel):
    """Hides (`true`) or shows (`false`) an inherited pack in a project."""

    hidden: bool


class ReportPackRestore(BaseModel):
    """Restores the named hidden packs, or every one when `pack_ids` is left out."""

    pack_ids: list[UUID] | None = None


class ReportPackRestoreOut(BaseModel):
    """The packs a restore showed again."""

    restored: list[UUID]


class ReportPackOut(BaseModel):
    """A pack without its definition.

    Attributes:
        project_id: The owning project, `None` for an organisation pack.
        origin: Where this project sees it from (`project`, `ancestor`, `organization`).
        hidden: Hidden in the project asking (never for its own packs).
        editable: Whether the asking scope owns it.
        entries: How many reports it lists.
    """

    id: UUID
    organization_id: UUID
    project_id: UUID | None
    name: str
    description: str
    current_version: int
    origin: Literal["project", "ancestor", "organization"]
    hidden: bool = False
    editable: bool = True
    entries: int = 0
    updated_at: datetime


class ReportPackVersionOut(BaseModel):
    """One saved version, with its definition."""

    version: int
    schema_version: int
    definition: dict[str, Any]
    definition_hash: str
    comment: str
    created_by: UUID | None
    created_at: datetime


class ReportPackDetailOut(ReportPackOut):
    """A pack with its current version's definition."""

    current: ReportPackVersionOut


class ReportPackVersionSummaryOut(BaseModel):
    """A version in the history list (no definition)."""

    version: int
    definition_hash: str
    comment: str
    created_by: UUID | None
    created_at: datetime


class ReportPackRunRequest(BaseModel):
    """Values for a pack run or its preview. Sent as a body so the values never appear in a URL."""

    variables: dict[str, Any] | None = Field(default=None, max_length=50, description="Values for the pack's variables.")
    report_template_id: UUID | None = None
    include_children: bool = False
    project_ids: list[UUID] | None = Field(default=None, max_length=200, description="Organisation packs: narrow to these projects.")
    variable_set_id: UUID | None = Field(default=None, description="A saved set to start from; `variables` win over its values.")


class ReportPackFormSetOut(BaseModel):
    """A saved set offered on the run form: the values a run would take."""

    id: UUID
    name: str
    values: dict[str, Any]
    warnings: list[str] = []


class ReportPackFormOut(BaseModel):
    """The run form of a pack: its variables with defaults and current options, and how many reports it lists."""

    name: str
    description: str
    entries: int
    variables: list[ReportVariableOut]
    sets: list[ReportPackFormSetOut] = []


class ReportPackPreviewEntryOut(BaseModel):
    """What one entry would produce, before anything is downloaded."""

    position: int
    kind: Literal["layout", "report"]
    title: str
    format: str
    status: Literal["included", "not_available"]
    reason: str | None = None
    records: int = 0
    warnings: list[str] = []


class ReportPackPreviewOut(BaseModel):
    """The counts per entry for the chosen values. Nothing is stored or produced."""

    entries: list[ReportPackPreviewEntryOut]
    total_records: int
    not_available: int
    variable_set: str | None = None
    warnings: list[str] = []


class ReportPackSetCreate(BaseModel):
    """Payload to save a variable set: a name and values for some or all of the pack's variables."""

    name: str = Field(min_length=1, max_length=200)
    values: dict[str, Any] = Field(default_factory=dict, max_length=50)


class ReportPackSetUpdate(BaseModel):
    """Renames a set and/or replaces its values; a field left out is unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    values: dict[str, Any] | None = Field(default=None, max_length=50)


class ReportPackSetOverrideSave(BaseModel):
    """A project's values for the variables it changes in a pack-defined set (empty removes the override)."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=50)


class ReportPackSetOut(BaseModel):
    """A saved set as one scope sees it.

    Attributes:
        origin: `pack` (saved with the pack) or `project` (added by a project).
        project_id: The adding project for a `project` set.
        base: The set's own values.
        override: The asking project's own override (`None` when it has none).
        overridden_by: The nearest project whose override changes a value (the asking project or an ancestor).
        effective: The values a run for the asking scope takes.
        editable: Whether the asking scope may rename, change or delete the set.
        overridable: Whether the asking project may override its values (an inherited pack-defined set).
        warnings: Values that are no longer among their variable's options.
    """

    id: UUID
    name: str
    origin: Literal["pack", "project"]
    project_id: UUID | None
    base: dict[str, Any]
    override: dict[str, Any] | None = None
    overridden_by: UUID | None = None
    effective: dict[str, Any]
    editable: bool
    overridable: bool = False
    warnings: list[str] = []
