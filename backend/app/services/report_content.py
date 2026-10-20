"""
Module: services.report_content

Per-report-type introduction, chapters and appendices across three tiers
(report template, project, organisation), .

Responsibilities:
- Report types: `report_type_options` lists the types an organisation can
  write content for (the requirements report plus every enabled module
  report, built from the registry so core never names a module's report);
  `valid_report_keys` is the write-time check.
- Storage: `get_scope_content`, `replace_scope_content`, `delete_content_for_scopes`
  over `models.report_content.ReportContent`.
- Resolution: `resolve_report_content` picks each of intro, chapters and
  appendices independently, tier first and then the specific report type before
  the "all reports" entry within a tier: template, the project, each ancestor
  project (nearest first), the organisation. A project's own description stands
  in for a blank requirements intro right after the project's own tier.
- Output: `content_markdown` joins resolved content into the pre/post Markdown the
  document builders take; `build_placeholders` and `content_blocks` serve the
  module-report path.

Design decisions:
- Ancestor fallback is always on and independent of `role_inheritance_mode`
  (the Action Types precedent, `services.project_hierarchy`). It reads
  boilerplate report text, not project data, and never returns an ancestor the
  caller could not already name through the project tree; edits and deletes
  stay scoped to rows a scope owns.
- Placeholders are a fixed allow-list substituted into the parsed text blocks
  (`report_model.markdown_to_blocks`), never into Markdown source and never a
  template engine, so a substituted value is ordinary text that cannot add
  headings, images or markup.
- A scope's blank entries are not stored: "no row" is the only way to say
  "inherit", so a blank save deletes the row.

Dependencies: SQLAlchemy, `models.report_content`, `modules.registry`,
`services.project_hierarchy`, `services.report_document` (image lookup).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.report_content import (
    ALL_REPORTS_KEY,
    REQUIREMENTS_REPORT_KEY,
    SCOPE_ORGANIZATION,
    SCOPE_PROJECT,
    SCOPE_TEMPLATE,
    ReportContent,
)
from app.schemas.report import ReportChapter, ReportContentEntry
from app.services.project_hierarchy import get_project_chain_ids
from app.services.report_document import resolve_report_images
from app.services.report_model import Block, markdown_to_blocks

# A resolved value that came from the project's own description rather than a
# stored row.
SCOPE_PROJECT_SUMMARY = "project_summary"

__all__ = [
    "ALL_REPORTS_KEY",
    "REQUIREMENTS_REPORT_KEY",
    "ReportTypeOption",
    "ResolvedContent",
    "ResolvedField",
    "build_placeholders",
    "bundle_entries",
    "chapters_markdown",
    "content_blocks",
    "content_entries",
    "content_markdown",
    "delete_content_for_scopes",
    "get_scope_content",
    "replace_scope_content",
    "report_key_for",
    "report_type_options",
    "resolve_report_content",
    "valid_report_keys",
]


def report_key_for(module_key: str, report_key: str) -> str:
    """The content key of a module report: `"<module_key>.<report_key>"`."""
    return f"{module_key}.{report_key}"


def valid_report_keys() -> set[str]:
    """Every key content may be written for: the requirements report, the
    "all reports" entry and every registered module report (whether or not its
    module is enabled for a particular organisation, so disabling a module never
    makes saved content unwritable)."""
    from app.modules.registry import get_all_reports  # lazy: the registry loads modules, which import the report framework

    return {REQUIREMENTS_REPORT_KEY, ALL_REPORTS_KEY, *(report_key_for(m, d.key) for m, d in get_all_reports())}


class ReportTypeOption(BaseModel):
    """A report type content can be written for, as the editors list it."""

    key: str
    title: str
    module_name: str | None = None


def report_type_options(db: Session, organization_id: UUID) -> list[ReportTypeOption]:
    """The report types an organisation's editors offer: the requirements
    report, then every module report whose module is enabled for the
    organisation, in registry order. The "all reports" entry is not listed; the
    editors add it themselves.

    Args:
        db: Database session.
        organization_id: The organisation.

    Returns:
        The options, requirements first.
    """
    from app.modules.registry import get_all_reports, get_module, is_module_enabled  # lazy: see `valid_report_keys`

    options = [ReportTypeOption(key=REQUIREMENTS_REPORT_KEY, title="Requirements report")]
    for module_key, definition in get_all_reports():
        if not is_module_enabled(db, organization_id, module_key):
            continue
        module = get_module(module_key)
        options.append(ReportTypeOption(
            key=report_key_for(module_key, definition.key), title=definition.title,
            module_name=module.name if module else module_key,
        ))
    return options


# --- Storage ---------------------------------------------------------------------


def _is_blank(entry: ReportContentEntry) -> bool:
    return not entry.intro.strip() and not entry.chapters and not entry.appendices


def get_scope_content(db: Session, scope_type: str, scope_id: UUID) -> list[ReportContent]:
    """The rows one scope owns (never an ancestor's), ordered by report key.

    Args:
        db: Database session.
        scope_type: `template`, `project` or `organization`.
        scope_id: The scope's id.

    Returns:
        The scope's `ReportContent` rows.
    """
    return list(db.scalars(
        select(ReportContent)
        .where(ReportContent.scope_type == scope_type, ReportContent.scope_id == scope_id)
        .order_by(ReportContent.report_key)
    ).all())


def content_entries(db: Session, scope_type: str, scope_id: UUID) -> list[ReportContentEntry]:
    """The rows one scope owns, as API entries (see `get_scope_content`)."""
    return [
        ReportContentEntry(report_key=r.report_key, intro=r.intro, chapters=r.chapters, appendices=r.appendices)
        for r in get_scope_content(db, scope_type, scope_id)
    ]


def replace_scope_content(
    db: Session, scope_type: str, scope_id: UUID, entries: Sequence[ReportContentEntry], *, skip_unknown: bool = False,
) -> list[str]:
    """Makes the scope's stored content exactly `entries`: rows are created or
    updated for non-blank entries and removed for blank or absent ones.

    Does not commit.

    Args:
        db: Database session.
        scope_type: `template`, `project` or `organization`.
        scope_id: The scope's id (ownership is the caller's concern).
        entries: The desired content, at most one entry per report key.
        skip_unknown: Ignore entries for report types this installation does
            not know (a bundle from a build with a module this one lacks)
            instead of rejecting them.

    Returns:
        The report keys skipped as unknown (always empty unless `skip_unknown`).

    Raises:
        HTTPException: 400 for an unknown (unless `skip_unknown`) or repeated report key.
    """
    valid = valid_report_keys()
    skipped = [e.report_key for e in entries if e.report_key not in valid] if skip_unknown else []
    entries = [e for e in entries if e.report_key not in skipped]
    seen: set[str] = set()
    for entry in entries:
        if entry.report_key not in valid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown report type '{entry.report_key}'.")
        if entry.report_key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Report type '{entry.report_key}' appears more than once.")
        seen.add(entry.report_key)
    existing = {row.report_key: row for row in get_scope_content(db, scope_type, scope_id)}
    wanted = {e.report_key: e for e in entries if not _is_blank(e)}
    for key, row in existing.items():
        if key not in wanted:
            db.delete(row)
    for key, entry in wanted.items():
        row = existing.get(key)
        if row is None:
            row = ReportContent(scope_type=scope_type, scope_id=scope_id, report_key=key)
            db.add(row)
        row.intro = entry.intro
        row.chapters = [c.model_dump() for c in entry.chapters]
        row.appendices = [c.model_dump() for c in entry.appendices]
    db.flush()
    return skipped


def bundle_entries(data: dict[str, Any], key: str, legacy_keys: tuple[str, str, str]) -> list[ReportContentEntry]:
    """Reads a scope's content from an export bundle's JSON object.

    Bundles written before per-report-type content carried the requirements
    report's three fields directly; those become a `requirements` entry.
    Entries that do not parse are dropped.

    Args:
        data: The bundle object for the scope (template, project or organisation).
        key: Where current bundles keep the entry list (`"content"` or `"report_content"`).
        legacy_keys: The old intro, chapters and appendices field names.

    Returns:
        The scope's entries.
    """
    entries: list[ReportContentEntry] = []
    for raw in data.get(key) or []:
        try:
            entries.append(ReportContentEntry.model_validate(raw))
        except ValueError:
            continue
    intro, chapters, appendices = (data.get(k) for k in legacy_keys)
    if not entries and (intro or chapters or appendices):
        try:
            entries.append(ReportContentEntry(
                report_key=REQUIREMENTS_REPORT_KEY, intro=intro or "", chapters=chapters or [], appendices=appendices or [],
            ))
        except ValueError:
            pass
    return entries


def delete_content_for_scopes(db: Session, scope_type: str, scope_ids: Iterable[UUID]) -> None:
    """Deletes every content row of the given scopes (their owners have no
    foreign key to cascade through). Does not commit.

    Args:
        db: Database session.
        scope_type: `template`, `project` or `organization`.
        scope_ids: The owners being deleted.
    """
    ids = list(scope_ids)
    if ids:
        db.execute(ReportContent.__table__.delete().where(
            ReportContent.scope_type == scope_type, ReportContent.scope_id.in_(ids),
        ))


# --- Resolution -------------------------------------------------------------------


@dataclass(frozen=True)
class ContentSource:
    """Where a resolved value came from.

    Attributes:
        scope_type: `template`, `project`, `organization` or `project_summary`.
        scope_id: The owning scope's id.
        scope_name: The template, project or organisation name.
        report_key: The key of the row it came from (`"*"` for the "all reports"
            entry), or `""` for a project description.
    """

    scope_type: str
    scope_id: UUID
    scope_name: str
    report_key: str


@dataclass
class ResolvedField:
    """One resolved field and its source (`None` when nothing set it)."""

    value: Any
    source: ContentSource | None = None


@dataclass
class ResolvedContent:
    """The effective intro, chapters and appendices for one report."""

    intro: ResolvedField = field(default_factory=lambda: ResolvedField(""))
    chapters: ResolvedField = field(default_factory=lambda: ResolvedField([]))
    appendices: ResolvedField = field(default_factory=lambda: ResolvedField([]))


@dataclass(frozen=True)
class _Tier:
    scope_type: str
    scope_id: UUID
    name: str
    summary: str = ""


def resolve_report_content(
    db: Session, report_key: str, organization: Organization, project: Project | None = None,
    template: ReportTemplate | None = None,
) -> ResolvedContent:
    """Resolves the content a report of `report_key` uses.

    Each field resolves on its own: the first non-empty value wins, walking
    the tiers (template, project, ancestors nearest first, organisation) and,
    within a tier, the report's own entry before the "all reports" entry. For
    the requirements report only, a project's description stands in for a blank
    intro directly after the project's own tier (the ancestors are consulted
    after it).

    Args:
        db: Database session.
        report_key: `"requirements"` or `"<module_key>.<report_key>"`.
        organization: The organisation the report is for.
        project: The project, or `None` for an organisation-wide report.
        template: The selected report template, or `None`.

    Returns:
        The resolved fields with their sources.
    """
    tiers: list[_Tier] = []
    if template is not None:
        tiers.append(_Tier(SCOPE_TEMPLATE, template.id, template.name))
    if project is not None:
        names: dict[UUID, str] = {project.id: project.name}
        chain = get_project_chain_ids(db, project.id)
        for pid in chain[1:]:
            ancestor = db.get(Project, pid)
            # Ancestors always share the organisation; the check is belt and braces.
            if ancestor is not None and ancestor.organization_id == organization.id:
                names[pid] = ancestor.name
        summary = project.summary if report_key == REQUIREMENTS_REPORT_KEY else ""
        for i, pid in enumerate(chain):
            if pid in names:
                tiers.append(_Tier(SCOPE_PROJECT, pid, names[pid], summary if i == 0 else ""))
    tiers.append(_Tier(SCOPE_ORGANIZATION, organization.id, organization.name))

    keys = [report_key, ALL_REPORTS_KEY]
    rows = db.scalars(select(ReportContent).where(
        or_(*(and_(ReportContent.scope_type == t.scope_type, ReportContent.scope_id == t.scope_id) for t in tiers)),
        ReportContent.report_key.in_(keys),
    )).all()
    by_scope: dict[tuple[str, UUID, str], ReportContent] = {(r.scope_type, r.scope_id, r.report_key): r for r in rows}

    resolved = ResolvedContent()
    for attr in ("intro", "chapters", "appendices"):
        done = False
        for tier in tiers:
            for key in keys:
                row = by_scope.get((tier.scope_type, tier.scope_id, key))
                value = getattr(row, attr) if row is not None else None
                if value:
                    setattr(resolved, attr, ResolvedField(value, ContentSource(tier.scope_type, tier.scope_id, tier.name, key)))
                    done = True
                    break
            if not done and attr == "intro" and tier.summary:
                resolved.intro = ResolvedField(
                    tier.summary, ContentSource(SCOPE_PROJECT_SUMMARY, tier.scope_id, tier.name, ""),
                )
                done = True
            if done:
                break
    return resolved


# --- Output -------------------------------------------------------------------------


def chapters_markdown(chapters: Sequence[dict[str, Any] | ReportChapter]) -> str:
    """Joins chapters into Markdown, one `# title` heading and body each;
    chapters without a title are skipped.

    Args:
        chapters: `{title, body}` mappings or `ReportChapter`s.

    Returns:
        The Markdown source.
    """
    parts = []
    for chapter in chapters:
        data = chapter.model_dump() if isinstance(chapter, ReportChapter) else chapter
        if data.get("title"):
            parts.append(f"# {data['title']}\n\n{data.get('body', '')}")
    return "\n\n".join(parts)


def content_markdown(content: ResolvedContent) -> tuple[str, str]:
    """The Markdown printed before the report body (intro, then chapters) and
    after it (appendices).

    Args:
        content: Resolved content.

    Returns:
        `(pre_markdown, post_markdown)`.
    """
    pre = "\n\n".join(s for s in [content.intro.value, chapters_markdown(content.chapters.value)] if s)
    return pre, chapters_markdown(content.appendices.value)


def build_placeholders(*, project_name: str, report_title: str, generated_on: date, organisation: str) -> dict[str, str]:
    """The values the fixed placeholder allow-list substitutes.

    Args:
        project_name: The project, or the organisation for an organisation-wide report.
        report_title: The title printed on the report.
        generated_on: The generation date (printed as `YYYY-MM-DD`).
        organisation: The organisation name.

    Returns:
        A mapping keyed by `report_model.PLACEHOLDER_NAMES`.
    """
    return {
        "project_name": project_name, "report_title": report_title,
        "generated_on": generated_on.isoformat(), "organisation": organisation,
    }


def content_blocks(
    db: Session, organization_id: UUID, content: ResolvedContent, placeholders: dict[str, str],
) -> tuple[list[Block], list[Block]]:
    """Resolved content as document blocks: those before the report body and
    those after it, with placeholders filled and images resolved (tenant-checked).

    Args:
        db: Database session.
        organization_id: The organisation, for the image tenant check.
        content: Resolved content.
        placeholders: See `build_placeholders`.

    Returns:
        `(before, after)` block lists.
    """
    pre, post = content_markdown(content)
    images = resolve_report_images(db, organization_id, pre, post)
    return markdown_to_blocks(pre, images, placeholders), markdown_to_blocks(post, images, placeholders)
