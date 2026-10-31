"""
Module: services.report_layout_designer

What the layout designer needs beyond storing layouts (`services.report_layouts`):

- The **field catalogue** for its field picker: every reportable record type the scope can use, with the fields a
  layout may name, plus the global placeholder names.
- The **block catalogue** for the visual designer: every registered block type with the editor schema it declared
  (`report_layout_block_schema`), so forms are drawn from data and a module's block type needs no frontend edit.
- A **tree check** (`check_tree`) that answers every problem with its path and never raises, for live feedback.
- A **draft preview**: a tree that is not saved is evaluated for the caller exactly as a run would be and returned
  as a standalone HTML page (document family) or as capped sheets (table family).

Design decisions:
- **A preview is a run that leaves nothing behind.** It goes through `custom_report_run`, so it applies the caller's
  own read permissions, the same work/output/time caps and the same fan-out rules; it writes no provenance row and no
  audit event (nothing was produced for anyone to keep) and stores nothing. The layout and version it evaluates are
  transient objects that are never added to the session.
- **The HTML is the renderer's own page** (`report_html`): it carries a restrictive `Content-Security-Policy`, no
  script and escaped text, and the frontend shows it in a sandboxed frame.
- **Sheets are capped for the screen** (`PREVIEW_MAX_ROWS` per sheet): a preview confirms the shape, a download gives
  the full table.
- The catalogue lists a type only where its module (and a sub-component keyed by the type) is enabled, the same gate
  the widget list uses, so an author is never offered a type the scope cannot read. Whether the *runner* may read a
  record is still decided at run time by the link graph.

Dependencies: `services.report_fields`, `services.custom_report_run`, `services.report_render`, `modules.registry`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import FAMILY_DOCUMENT, ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.modules.registry import (
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_artefact_type_label,
    get_report_field_providers,
    is_module_enabled,
    is_org_module_subcomponent_enabled,
)
from app.services import custom_report_run, report_render
from app.services.report_fields import FieldInfo, field_catalogue
from app.services.report_layout_block_schema import FIELD_KINDS, LAYOUT_FIELDS, BlockField, BlockSchema
from app.services.report_layout_tree import (
    BLOCK_SPECS,
    GROUP_FIELDS,
    IMAGE_COLUMN_FIELDS,
    LIST_OPERATORS,
    OPERATORS_BY_KIND,
    TREE_SCHEMA_VERSION,
    VALUELESS_OPERATORS,
    TreeAnalysis,
    TreeError,
    assert_valid,
    validate_tree,
)
from app.services.report_model import PLACEHOLDER_NAMES

#: Most rows of one sheet a preview returns.
PREVIEW_MAX_ROWS = 200
PREVIEW_NAME = "Preview"


@dataclass(frozen=True)
class TypeFields:
    """One reportable record type for the picker: its key, display name and fields."""

    type: str
    label: str
    fields: list[FieldInfo]


@dataclass(frozen=True)
class FieldCatalogue:
    """Everything a layout author can name: record types with their fields, global placeholders, and the fields of a group."""

    types: list[TypeFields]
    placeholders: tuple[str, ...]
    group_fields: dict[str, str]
    schema_version: int


@dataclass(frozen=True)
class PreviewSheet:
    """One sheet of a table-family preview.

    Attributes:
        name / columns / rows: As on `Sheet`, with at most `PREVIEW_MAX_ROWS` rows.
        total_rows: Rows the sheet really has.
    """

    name: str
    columns: list[str]
    rows: list[list[str]]
    total_rows: int


@dataclass(frozen=True)
class Preview:
    """A draft evaluated.

    Attributes:
        family: `document` or `table`.
        html: The standalone HTML page (document family), else `None`.
        sheets: The capped sheets (table family), else empty.
        warnings: What the reader should know (a cap truncated a read, a link type matched nothing) and run remarks.
        records_read: Total records the evaluation read.
        duration_ms: How long the evaluation took.
        projects: How many projects were evaluated.
    """

    family: str
    html: str | None
    sheets: list[PreviewSheet]
    warnings: list[str]
    records_read: int
    duration_ms: int
    projects: int


def _catalogue(types: Sequence[str]) -> FieldCatalogue:
    """Builds the catalogue for the given reportable types, sorted by display name."""
    entries = [TypeFields(t, get_artefact_type_label(t), field_catalogue(t)) for t in types]
    entries.sort(key=lambda e: (e.label.lower(), e.type))
    return FieldCatalogue(entries, PLACEHOLDER_NAMES, dict(GROUP_FIELDS), TREE_SCHEMA_VERSION)


def catalogue_for_organization(db: Session, organization_id: uuid.UUID) -> FieldCatalogue:
    """The types an organisation's layout author may use: those whose module the organisation has enabled."""
    usable: list[str] = []
    for artefact_type in get_report_field_providers():
        definition = artefact_type_module(artefact_type)
        if definition is not None:
            if not is_module_enabled(db, organization_id, definition.key):
                continue
            if any(sub.key == artefact_type for sub in definition.sub_components) and not is_org_module_subcomponent_enabled(
                db, organization_id, definition.key, artefact_type,
            ):
                continue
        usable.append(artefact_type)
    return _catalogue(usable)


def catalogue_for_project(db: Session, project: Project) -> FieldCatalogue:
    """The types a project's layout author may use: those whose module (and sub-component) is enabled for the project."""
    return _catalogue([t for t in get_report_field_providers() if artefact_type_enabled_for_project(db, t, project.id)])


def _transient(
    family: str, tree: dict[str, Any], organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str,
) -> tuple[ReportLayout, ReportLayoutVersion]:
    """An unsaved layout and version to evaluate; neither is added to the session."""
    layout_id = uuid.uuid4()
    layout = ReportLayout(
        id=layout_id, organization_id=organization_id, project_id=project_id, name=name or PREVIEW_NAME, description="",
        family=family, current_version=0,
    )
    version = ReportLayoutVersion(
        id=uuid.uuid4(), layout_id=layout_id, version=0, schema_version=TREE_SCHEMA_VERSION, tree=tree, tree_hash="",
        comment="",
    )
    return layout, version


def _preview_of(run: custom_report_run.LayoutRun) -> Preview:
    """Turns a finished run into the preview payload."""
    evaluated = run.evaluated
    records_read = sum(evaluated.stats.records_read.values())
    warnings = [*run.notes, *evaluated.warnings]
    html: str | None = None
    sheets: list[PreviewSheet] = []
    if run.family == FAMILY_DOCUMENT:
        rendered = report_render.render("html", run.family, custom_report_run.render_input_for(run))
        html = rendered.content.decode("utf-8")
    else:
        sheets = [
            PreviewSheet(s.name, s.columns, [[str(c) for c in row] for row in s.rows[:PREVIEW_MAX_ROWS]], len(s.rows)) for s in evaluated.sheets
        ]
    return Preview(run.family, html, sheets, warnings, records_read, run.duration_ms, len(run.projects))


@dataclass(frozen=True)
class BlockDescription:
    """One block type for the designer: its registry entry plus its editor schema.

    Attributes:
        key: The node's `type`.
        families: Layout families that may contain it.
        schema: What the form offers; a type that declared none gets a bare one (`described` false).
        described: Whether the type declared a schema.
    """

    key: str
    families: tuple[str, ...]
    schema: BlockSchema
    described: bool


@dataclass(frozen=True)
class BlockCatalogue:
    """Every block type, the layout-level fields and the field kinds the designer can draw."""

    blocks: list[BlockDescription]
    layout_fields: tuple[BlockField, ...]
    image_column_fields: tuple[BlockField, ...]
    field_kinds: tuple[str, ...]
    operators: dict[str, tuple[str, ...]]
    valueless_operators: tuple[str, ...]
    list_operators: tuple[str, ...]
    schema_version: int


def block_catalogue() -> BlockCatalogue:
    """The block types the designer can add, in the order the registry holds them (core first, then modules')."""
    blocks = [
        BlockDescription(
            spec.key, spec.families,
            spec.schema or BlockSchema(spec.key, "", template={"type": spec.key}), spec.schema is not None,
        )
        for spec in BLOCK_SPECS.values()
    ]
    return BlockCatalogue(
        blocks, LAYOUT_FIELDS, IMAGE_COLUMN_FIELDS, FIELD_KINDS, dict(OPERATORS_BY_KIND), VALUELESS_OPERATORS, LIST_OPERATORS, TREE_SCHEMA_VERSION,
    )


def check_tree(tree: dict[str, Any]) -> TreeAnalysis:
    """Validates a draft tree for live feedback: every problem with its path, nothing raised, nothing stored."""
    return validate_tree(tree)


def validation_errors(tree: dict[str, Any]) -> list[TreeError]:
    """The validator's problems with a draft tree (empty when it may be run)."""
    return validate_tree(tree).errors


def preview_for_project(
    db: Session, user: User, project: Project, *, tree: dict[str, Any], name: str = "", include_children: bool = False,
    variables: Mapping[str, Any] | None = None,
) -> Preview:
    """Evaluates a draft for one project.

    Args:
        db: Active session (read only).
        user: The caller; the evaluation sees only what they may read.
        project: The project (the route has authorised the caller as a layout manager).
        tree: The draft; validated here (it declares its own family).
        name: The report title to print.
        include_children: Also read the project's readable child projects.
        variables: Values for the draft's run-time variables (a variable not given takes its default).

    Returns:
        The preview.

    Raises:
        InvalidLayoutError: The tree is not valid.
        LayoutLimitError: A work, output or time limit was exceeded.
        VariableValueError: A variable's value is missing, undeclared or unacceptable.
    """
    assert_valid(tree)
    layout, version = _transient(str(tree["family"]), tree, project.organization_id, project.id, name)
    run = custom_report_run.run_project_layout(
        db, user, project, layout, version, include_children=include_children, variables=variables,
    )
    return _preview_of(run)


def preview_for_organization(
    db: Session, user: User, organization: Organization, *, tree: dict[str, Any], name: str = "",
    project_ids: Sequence[uuid.UUID] | None = None, variables: Mapping[str, Any] | None = None,
) -> Preview:
    """Evaluates a draft organisation layout once per project the caller can read (or the selected ones), merged.

    Raises:
        InvalidLayoutError: The tree is not valid.
        LayoutLimitError: A work, output or time limit was exceeded.
        custom_report_run.ProjectsNotInScopeError / NoProjectsToRunError / FanOutTooLargeError: As for a run.
    """
    assert_valid(tree)
    layout, version = _transient(str(tree["family"]), tree, organization.id, None, name)
    run = custom_report_run.run_organization_layout(
        db, user, organization, layout, version, project_ids=project_ids, variables=variables,
    )
    return _preview_of(run)
