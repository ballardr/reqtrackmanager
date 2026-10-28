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

from pydantic import BaseModel, Field, model_validator

from app.services.report_framework import ReportParamOut, ReportVariableOut
from app.services.report_layout_text import MAX_TEXT_VIEW_CHARS


class ReportLayoutCreate(BaseModel):
    """Payload to create a layout with its first version."""

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    folder: str = Field(default="", max_length=120)
    report_template_id: UUID | None = None
    family: Literal["document", "table"]
    tree: dict[str, Any]
    comment: str = ""


class ReportLayoutUpdate(BaseModel):
    """Renames or re-describes a layout; a field left out is unchanged. The tree is saved separately."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    folder: str | None = Field(default=None, max_length=120)
    report_template_id: UUID | None = None
    """The branding template; sent as `null` it clears the override (a field left out is unchanged)."""


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


class ReportLayoutStartersOut(BaseModel):
    """The result of adding the starter layouts to an organisation.

    Attributes:
        added: The names written; starters the organisation already had are not listed.
    """

    added: list[str]


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
    folder: str = ""
    report_template_id: UUID | None = None
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


class ReportFieldOut(BaseModel):
    """One field of a record type as the field picker shows it (`reserved` fields are the engine's own)."""

    key: str
    label: str
    kind: str
    reserved: bool = False
    choices: list[str] = []
    math: bool = False


class ReportFieldTypeOut(BaseModel):
    """A reportable record type with its fields; `type` is what a block's source names."""

    type: str
    label: str
    fields: list[ReportFieldOut]


class ReportFieldCatalogueOut(BaseModel):
    """What a layout may name: the record types the scope can use with their fields, the global `{{placeholders}}`
    and the fields every group exposes (`{{group.value}}`, `{{group.count}}`) with their kinds."""

    types: list[ReportFieldTypeOut]
    placeholders: list[str]
    group_fields: dict[str, str]
    schema_version: int


class ReportBlockFieldOut(BaseModel):
    """One key of a block (or of the layout) as the designer's form offers it (`services.report_layout_block_schema.BlockField`)."""

    key: str
    label: str
    kind: str
    required: bool
    help: str
    max_length: int | None
    minimum: int | None
    maximum: int | None
    default: Any
    choices: list[str]
    features: list[str]
    depends_on: str | None
    families: list[str]


class ReportBlockContainerOut(BaseModel):
    """A list of child blocks a block holds."""

    key: str
    label: str


class ReportBlockProvidesOut(BaseModel):
    """A name a block brings into scope: `key` holds it, `kind` is `record` or `group`, `default` is used when absent."""

    key: str
    kind: str
    default: str


class ReportBlockOut(BaseModel):
    """One block type the designer can add.

    Attributes:
        type: The `type` value of a node.
        label / description: How the designer names and explains it.
        families: The layout families that may contain it.
        fields: The keys of a node, in form order.
        containers: Child lists, in order.
        provides: The name it brings into scope, if any.
        template: The node a new block starts as (may fail validation until filled in).
        described: False for a type that declared no schema; the designer shows its node as JSON.
    """

    type: str
    label: str
    description: str
    families: list[str]
    fields: list[ReportBlockFieldOut]
    containers: list[ReportBlockContainerOut]
    provides: ReportBlockProvidesOut | None
    template: dict[str, Any]
    described: bool


class ReportBlockCatalogueOut(BaseModel):
    """Every block type, the layout-level fields, the field kinds the designer has a control for and the operators a
    condition accepts for each kind of field (so the designer never restates the validator's rule)."""

    blocks: list[ReportBlockOut]
    layout_fields: list[ReportBlockFieldOut]
    field_kinds: list[str]
    operators: dict[str, list[str]]
    valueless_operators: list[str]
    list_operators: list[str]
    schema_version: int


class ReportLayoutValidateRequest(BaseModel):
    """A tree to check (nothing is stored or run)."""

    tree: dict[str, Any]


class ReportLayoutTreeErrorOut(BaseModel):
    """One problem in a tree: `path` is where (`nodes[2].children[0].columns[1].field`; empty for the layout itself)."""

    path: str
    message: str


class ReportLayoutValidateOut(BaseModel):
    """Whether the tree may be saved and run, and every problem found (at most 50)."""

    ok: bool
    errors: list[ReportLayoutTreeErrorOut]
    node_count: int


class ReportLayoutPreviewRequest(BaseModel):
    """A draft to evaluate: its text view or its tree (exactly one).

    Attributes:
        text / tree: The draft.
        name: The report title to print.
        include_children: Project scope only: also read readable child projects.
        project_ids: Organisation scope only: narrow the fan-out to these projects.
        variables: Values for the draft's run-time variables (a variable not given takes its default).
    """

    text: str | None = Field(default=None, max_length=MAX_TEXT_VIEW_CHARS)
    tree: dict[str, Any] | None = None
    name: str = Field(default="", max_length=200)
    include_children: bool = False
    project_ids: list[UUID] | None = Field(default=None, max_length=200)
    variables: dict[str, Any] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _one_draft(self) -> ReportLayoutPreviewRequest:
        if (self.text is None) == (self.tree is None):
            raise ValueError("Send either text or tree.")
        return self


class ReportVariablesOut(BaseModel):
    """The run form of a layout: its variables (empty when it declares none)."""

    variables: list[ReportVariableOut]


class ReportLayoutVariablesRequest(BaseModel):
    """A draft whose run form is wanted: its text view or its tree (exactly one), and the projects whose options to offer."""

    text: str | None = Field(default=None, max_length=MAX_TEXT_VIEW_CHARS)
    tree: dict[str, Any] | None = None
    project_ids: list[UUID] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one_draft(self) -> ReportLayoutVariablesRequest:
        if (self.text is None) == (self.tree is None):
            raise ValueError("Send either text or tree.")
        return self


class ReportLayoutDraftVariablesOut(BaseModel):
    """The run form of a draft. When the text has problems `ok` is false and `errors` names them."""

    ok: bool
    variables: list[ReportVariableOut] = Field(default_factory=list)
    errors: list[ReportLayoutTextError] = Field(default_factory=list)


class ReportLayoutPreviewSheetOut(BaseModel):
    """One sheet of a table preview, capped; `total_rows` is the real count."""

    name: str
    columns: list[str]
    rows: list[list[str]]
    total_rows: int


class ReportLayoutPreviewOut(BaseModel):
    """The outcome of a preview. When the text has problems `ok` is false, `errors` names them and nothing was run.

    Attributes:
        html: A standalone, script-free HTML page (document family) to show in a sandboxed frame.
        sheets: Capped sheets (table family).
        warnings: Things the reader should know.
        records_read / duration_ms / projects: Counters of the run.
    """

    ok: bool
    errors: list[ReportLayoutTextError] = []
    family: str | None = None
    html: str | None = None
    sheets: list[ReportLayoutPreviewSheetOut] = []
    warnings: list[str] = []
    records_read: int = 0
    duration_ms: int = 0
    projects: int = 0
