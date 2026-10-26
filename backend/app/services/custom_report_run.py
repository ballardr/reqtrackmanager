"""
Module: services.custom_report_run

Runs a custom report layout for a caller and turns the result into what the report framework serves:
a `ReportResult` (the Reports page's on-screen run), a `ReportDocument` (PDF, Word) or a CSV, with the
provenance row and the catalogue entries that make a layout appear beside the module reports.

Responsibilities:
- Project run: one layout, one project (optionally with its readable child projects), through the
  caller's `ArtefactResolver`.
- Organisation-wide run: the same layout evaluated once **per project** the caller can read (narrowed by
  the caller's project selection), each with that project's own resolver, merged into one report.
- Merge: a document gets one top-level heading per project (authored headings move one level down) and a
  page break between projects; a table layout's sheets of the same name are concatenated with a leading
  `Project` column.
- Output: `result_for` (on-screen), `document_for` (branding, introduction/chapters/appendices),
  `render_input_for`, `available_formats`.
- Provenance: `record_run` writes the `GeneratedReport` row (D11).
- Catalogue: `project_entries` / `org_entries` describe the runnable layouts like any other report.

Design decisions:
- **Authorisation is per project and is the traversal layer's.** The organisation-wide run adds no
  visibility rule: each project is evaluated with `ArtefactResolver(project, caller)`, so a record the
  caller cannot see is counted and never named, exactly as in a project run. The projects offered are the
  ones the caller holds a role in (`readable_projects`) and a selection can only narrow them.
- **A project that hid the layout is skipped** in an organisation-wide run, as it does not offer the layout
  to its runners; the report says how many were skipped.
- **One budget for the whole run.** The wall-clock limit is shared by all projects (each gets what is left)
  and the output limit applies to the total, so a fan-out cannot multiply the single-project caps;
  `MAX_FANOUT_PROJECTS` bounds the number of evaluations.
- **The on-screen form is a table view of the document.** Each table becomes a section titled by the
  headings above it, with the text between them as its note; text after the last table becomes a report
  note. The PDF and Word are the faithful forms.
- **Formats follow the layout family and come from the renderer registry** (`services.report_render`): a
  document layout gives `json` plus `pdf`, `docx`, `html`; a table layout `json` plus `csv` (a zip when it has
  several sheets) and `xlsx`. A new format is one registration there.
- **Content tiers key on the layout id** (`custom.<layout id>`), so a layout has its own introduction,
  chapters and appendices across template, project and organisation like a module report.

Dependencies: `services.report_layout_eval`, `services.report_layout_scope`, `services.report_framework`,
`services.report_content`, `services.report_document`, `models.generated_report`.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.generated_report import SCOPE_ORGANIZATION, SCOPE_PROJECT, GeneratedReport
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.report_content import CUSTOM_REPORT_KEY_PREFIX
from app.models.report_layout import FAMILY_DOCUMENT, ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.services import definition_suppression, report_layout_scope, report_layouts
from app.services.link_graph import ArtefactResolver
from app.services.report_content import (
    build_placeholders,
    content_blocks,
    resolve_report_content,
)
from app.services.report_document import ReportBranding
from app.services.report_framework import (
    ReportCatalogueEntryOut,
    ReportContext,
    ReportMetric,
    ReportProjectOut,
    ReportResult,
    ReportSection,
    readable_projects,
)
from app.services.report_layout_eval import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_OUTPUT,
    MAX_RECORDED_VERSIONS,
    EvalStats,
    EvaluatedLayout,
    LayoutLimitError,
    LayoutTimeoutError,
    evaluate_layout,
)
from app.services.report_model import (
    Block,
    BulletList,
    Gap,
    Heading,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Sheet,
    Table,
)
from app.services.report_render import RenderInput, formats_for

ENGINE_VERSION = "1"
"""Bumped when evaluation semantics change, so a provenance row says which engine produced a report."""
MODULE_KEY = "custom_reports"
MODULE_NAME = "Custom reports"
#: Most projects one organisation-wide run evaluates.
MAX_FANOUT_PROJECTS = 200
_SLUG = re.compile(r"[^a-z0-9]+")


class ProjectsNotInScopeError(LookupError):
    """A requested project is not one the caller can run the report for."""


class NoProjectsToRunError(LookupError):
    """No project is left to run the layout for (none readable, selected, or all have hidden it)."""


class FanOutTooLargeError(ValueError):
    """More than `MAX_FANOUT_PROJECTS` projects were asked for."""


def content_key(layout_id: uuid.UUID) -> str:
    """The `ReportContent.report_key` of a layout's introduction, chapters and appendices."""
    return f"{CUSTOM_REPORT_KEY_PREFIX}{layout_id}"


@dataclass
class LayoutRun:
    """A finished run, before rendering.

    Attributes:
        layout: The layout that ran.
        version: The pinned version that ran.
        organization: The organisation.
        projects: The projects the run covered.
        root_project: The project of a project-level run, `None` for an organisation-wide run.
        evaluated: The evaluation (merged across projects for an organisation-wide run).
        generated_at: When the run started (UTC).
        duration_ms: How long evaluation took.
        notes: Run-level remarks (projects skipped because they hid the layout).
    """

    layout: ReportLayout
    version: ReportLayoutVersion
    organization: Organization
    projects: list[Project]
    root_project: Project | None
    evaluated: EvaluatedLayout
    generated_at: datetime
    duration_ms: int
    notes: list[str] = field(default_factory=list)

    @property
    def scope_label(self) -> str:
        """The name printed as the report's scope."""
        return self.root_project.name if self.root_project is not None else self.organization.name

    @property
    def family(self) -> str:
        """`document` or `table`."""
        return self.evaluated.family


def available_formats(family: str, tree: dict[str, Any] | None = None) -> list[str]:
    """The formats a layout can be produced in: `json` (the on-screen run) then every renderer of its family.

    Args:
        family: The layout's family.
        tree: Unused by the shipped renderers (kept so a format that depends on the layout's shape, such as
            one needing a single sheet, can decide from it).

    Returns:
        `json` first, then `services.report_render.formats_for(family)`.
    """
    return ["json", *formats_for(family)]


# --- running ---------------------------------------------------------------------------------------------


def _evaluate_project(
    db: Session, user: User, organization: Organization, root: Project, projects: Sequence[Project],
    version: ReportLayoutVersion, title: str, timeout: float,
) -> EvaluatedLayout:
    """Evaluates the tree for one root project with that project's resolver (the authorisation point)."""
    resolver = ArtefactResolver(db, root, user.id, include_related=True)
    ctx = ReportContext(module_key=MODULE_KEY, organization=organization, projects=list(projects), root_project=root)
    return evaluate_layout(
        db, resolver, ctx, version.tree, title=title, project_ids=[p.id for p in projects], timeout_seconds=timeout,
    )


def run_project_layout(
    db: Session, user: User, project: Project, layout: ReportLayout, version: ReportLayoutVersion, *,
    include_children: bool = False,
) -> LayoutRun:
    """Runs a layout for `project`.

    Args:
        db: Active session (read only).
        user: The caller.
        project: The project (the route has already authorised the caller for it).
        layout: A layout the project can reach (the route checked reachability and hiding).
        version: The version to run (the layout's current one).
        include_children: Also read the project's readable child projects' records.

    Returns:
        The run.

    Raises:
        LayoutLimitError: A work, output or time limit was exceeded.
    """
    organization = db.get(Organization, project.organization_id)
    assert organization is not None
    started = datetime.now(UTC)
    clock = time.monotonic()
    projects = readable_projects(db, user, organization=organization, root_project=project, include_children=include_children)
    evaluated = _evaluate_project(db, user, organization, project, projects, version, layout.name, DEFAULT_TIMEOUT_SECONDS)
    return LayoutRun(
        layout, version, organization, projects, project, evaluated, started, round((time.monotonic() - clock) * 1000),
    )


def run_organization_layout(
    db: Session, user: User, organization: Organization, layout: ReportLayout, version: ReportLayoutVersion, *,
    project_ids: Sequence[uuid.UUID] | None = None,
) -> LayoutRun:
    """Runs an organisation layout once per project the caller can read and merges the results.

    Args:
        db: Active session (read only).
        user: The caller.
        organization: The organisation.
        layout: An organisation-level layout of `organization`.
        version: The version to run.
        project_ids: The projects to include (narrowing only); `None` for every project the caller can read.

    Returns:
        The merged run; its `projects` are the ones evaluated.

    Raises:
        ProjectsNotInScopeError: A requested project is not one the caller holds a role in.
        FanOutTooLargeError: More than `MAX_FANOUT_PROJECTS` projects would be evaluated.
        NoProjectsToRunError: No project is left to evaluate.
        LayoutLimitError: A work, output or time limit was exceeded across the whole run.
    """
    started = datetime.now(UTC)
    clock = time.monotonic()
    readable = readable_projects(db, user, organization=organization, root_project=None, include_children=False)
    if project_ids is not None:
        by_id = {p.id: p for p in readable}
        if any(pid not in by_id for pid in project_ids):
            raise ProjectsNotInScopeError("A selected project is not one you can report on.")
        chosen = sorted((by_id[pid] for pid in set(project_ids)), key=lambda p: (p.name.lower(), str(p.id)))
    else:
        chosen = readable
    if len(chosen) > MAX_FANOUT_PROJECTS:
        raise FanOutTooLargeError(
            f"This report would cover {len(chosen)} projects; select at most {MAX_FANOUT_PROJECTS}."
        )
    hiding = [p for p in chosen if layout.id in definition_suppression.get_suppressed_ids(db, p.id, report_layout_scope.LAYOUT_KIND)]
    hiding_ids = {p.id for p in hiding}
    chosen = [p for p in chosen if p.id not in hiding_ids]
    if not chosen:
        raise NoProjectsToRunError("There is no project to run this report for.")
    deadline = clock + DEFAULT_TIMEOUT_SECONDS
    parts: list[tuple[Project, EvaluatedLayout]] = []
    produced = 0
    for project in chosen:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LayoutTimeoutError("The report took too long to run. Select fewer projects or narrow the layout.")
        part = _evaluate_project(db, user, organization, project, [project], version, layout.name, remaining)
        produced += part.stats.blocks + part.stats.rows
        if produced > MAX_OUTPUT:
            raise LayoutLimitError("The report is too large. Select fewer projects or narrow the layout.")
        parts.append((project, part))
    notes = []
    if hiding:
        notes.append(f"{len(hiding)} project(s) were left out because they have hidden this report.")
    return LayoutRun(
        layout, version, organization, chosen, None, merge_evaluations(parts, layout.name),
        started, round((time.monotonic() - clock) * 1000), notes,
    )


def merge_evaluations(parts: Sequence[tuple[Project, EvaluatedLayout]], title: str) -> EvaluatedLayout:
    """Combines per-project evaluations of one layout into one (see the module docstring for the shape).

    Args:
        parts: `(project, evaluation)` in the order they should appear (every evaluation is of the same layout).
        title: The document title.

    Returns:
        The merged evaluation: stats summed, warnings prefixed with the project, the digests combined.
    """
    family = parts[0][1].family
    stats = EvalStats()
    warnings: list[str] = []
    for project, part in parts:
        for record_type, count in part.stats.records_read.items():
            stats.records_read[record_type] += count
        stats.blocks += part.stats.blocks
        stats.rows += part.stats.rows
        stats.hidden += part.stats.hidden
        stats.unavailable += part.stats.unavailable
        warnings += [f"{project.name}: {w}" for w in part.warnings]
    digest = hashlib.sha256("\n".join(f"{p.id}:{e.source_digest}" for p, e in parts).encode()).hexdigest()
    versions: dict[str, dict[str, int]] = {}
    truncated = any(part.record_versions_truncated for _, part in parts)
    for _, part in parts:
        for record_type, found in part.record_versions.items():
            versions.setdefault(record_type, {}).update(found)  # a record shown under two projects is one record
    if sum(len(v) for v in versions.values()) > MAX_RECORDED_VERSIONS:
        keep = MAX_RECORDED_VERSIONS
        trimmed: dict[str, dict[str, int]] = {}
        for record_type in sorted(versions):
            for record_id in sorted(versions[record_type]):
                if keep == 0:
                    break
                trimmed.setdefault(record_type, {})[record_id] = versions[record_type][record_id]
                keep -= 1
        versions, truncated = trimmed, True
    document = None
    sheets: list[Sheet] = []
    if family == FAMILY_DOCUMENT:
        blocks: list[Block] = []
        for index, (project, part) in enumerate(parts):
            assert part.document is not None
            if index:
                blocks.append(PageBreak())
            blocks.append(Heading(project.name, 1))
            blocks += [Heading(b.text, min(b.level + 1, 4)) if isinstance(b, Heading) else b for b in part.document.blocks]
        document = ReportDocument(title=title, blocks=blocks, landscape=parts[0][1].document.landscape if parts[0][1].document else False)
    else:
        merged: dict[str, Sheet] = {}
        for project, part in parts:
            for sheet in part.sheets:
                target = merged.setdefault(sheet.name, Sheet(sheet.name, ["Project", *sheet.columns], []))
                target.rows.extend([project.name, *row] for row in sheet.rows)
        sheets = list(merged.values())
    widgets = sorted({key for _, part in parts for key in part.widgets})
    return EvaluatedLayout(family, document, sheets, warnings, stats, digest, versions, truncated, widgets)


# --- output ------------------------------------------------------------------------------------------------


def _scope_line(run: LayoutRun) -> str:
    return f"{run.scope_label} · generated {run.generated_at.strftime('%Y-%m-%d %H:%M')} UTC"


def _sections_of_document(blocks: Sequence[Block]) -> tuple[list[ReportSection], list[str]]:
    """The tables of a document as sections, with the text around them (see the module docstring).

    A section is titled by the headings above its table, outermost first and joined with " / " (so a merged
    organisation run reads "Alpha / Requirements"); the paragraphs between the previous table and this one
    become its note.
    """
    sections: list[ReportSection] = []
    trail: list[tuple[int, str]] = []
    unused: list[str] = []  # headings no table has been titled by yet
    lines: list[str] = []
    for block in blocks:
        if isinstance(block, Heading):
            trail = [(level, text) for level, text in trail if level < block.level] + [(block.level, block.text)]
            unused.append(block.text)
        elif isinstance(block, Paragraph | Note):
            lines.append(block.text)
        elif isinstance(block, BulletList):
            lines += [f"• {item}" for item in block.items]
        elif isinstance(block, Table):
            sections.append(ReportSection(
                key=f"section-{len(sections) + 1}", title=" / ".join(text for _, text in trail) or f"Table {len(sections) + 1}",
                columns=block.columns, rows=block.rows, note=" ".join(lines), tones=block.tones,
            ))
            unused, lines = [], []
        # Gap, PageBreak and Image carry no text.
    return sections, [*unused, *lines]


def result_for(run: LayoutRun) -> ReportResult:
    """The run as the Reports page shows it on screen.

    Args:
        run: A finished run.

    Returns:
        A `ReportResult`: sections from the tables (or sheets), warnings and run remarks as notes, and the
        records read as the one headline figure.
    """
    evaluated = run.evaluated
    notes = [*run.notes, *evaluated.warnings]
    if evaluated.family == FAMILY_DOCUMENT:
        assert evaluated.document is not None
        sections, leftover = _sections_of_document(evaluated.document.blocks)
        notes += leftover
    else:
        sections = [
            ReportSection(key=f"sheet-{i + 1}", title=sheet.name, columns=sheet.columns, rows=sheet.rows)
            for i, sheet in enumerate(evaluated.sheets)
        ]
    total = sum(evaluated.stats.records_read.values())
    return ReportResult(
        key=str(run.layout.id), title=run.layout.name, scope_label=run.scope_label, generated_at=run.generated_at,
        notes=notes, sections=sections, metrics=[ReportMetric("Records read", total)],
        data={"family": evaluated.family, "layout_version": run.version.version, "projects": len(run.projects)},
        eligible_projects=len(run.projects),
    )


def document_for(
    run: LayoutRun, *, branding: ReportBranding | None, before: Sequence[Block] = (), after: Sequence[Block] = (),
) -> ReportDocument:
    """The run's document for the PDF and Word renderers.

    Args:
        run: A finished document-family run.
        branding: The organisation template's branding, or `None`.
        before: The layout's introduction and chapters (`content_blocks_for`).
        after: Its appendices.

    Returns:
        The document: content before, a scope line, the evaluated blocks, content after.
    """
    document = run.evaluated.document
    assert document is not None
    blocks: list[Block] = [*before, Note(_scope_line(run)), Gap(0.2), *[Note(n) for n in run.notes], *document.blocks, *after]
    return ReportDocument(title=run.layout.name, blocks=blocks, branding=branding, landscape=document.landscape)


def content_blocks_for(
    db: Session, run: LayoutRun, template: ReportTemplate | None,
) -> tuple[list[Block], list[Block]]:
    """The layout's introduction/chapters and appendices (template, project, ancestors, organisation).

    An organisation-wide run has no single project, so only the template and organisation tiers apply.
    """
    content = resolve_report_content(db, content_key(run.layout.id), run.organization, run.root_project, template)
    placeholders = build_placeholders(
        project_name=run.scope_label, report_title=run.layout.name, generated_on=run.generated_at.date(),
        organisation=run.organization.name,
    )
    return content_blocks(db, run.organization.id, content, placeholders)


def render_input_for(
    run: LayoutRun, *, branding: ReportBranding | None = None, before: Sequence[Block] = (), after: Sequence[Block] = (),
) -> RenderInput:
    """What the renderers are given for a run: the document (with branding and content) or the sheets."""
    if run.family == FAMILY_DOCUMENT:
        return RenderInput(run.layout.name, document=document_for(run, branding=branding, before=before, after=after))
    return RenderInput(run.layout.name, sheets=run.evaluated.sheets)


# --- provenance ----------------------------------------------------------------------------------------------


def record_run(
    db: Session, user: User, run: LayoutRun, fmt: str, *, report_template_id: uuid.UUID | None,
    include_children: bool = False, requested_project_ids: Sequence[uuid.UUID] | None = None,
) -> GeneratedReport:
    """Adds the provenance row of a run (the caller commits).

    The row holds identifiers, counts and keys only: no layout text, record content or cell value.

    Args:
        db: Active session.
        user: The caller.
        run: The finished run.
        fmt: The requested format.
        report_template_id: The branding template applied, if any.
        include_children: Whether child projects were included (project-level run).
        requested_project_ids: The selection of an organisation-wide run, `None` for "all readable".

    Returns:
        The new row.
    """
    stats = run.evaluated.stats
    counts: dict[str, int] = defaultdict(int)
    counts.update(stats.records_read)
    row = GeneratedReport(
        organization_id=run.organization.id, project_id=run.root_project.id if run.root_project else None,
        scope=SCOPE_PROJECT if run.root_project else SCOPE_ORGANIZATION,
        layout_id=run.layout.id, layout_name=run.layout.name, layout_version=run.version.version,
        tree_hash=run.version.tree_hash, requested_by=user.id, created_at=run.generated_at, format=fmt,
        engine_version=ENGINE_VERSION,
        params={
            "report_template_id": str(report_template_id) if report_template_id else None,
            "include_children": include_children,
            "requested_project_ids": [str(p) for p in requested_project_ids] if requested_project_ids is not None else None,
        },
        scope_project_ids=[str(p.id) for p in run.projects], widgets=list(run.evaluated.widgets), record_counts=dict(counts),
        stats={
            "blocks": stats.blocks, "rows": stats.rows, "hidden": stats.hidden, "unavailable": stats.unavailable,
            "warnings": len(run.evaluated.warnings), "duration_ms": run.duration_ms,
        },
        source_digest=run.evaluated.source_digest, record_versions=run.evaluated.record_versions,
        record_versions_truncated=run.evaluated.record_versions_truncated,
    )
    db.add(row)
    return row


# --- catalogue -----------------------------------------------------------------------------------------------


def slug_for(layout: ReportLayout) -> str:
    """The catalogue slug of a layout: `custom-<name>-<id prefix>`, unique and unable to clash with a module report."""
    name = _SLUG.sub("-", layout.name.lower()).strip("-")[:40] or "report"
    return f"custom-{name}-{str(layout.id)[:8]}"


def _entry(
    db: Session, layout: ReportLayout, *, scope: str, path: str, projects: Sequence[Project] = (),
) -> ReportCatalogueEntryOut:
    version = report_layouts.get_version(db, layout.id, layout.current_version)
    tree = version.tree if version is not None else {"nodes": []}
    return ReportCatalogueEntryOut(
        module_key=MODULE_KEY, module_name=MODULE_NAME, key=str(layout.id), slug=slug_for(layout), title=layout.name,
        description=layout.description or "A custom report layout.", scope="project" if scope == "project" else "organization",
        path=path, formats=available_formats(layout.family, tree),
        supports_include_children=scope == "project", supports_project_filter=False,
        supports_project_multi_filter=scope != "project",
        projects=[ReportProjectOut(id=p.id, name=p.name) for p in projects], params=[],
    )


def project_entries(db: Session, project: Project) -> list[ReportCatalogueEntryOut]:
    """The layouts a project's runners can run: its effective set minus the ones it has hidden."""
    return [
        _entry(db, s.layout, scope="project", path=f"/api/v1/projects/{project.id}/custom-reports/{s.layout.id}/run")
        for s in report_layout_scope.resolve_project_layouts(db, project) if not s.hidden
    ]


def org_entries(db: Session, user: User, organization_id: uuid.UUID) -> list[ReportCatalogueEntryOut]:
    """The organisation layouts `user` can run organisation-wide, each listing the projects they may select."""
    organization = db.get(Organization, organization_id)
    assert organization is not None
    layouts = report_layout_scope.list_org_layouts(db, organization_id)
    if not layouts:
        return []
    readable = readable_projects(db, user, organization=organization, root_project=None, include_children=False)
    return [
        _entry(db, layout, scope="organization", path=f"/api/v1/orgs/{organization_id}/custom-reports/{layout.id}/run", projects=readable)
        for layout in layouts
    ]


__all__ = [
    "ENGINE_VERSION", "MAX_FANOUT_PROJECTS", "MODULE_KEY", "FanOutTooLargeError", "LayoutRun",
    "NoProjectsToRunError", "ProjectsNotInScopeError", "available_formats", "content_blocks_for",
    "content_key", "document_for", "render_input_for", "merge_evaluations", "org_entries",
    "project_entries", "record_run", "result_for", "run_organization_layout", "run_project_layout", "slug_for",
]
