"""
Module: services.report_pack_run

Runs a report pack: every entry is produced as the caller and the files are returned as one zip with a manifest.

Responsibilities:
- `run_project_pack` / `run_organization_pack`: run a pinned pack version for a project, or across the projects the
  caller can read, with one set of pack variable values.
- `preview_*`: the same resolution and evaluation without rendering, storing or recording anything, so a person can
  see how many records each entry would include before they download.
- `build_zip`: the files plus `manifest.json`, with flat server-built names.
- `record_pack_run`: one `GeneratedReport` row per included entry, sharing a `pack_run_id`.

Design decisions:
- **Each entry goes through the report's own run path as the caller.** A layout entry is `custom_report_run`'s
  project or organisation run, a module report entry `report_module_run`'s, so every entry keeps its own gate,
  caps, cell tones and record codes; the pack adds no visibility rule. A record the caller cannot read is counted
  and never named inside the entry, exactly as in a single run.
- **An entry that cannot run is skipped and listed, never silently dropped** (the layout is not reachable, was
  hidden by the project, does not offer the format, its module is off, the caller lacks the role, its variables
  cannot be set). The manifest says which and why in words that carry no record content. A pack with no runnable
  entry is an error (`NothingToRunError`).
- **Variables.** The pack declares variables; a layout entry receives the pack variable of the same name, type and
  list-ness, or the value the entry fixes itself, else the layout's own default. Values are checked by the layout's
  declarations (`report_variables.resolve_values`), so a pack value cannot bypass a layout's rules. They narrow
  what a report shows and are not access control: the manifest records the values used and the preview shows the
  counts, so a wrong choice is visible before anything is sent on.
- **Names.** The zip holds flat files `NN-<stem>.<ext>` (`NN` is the entry's position, so names are unique and
  ordered); the stem is the entry's `filename` template, else its layout's `file_name`, else its layout or report
  name, filled in and reduced to letters, digits and `._- ` (`services.report_file_names`), so a name from user
  text or a record value can never be a path. The zip itself is named by the pack's `file_name`, else the
  organisation's default, else scope then pack name.
- **Bounded.** At most `MAX_ENTRIES` entries, `MAX_ZIP_BYTES` of output and `MAX_PACK_SECONDS` of wall time for the
  whole pack (each layout entry also keeps its own caps). Going over is `PackLimitError`; nothing partial is returned
  or recorded.
- The manifest holds names, keys, counts, formats, variable values and UTC times; never a cell value.

Dependencies: `services.custom_report_run`, `services.report_module_run`, `services.report_pack_scope`,
`services.report_layout_scope`, `services.report_variables`.
"""

from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generated_report import GeneratedReport
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack, ReportPackVersion
from app.models.user import User
from app.services import custom_report_run, report_layout_scope, report_layouts, report_pack_sets
from app.services.client_date import effective_today
from app.services.report_file_names import clean_filename, render_stem
from app.services.report_framework import readable_projects
from app.services.report_layout_eval import LayoutLimitError
from app.services.report_layout_tree import record_types_of
from app.services.report_module_run import (
    ModuleReportUnavailableError,
    find_report,
    render_module_report,
    run_module_report,
)
from app.services.report_variables import VariableValueError, resolve_values, variable_text

MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_PACK_SECONDS = 120.0
#: The bounds of a background pack run (the background layout limits apply to each entry too).
ASYNC_MAX_ZIP_BYTES = 200 * 1024 * 1024
ASYNC_MAX_PACK_SECONDS = 900.0
MANIFEST_SCHEMA = 1
MANIFEST_NAME = "manifest.json"

STATUS_INCLUDED = "included"
STATUS_NOT_AVAILABLE = "not_available"


class NothingToRunError(LookupError):
    """No entry of the pack can be run here (or the pack has no entries)."""


class PackLimitError(ValueError):
    """The pack's output or run time went over a bound."""


@dataclass
class EntryOutcome:
    """What happened to one entry.

    Attributes:
        index: Position in the pack (0-based).
        kind: `layout` or `report`.
        title: The layout's or report's name.
        format: The requested format.
        status: `included` or `not_available`.
        reason: Why it is not available (never record content).
        stem: The file stem chosen for it.
        extension: The produced file's extension (`zip` for a multi-sheet CSV).
        content: The file (empty for a preview or a skipped entry).
        record_counts: Records included in the report by artefact type, after the layout's conditions (a module
            report: the rows of its sections under `rows`).
        records: Total records (or rows) included, for the preview.
        layout_version: The pinned layout version, for a layout.
        variables: The variable values the entry ran with (an organisation run: the first project's).
        variables_by_project: Organisation run only, and only when the projects' values differ (a saved set as each
            project overrides it): `{project name: values}`.
        warnings: Run remarks (a value no longer among its options, projects left out).
        run: The finished layout run, kept so provenance can be written.
        report_key: `<module key>.<report key>` for a module report.
    """

    index: int
    kind: str
    title: str
    format: str
    status: str = STATUS_NOT_AVAILABLE
    reason: str | None = None
    stem: str = "report"
    extension: str = ""
    content: bytes = b""
    record_counts: dict[str, int] = field(default_factory=dict)
    records: int = 0
    layout_version: int | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    variables_by_project: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    run: custom_report_run.LayoutRun | None = None
    report_key: str | None = None

    @property
    def filename(self) -> str | None:
        """The name inside the zip, or `None` for an entry that was not produced."""
        if self.status != STATUS_INCLUDED or not self.extension:
            return None
        return f"{self.index + 1:02d}-{self.stem}.{self.extension}"


@dataclass
class PackRun:
    """A finished (or previewed) pack run.

    Attributes:
        pack / version: The pack and the pinned version that ran.
        organization: The organisation.
        project: The project of a project-level run, `None` for an organisation-wide run.
        generated_at: When the run started (UTC).
        values: The resolved pack variable values.
        entries: One outcome per entry, in order.
        template_id: The branding template applied to documents, if any.
        pack_run_id: Shared by the provenance rows.
        set_name: The saved variable set the values started from, if one was chosen.
        warnings: Remarks on the values (a set value no longer among its options, names ignored).
        today: The caller's calendar day when the run started, which `{{generated_on}}` in a file name uses.
    """

    pack: ReportPack
    version: ReportPackVersion
    organization: Organization
    project: Project | None
    generated_at: datetime
    values: dict[str, Any]
    entries: list[EntryOutcome]
    template_id: uuid.UUID | None = None
    pack_run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    set_name: str | None = None
    warnings: list[str] = field(default_factory=list)
    today: date = field(default_factory=effective_today)

    @property
    def included(self) -> list[EntryOutcome]:
        """The entries that produced a file."""
        return [e for e in self.entries if e.status == STATUS_INCLUDED]

    @property
    def scope_label(self) -> str:
        """The name printed as the pack's scope."""
        return self.project.name if self.project is not None else self.organization.name


# --- variables ---------------------------------------------------------------------------------------------------


def resolve_pack_values(version: ReportPackVersion, supplied: Mapping[str, Any] | None) -> dict[str, Any]:
    """The pack variables' values for a run: what was supplied, else each default.

    Raises:
        VariableValueError: A value is missing, undeclared or unacceptable.
    """
    return resolve_values(version.definition.get("variables"), supplied, today=effective_today())


def entry_variables(
    pack_declarations: Sequence[Mapping[str, Any]] | None, pack_values: Mapping[str, Any],
    layout_declarations: Sequence[Mapping[str, Any]] | None, fixed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The values to offer one layout entry: its fixed ones, else the pack variable of the same name, type and list-ness.

    A layout variable neither fixed nor matched is left out so the layout's own default applies.
    """
    pack_by_name = {d["name"]: d for d in pack_declarations or []}
    out: dict[str, Any] = {}
    for declaration in layout_declarations or []:
        name = declaration["name"]
        if fixed and name in fixed:
            out[name] = fixed[name]
            continue
        match = pack_by_name.get(name)
        if (
            match is not None and match["type"] == declaration["type"]
            and bool(match.get("multiple")) == bool(declaration.get("multiple"))
        ):
            out[name] = pack_values[name]
    return out


# --- entries -----------------------------------------------------------------------------------------------------


def _stem(entry: Mapping[str, Any], fallback: str) -> str:
    """The entry's name before it has run: its template with nothing filled in, else `fallback` (a plain name)."""
    return clean_filename(str(entry.get("filename") or fallback))


def _layout_stem(entry: Mapping[str, Any], run: custom_report_run.LayoutRun, fallback: str) -> str:
    """A layout entry's stem: its own `filename` template, else the layout's `file_name`, else `fallback`.

    The values are the layout run's (so `{{var.x}}` is that entry's variable and `{{report_title}}` the layout's name).
    """
    plain, texts = custom_report_run.file_values(run, entry["format"])
    for template in (entry.get("filename"), run.version.tree.get("file_name")):
        stem = render_stem(template, plain, texts)
        if stem is not None:
            return stem
    return fallback


def _report_stem(
    entry: Mapping[str, Any], organization: Organization, project: Project | None, title: str, fallback: str,
) -> str:
    """A module report entry's stem: its `filename` template filled with the run facts, else `fallback`."""
    plain = {
        "report_title": title, "project_name": project.name if project else organization.name, "organisation": organization.name,
        "project_code": (project.code if project else "") or "", "generated_on": effective_today().isoformat(),
        "format": entry["format"],
    }
    return render_stem(entry.get("filename"), plain) or fallback


def _find_layout(
    db: Session, organization: Organization, project: Project | None, entry: Mapping[str, Any],
) -> ReportLayout | None:
    """The layout an entry names as the scope sees it (not hidden), or `None`."""
    name = str(entry["name"]).strip().casefold()
    tier = entry.get("tier")
    if project is None:
        if tier == "project":
            return None
        return next((layout for layout in report_layout_scope.list_org_layouts(db, organization.id) if layout.name.casefold() == name), None)
    for scoped in report_layout_scope.resolve_project_layouts(db, project):
        if scoped.layout.name.casefold() != name or scoped.hidden:
            continue
        if tier == "organization" and scoped.origin != "organization":
            return None
        if tier == "project" and scoped.origin == "organization":
            return None
        return scoped.layout
    return None


def pack_record_types(
    db: Session, organization_id: uuid.UUID, project: Project | None, definition: Mapping[str, Any],
) -> list[str]:
    """The record types a pack's entries read, sorted: the declared types of each module report and the types the
    tree of each layout reads, as the asking scope reaches them (a layout it cannot reach, or a report that is not
    installed, adds none).

    Args:
        db: Active session.
        organization_id: The pack's organisation.
        project: The asking project, or `None` for the organisation tier.
        definition: The pack's definition.

    Returns:
        The distinct type keys, alphabetically.
    """
    organization = db.get(Organization, organization_id)
    found: set[str] = set()
    for entry in definition.get("entries", []):
        if entry.get("kind") == "report":
            report = find_report(entry["module_key"], entry["report"])
            if report is not None:
                found.update(report.record_types)
        elif organization is not None:
            layout = _find_layout(db, organization, project, entry)
            version = report_layouts.get_version(db, layout.id, layout.current_version) if layout is not None else None
            if version is not None:
                found.update(record_types_of(version.tree))
    return sorted(found)


def _clock_left(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise PackLimitError("The pack took too long to produce. Remove some reports or narrow what they cover.")


def _layout_entry(
    db: Session, user: User, organization: Organization, project: Project | None, entry: Mapping[str, Any],
    index: int, pack_declarations: Sequence[Mapping[str, Any]] | None, pack_values: Mapping[str, Any], *,
    values_for: Callable[[Project], Mapping[str, Any]] | None, template: ReportTemplate | None,
    project_ids: Sequence[uuid.UUID] | None, include_children: bool, render: bool, background: bool = False,
) -> EntryOutcome:
    outcome = EntryOutcome(index, "layout", str(entry["name"]), entry["format"], stem=_stem(entry, str(entry["name"])))
    layout = _find_layout(db, organization, project, entry)
    if layout is None:
        outcome.reason = "No report layout of that name is available here."
        return outcome
    version = report_layouts.get_version(db, layout.id, layout.current_version)
    assert version is not None
    if entry["format"] not in custom_report_run.available_formats(layout.family, version.tree) or entry["format"] == "json":
        outcome.reason = f"The layout cannot be produced as {entry['format']}."
        return outcome
    outcome.layout_version = version.version
    declarations = version.tree.get("variables")

    def resolved_for(values: Mapping[str, Any]) -> dict[str, Any]:
        supplied = entry_variables(pack_declarations, values, declarations, entry.get("variables"))
        return resolve_values(declarations, supplied, today=effective_today())

    by_project: dict[str, dict[str, Any]] = {}

    def variables_for(target: Project) -> dict[str, Any]:
        assert values_for is not None
        resolved = resolved_for(values_for(target))
        by_project[target.name] = resolved
        return resolved

    try:
        values = resolved_for(pack_values)
        outcome.variables = values
        if project is not None:
            run = custom_report_run.run_project_layout(
                db, user, project, layout, version, include_children=include_children, variables=values,
                background=background,
            )
        else:
            run = custom_report_run.run_organization_layout(
                db, user, organization, layout, version, project_ids=project_ids, variables=values, background=background,
                variables_for=variables_for if values_for is not None else None,
            )
    except VariableValueError as exc:
        names = ", ".join(sorted({name for name, _ in exc.problems if name}))
        outcome.reason = f"Its variables could not be set{': ' + names if names else ''}."
        return outcome
    except (custom_report_run.NoProjectsToRunError, custom_report_run.ProjectsNotInScopeError):
        outcome.reason = "There is no project to run it for."
        return outcome
    except custom_report_run.FanOutTooLargeError:
        outcome.reason = "It would cover too many projects."
        return outcome
    except LayoutLimitError as exc:
        raise PackLimitError("A report in the pack is too large to produce while you wait.") from exc
    if by_project and any(v != outcome.variables for v in by_project.values()):
        outcome.variables_by_project = by_project
    outcome.run = run
    outcome.stem = _layout_stem(entry, run, outcome.stem)
    outcome.record_counts = dict(run.evaluated.stats.records_included)
    outcome.records = sum(outcome.record_counts.values())
    outcome.warnings = [*run.notes, *run.evaluated.warnings][:5]
    if render:
        rendered = custom_report_run.render_file(db, run, entry["format"], template)
        outcome.content, outcome.extension = rendered.content, rendered.extension
    outcome.status = STATUS_INCLUDED
    return outcome


def _report_entry(
    db: Session, user: User, organization: Organization, project: Project | None, entry: Mapping[str, Any], index: int, *,
    template: ReportTemplate | None, include_children: bool, render: bool,
) -> EntryOutcome:
    module_key, report_key = entry["module_key"], entry["report"]
    definition = find_report(module_key, report_key)
    outcome = EntryOutcome(
        index, "report", definition.title if definition else f"{module_key}.{report_key}", entry["format"],
        stem=_stem(entry, definition.slug if definition else report_key), report_key=f"{module_key}.{report_key}",
    )
    if definition is None:
        outcome.reason = "That report is not installed."
        return outcome
    outcome.stem = _report_stem(entry, organization, project, definition.title, outcome.stem)
    try:
        result = run_module_report(
            db, user, organization=organization, project=project, module_key=module_key, definition=definition,
            params=entry.get("params"), include_children=include_children,
        )
    except ModuleReportUnavailableError as exc:
        outcome.reason = str(exc)
        return outcome
    outcome.records = sum(len(section.rows) for section in result.sections)
    outcome.record_counts = {"rows": outcome.records}
    if render:
        outcome.content = render_module_report(db, result, entry["format"], organization=organization, template=template)
        outcome.extension = entry["format"]
    outcome.status = STATUS_INCLUDED
    return outcome


def _template(db: Session, organization: Organization, version: ReportPackVersion, template_id: uuid.UUID | None) -> ReportTemplate | None:
    """The branding template: the one requested, else the pack's own by name, else the organisation's default."""
    if template_id is not None:
        return db.scalar(select(ReportTemplate).where(ReportTemplate.id == template_id, ReportTemplate.organization_id == organization.id))
    name = version.definition.get("template")
    if name:
        named = db.scalar(select(ReportTemplate).where(ReportTemplate.organization_id == organization.id, ReportTemplate.name == name))
        if named is not None:
            return named
    return db.scalar(select(ReportTemplate).where(ReportTemplate.organization_id == organization.id, ReportTemplate.is_default))


def _run(
    db: Session, user: User, pack: ReportPack, version: ReportPackVersion, organization: Organization,
    project: Project | None, values: dict[str, Any], *, template_id: uuid.UUID | None, project_ids: Sequence[uuid.UUID] | None,
    include_children: bool, render: bool, values_for: Callable[[Project], Mapping[str, Any]] | None = None,
    set_name: str | None = None, warnings: Sequence[str] = (), background: bool = False,
) -> PackRun:
    entries = version.definition.get("entries", [])
    if not entries:
        raise NothingToRunError("This pack has no reports.")
    started = datetime.now(UTC)
    deadline = time.monotonic() + (ASYNC_MAX_PACK_SECONDS if background else MAX_PACK_SECONDS)
    template = _template(db, organization, version, template_id)
    declarations = version.definition.get("variables")
    outcomes: list[EntryOutcome] = []
    for index, entry in enumerate(entries):
        _clock_left(deadline)
        if entry["kind"] == "layout":
            outcomes.append(_layout_entry(
                db, user, organization, project, entry, index, declarations, values, values_for=values_for,
                template=template, project_ids=project_ids, include_children=include_children, render=render,
                background=background,
            ))
        else:
            outcomes.append(_report_entry(
                db, user, organization, project, entry, index, template=template, include_children=include_children, render=render,
            ))
    run = PackRun(
        pack, version, organization, project, started, values, outcomes, template.id if template else None,
        set_name=set_name, warnings=list(warnings),
    )
    if not run.included:
        raise NothingToRunError("None of the reports in this pack can be run here.")
    if sum(len(e.content) for e in outcomes) > (ASYNC_MAX_ZIP_BYTES if background else MAX_ZIP_BYTES):
        raise PackLimitError("The pack is too large to produce while you wait.")
    return run


class UnknownSetError(LookupError):
    """The chosen saved variable set is not one this scope can use."""


def _chosen_values(
    db: Session, pack: ReportPack, version: ReportPackVersion, set_id: uuid.UUID | None, project: Project | None,
    supplied: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str | None, list[str]]:
    """`(values to resolve, set name, remarks)`: the chosen set's values, then what the person typed over them."""
    if set_id is None:
        return dict(supplied or {}), None, []
    try:
        stored, remarks, name = report_pack_sets.set_values_for(db, pack, version, set_id, project)
    except LookupError as exc:
        raise UnknownSetError(str(exc)) from exc
    return {**stored, **(supplied or {})}, name, remarks


def check_request(
    db: Session, pack: ReportPack, version: ReportPackVersion, project: Project | None, supplied: Mapping[str, Any] | None,
    set_id: uuid.UUID | None,
) -> None:
    """Validates a run request's set and variable values now, so a bad request fails when it is made and not in a queued job.

    Raises:
        UnknownSetError / VariableValueError: As `run_project_pack`.
    """
    chosen, _, _ = _chosen_values(db, pack, version, set_id, project, supplied)
    resolve_pack_values(version, chosen)


def run_project_pack(
    db: Session, user: User, project: Project, pack: ReportPack, version: ReportPackVersion,
    supplied: Mapping[str, Any] | None = None, *, template_id: uuid.UUID | None = None, include_children: bool = False,
    render: bool = True, set_id: uuid.UUID | None = None, background: bool = False,
) -> PackRun:
    """Runs a pack for `project` as `user`.

    Args:
        db: Active session (read only).
        user: The caller (the route has authorised them for the project).
        project: The project.
        pack: A pack the project can reach (not hidden).
        version: The pinned version (the pack's current one).
        supplied: Pack variable values; they win over a chosen set's, and a variable left out takes its default.
        template_id: A branding template of the organisation (else the pack's default by name).
        include_children: Also read readable child projects.
        render: Produce the files; `False` evaluates only (the preview of counts).
        set_id: A saved variable set to start from, as this project sees it (its overrides applied).
        background: Use the larger bounds of a background run.

    Returns:
        The run.

    Raises:
        UnknownSetError: The set is not one this project can use.
        VariableValueError: A pack variable value is missing, undeclared or unacceptable.
        NothingToRunError: No entry can be run.
        PackLimitError: The pack went over a bound.
    """
    organization = db.get(Organization, project.organization_id)
    assert organization is not None
    chosen, set_name, remarks = _chosen_values(db, pack, version, set_id, project, supplied)
    values = resolve_pack_values(version, chosen)
    remarks += report_pack_sets.stale_warnings(db, version, chosen, [project.id]) if set_id is not None else []
    return _run(
        db, user, pack, version, organization, project, values, template_id=template_id, project_ids=None,
        include_children=include_children, render=render, set_name=set_name, warnings=remarks, background=background,
    )


def run_organization_pack(
    db: Session, user: User, organization: Organization, pack: ReportPack, version: ReportPackVersion,
    supplied: Mapping[str, Any] | None = None, *, template_id: uuid.UUID | None = None,
    project_ids: Sequence[uuid.UUID] | None = None, render: bool = True, set_id: uuid.UUID | None = None,
    background: bool = False,
) -> PackRun:
    """Runs an organisation pack: each layout entry once per project the caller can read (or the selected ones, merged).

    A chosen saved set is applied per project: each project's entries take that project's effective values, the set's
    own values with the project's overrides (and its ancestors') layered over them.

    Raises:
        UnknownSetError / VariableValueError / NothingToRunError / PackLimitError: As `run_project_pack`.
    """
    chosen, set_name, remarks = _chosen_values(db, pack, version, set_id, None, supplied)
    values = resolve_pack_values(version, chosen)
    values_for: Callable[[Project], Mapping[str, Any]] | None = None
    if set_id is not None:
        cache: dict[uuid.UUID, dict[str, Any]] = {}

        def values_for(target: Project) -> Mapping[str, Any]:
            if target.id not in cache:
                stored, _, _ = _chosen_values(db, pack, version, set_id, target, supplied)
                cache[target.id] = resolve_pack_values(version, stored)
            return cache[target.id]

        scope = readable_projects(db, user, organization=organization, root_project=None, include_children=False)
        remarks += report_pack_sets.stale_warnings(db, version, chosen, [p.id for p in scope][: custom_report_run.MAX_FANOUT_PROJECTS])
    return _run(
        db, user, pack, version, organization, None, values, template_id=template_id, project_ids=project_ids,
        include_children=False, render=render, values_for=values_for, set_name=set_name, warnings=remarks,
        background=background,
    )


# --- output ------------------------------------------------------------------------------------------------------


def manifest_for(run: PackRun) -> dict[str, Any]:
    """The `manifest.json` content: what was asked, what was included and what was not (no cell values)."""
    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "pack": {"name": run.pack.name, "version": run.version.version, "definition_hash": run.version.definition_hash},
        "scope": {"type": "project" if run.project else "organization", "name": run.scope_label},
        "generated_at": run.generated_at.isoformat(),
        "variables": run.values,
        "variable_set": run.set_name,
        "warnings": run.warnings,
        "entries": [
            {
                "position": e.index + 1, "kind": e.kind, "title": e.title, "format": e.format, "status": e.status,
                "file": e.filename, "reason": e.reason, "layout_version": e.layout_version,
                "report": e.report_key, "records": e.records, "record_counts": e.record_counts,
                "variables": e.variables, "variables_by_project": e.variables_by_project, "warnings": e.warnings,
            }
            for e in run.entries
        ],
        "not_available": sum(1 for e in run.entries if e.status == STATUS_NOT_AVAILABLE),
    }


def build_zip(run: PackRun, *, background: bool = False) -> bytes:
    """The pack as a zip: `manifest.json` then each included file under its flat name.

    Raises:
        PackLimitError: The zip would exceed `MAX_ZIP_BYTES`.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest_for(run), indent=2, ensure_ascii=False))
        for entry in run.included:
            assert entry.filename is not None
            archive.writestr(entry.filename, entry.content)
    data = buffer.getvalue()
    if len(data) > (ASYNC_MAX_ZIP_BYTES if background else MAX_ZIP_BYTES):
        raise PackLimitError("The pack is too large to produce while you wait.")
    return data


def zip_stem(run: PackRun) -> str:
    """The download name (without extension): the pack's `file_name` template, else the organisation's default, else
    scope then pack name, made safe. A template that fills in to nothing usable falls through to the next."""
    plain = {
        "report_title": run.pack.name, "project_name": run.scope_label, "organisation": run.organization.name,
        "project_code": (run.project.code if run.project is not None else "") or "", "generated_on": run.today.isoformat(),
        "layout_version": str(run.version.version), "format": "zip",
    }
    texts = variable_text(run.version.definition.get("variables"), run.values)
    for template in (run.version.definition.get("file_name"), run.organization.report_file_name):
        stem = render_stem(template, plain, texts)
        if stem is not None:
            return stem
    return f"{clean_filename(run.scope_label)}-{clean_filename(run.pack.name)}"


def record_pack_run(
    db: Session, user: User, run: PackRun, *, requested_project_ids: Sequence[uuid.UUID] | None = None,
    include_children: bool = False,
) -> list[GeneratedReport]:
    """Adds one provenance row per included entry, sharing `run.pack_run_id` (the caller commits).

    A layout entry uses the layout run's provenance (`custom_report_run.provenance_fields`); a module report entry
    records the report key, its rows and the projects it covered. The pack and its version are in `params`.
    """
    rows: list[GeneratedReport] = []
    pack_info = {"pack_id": str(run.pack.id), "pack_version": run.version.version, "entry": 0}
    for entry in run.included:
        if entry.run is not None:
            row = custom_report_run.record_run(
                db, user, entry.run, entry.format, report_template_id=run.template_id,
                include_children=include_children, requested_project_ids=requested_project_ids,
            )
        else:
            counts: dict[str, int] = defaultdict(int, entry.record_counts)
            assert entry.report_key is not None
            row = GeneratedReport(
                organization_id=run.organization.id, project_id=run.project.id if run.project else None,
                scope="project" if run.project else "organization",
                layout_id=uuid.uuid5(uuid.NAMESPACE_URL, f"report:{entry.report_key}"), layout_name=entry.title,
                layout_version=0, tree_hash="", requested_by=user.id, created_at=run.generated_at, format=entry.format,
                engine_version=custom_report_run.ENGINE_VERSION, report_key=entry.report_key, status="completed",
                params=custom_report_run.run_params(run.template_id, include_children, requested_project_ids),
                scope_project_ids=[str(run.project.id)] if run.project else [], widgets=[], record_counts=dict(counts),
                stats={"rows": entry.records}, source_digest="",
            )
            db.add(row)
        row.pack_run_id = run.pack_run_id
        row.params = {
            **row.params, **pack_info, "entry": entry.index + 1, "pack_variables": run.values, "variable_set": run.set_name,
        }
        rows.append(row)
    return rows


__all__ = [
    "ASYNC_MAX_PACK_SECONDS", "ASYNC_MAX_ZIP_BYTES", "MAX_PACK_SECONDS", "MAX_ZIP_BYTES", "STATUS_INCLUDED",
    "STATUS_NOT_AVAILABLE", "EntryOutcome", "NothingToRunError", "PackLimitError", "PackRun", "UnknownSetError", "build_zip",
    "check_request", "entry_variables", "manifest_for", "record_pack_run", "resolve_pack_values", "run_organization_pack",
    "run_project_pack", "zip_stem",
]
