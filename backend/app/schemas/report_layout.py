"""
Module: schemas.report_layout

Request and response models for custom report layouts (`routers.report_layouts`).

A summary never carries the tree (it can be large and is configuration only a manager needs); the detail
and version responses do. Dates are UTC instants.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.report_framework import ReportParamOut
from app.services.report_layout_text import MAX_TEXT_VIEW_CHARS


class ReportLayoutCreate(BaseModel):
    """Payload to create a layout with its first version."""

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    family: Literal["document", "table"]
    tree: dict[str, Any]
    comment: str = ""


class ReportLayoutUpdate(BaseModel):
    """Renames or re-describes a layout; a field left out is unchanged. The tree is saved separately."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ReportLayoutSave(BaseModel):
    """Saves a new version. `base_version` is the version the author started from."""

    tree: dict[str, Any]
    base_version: int = Field(ge=1)
    comment: str = ""


class ReportLayoutTextParse(BaseModel):
    """Text view to read (`services.report_layout_text`)."""

    text: str = Field(max_length=MAX_TEXT_VIEW_CHARS)


class ReportLayoutTextFormat(BaseModel):
    """A tree to write as its text view."""

    tree: dict[str, Any]


class ReportLayoutTextError(BaseModel):
    """One problem in the text: `column` is set for a syntax error, `None` for a validation error of a whole block."""

    line: int
    column: int | None
    message: str


class ReportLayoutTextParseOut(BaseModel):
    """The tree read from the text (`None` after a syntax error) and every problem found; `ok` means it may be saved."""

    ok: bool
    tree: dict[str, Any] | None
    errors: list[ReportLayoutTextError]


class ReportLayoutTextOut(BaseModel):
    """A layout's text view."""

    text: str


class ReportLayoutVisibilitySet(BaseModel):
    """Hides (`true`) or shows (`false`) an inherited layout in a project."""

    hidden: bool


class ReportLayoutRestore(BaseModel):
    """Restores the named hidden layouts, or every one when `layout_ids` is left out."""

    layout_ids: list[UUID] | None = None


class ReportLayoutOut(BaseModel):
    """A layout without its tree.

    Attributes:
        project_id: The owning project, `None` for an organisation layout.
        origin: Where this project sees it from (`project`, `ancestor`, `organization`); on an organisation
            list always `organization`.
        hidden: Hidden in the project asking (never for its own layouts).
        editable: Whether the asking scope owns it (an inherited layout is edited where it lives).
    """

    id: UUID
    organization_id: UUID
    project_id: UUID | None
    name: str
    description: str
    family: str
    current_version: int
    origin: Literal["project", "ancestor", "organization"]
    hidden: bool = False
    editable: bool = True
    updated_at: datetime


class ReportLayoutVersionOut(BaseModel):
    """One saved version, with its tree."""

    version: int
    schema_version: int
    tree: dict[str, Any]
    tree_hash: str
    comment: str
    created_by: UUID | None
    created_at: datetime


class ReportLayoutDetailOut(ReportLayoutOut):
    """A layout with its current version's tree."""

    current: ReportLayoutVersionOut


class ReportLayoutVersionSummaryOut(BaseModel):
    """A version in the history list (no tree)."""

    version: int
    tree_hash: str
    comment: str
    created_by: UUID | None
    created_at: datetime


class LayoutErrorOut(BaseModel):
    """One validation problem: where and what."""

    path: str
    message: str


class ReportLayoutRestoreOut(BaseModel):
    """The layouts a restore showed again."""

    restored: list[UUID]


class ReportWidgetOut(BaseModel):
    """One component of a report (a table, its headline figures or its notes) that a layout can embed with a `widget` block.

    Attributes:
        key: What the block names (`<module key>.<report slug>.<part>`).
        title: The component's title.
        description: One line about what it holds (may be empty).
        kind: `section` (a table), `figures` or `notes`.
        report_title: The report it comes from.
        module_key: The module that provides it.
        module_name: That module's display name.
        params: The report's settings a block may give it, with their types, bounds and choices.
    """

    key: str
    title: str
    description: str
    kind: str
    report_title: str
    module_key: str
    module_name: str
    params: list[ReportParamOut]
