"""
Module: services.report_placements

Where each report appears in the Reports picker for one organisation or project, and whether it appears at all.

Responsibilities:
- Name every report by a stable key (`report:<module>.<key>`, `layout:<id>`, `pack:<id>`).
- Store and resolve placement overrides: an organisation's, and a project's over its ancestors' and the organisation's,
  nearest first, per attribute (`folder`, `hidden`), the way an action type falls back to its nearest ancestor's.
- Apply the resolved placements to the report catalogue (a folder for each entry, hidden module reports left out).
- List what a scope's managers can place (`candidates`), hidden ones included, so a hidden report can be restored.

Design decisions:
- **Tidying, not access.** A placement changes what the picker lists, never what a person may run: a hidden report
  still answers on its route and the run still checks the caller's role and module state. The documentation says so.
- **Layouts and packs keep their own hide.** A shared layout or pack is hidden per project through the definition
  suppression mechanism (and restored there); a placement may only *move* it. Only module and platform reports are
  hidden by a placement, since nothing else hides them.
- **Default folders** are decided here, once: a module report files under its module's name, the platform's reports
  under "Platform", an unfiled layout under "Custom reports" and an unfiled pack under "Report packs". An author's
  `folder` replaces the default; a placement replaces both.
- Every change is audited with the key and the folder/hidden values (configuration, never record content).

Dependencies: `models.report_placement`, `services.report_folders`, `services.report_layout_scope`,
`services.report_pack_scope`, `services.report_framework` (the catalogue).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_placement import ReportPlacement
from app.models.user import User
from app.modules.registry import get_all_reports, get_module, report_enabled_for_organization
from app.services import report_pack_scope
from app.services.audit import log_event
from app.services.custom_report_run import MODULE_KEY as CUSTOM_MODULE_KEY
from app.services.custom_report_run import MODULE_NAME as CUSTOM_FOLDER
from app.services.custom_report_run import org_entries as custom_org_entries
from app.services.custom_report_run import project_entries as custom_project_entries
from app.services.project_hierarchy import get_project_chain_ids
from app.services.record_list_report import REPORT_KEY as RECORD_LIST_KEY
from app.services.record_list_report import REPORT_TITLE as RECORD_LIST_TITLE
from app.services.record_list_report import catalogue_entry as record_list_catalogue_entry
from app.services.report_folders import clean_folder
from app.services.report_framework import ReportCatalogueEntryOut, project_catalogue

Source = Literal["project", "ancestor", "organization"]
Kind = Literal["report", "sheet", "pack"]

#: The project's own requirements report: a frontend-only entry (it has its own request model), placeable all the same.
REQUIREMENTS_REPORT_KEY = "report:platform.requirements"
REQUIREMENTS_REPORT_TITLE = "Requirements report"
PLATFORM_FOLDER = "Platform"
PACKS_FOLDER = "Report packs"
_PLATFORM_MODULE = "platform"


def report_key(module_key: str, key: str) -> str:
    """The placement key of a module (or platform) report."""
    return f"report:{module_key}.{key}"


def layout_key(layout_id: uuid.UUID | str) -> str:
    """The placement key of a custom report layout."""
    return f"layout:{layout_id}"


def pack_key(pack_id: uuid.UUID | str) -> str:
    """The placement key of a report pack."""
    return f"pack:{pack_id}"


def entry_key(entry: ReportCatalogueEntryOut) -> str:
    """The placement key of a catalogue entry."""
    return layout_key(entry.key) if entry.module_key == CUSTOM_MODULE_KEY else report_key(entry.module_key, entry.key)


def is_hideable(key: str) -> bool:
    """Whether a placement may hide the report (module and platform reports only; see the module notes)."""
    return key.startswith("report:")


@dataclass(frozen=True)
class Resolved:
    """What a scope's placements say about one report.

    Attributes:
        folder: The overriding folder (`""` = top level), or `None` when nothing overrides the default.
        folder_from: Which tier set `folder`, or `None`.
        hidden: Whether the report is left out of the picker.
        hidden_from: Which tier set `hidden`, or `None`.
    """

    folder: str | None = None
    folder_from: Source | None = None
    hidden: bool = False
    hidden_from: Source | None = None


@dataclass(frozen=True)
class Candidate:
    """A report a scope's managers can place.

    Attributes:
        key: The placement key.
        title: Display title.
        description: One line about it.
        kind: `report`, `sheet` (a table layout) or `pack`.
        group: The module (or "Custom reports", "Report packs") it belongs to, for the organiser's grouping.
        default_folder: Where it files with no placement (the author's folder, else the default folder).
    """

    key: str
    title: str
    description: str
    kind: Kind
    group: str
    default_folder: str


def default_folder_for(entry: ReportCatalogueEntryOut) -> str:
    """Where a catalogue entry files with no placement."""
    if entry.module_key == CUSTOM_MODULE_KEY:
        return entry.folder or CUSTOM_FOLDER
    if entry.module_key == _PLATFORM_MODULE:
        return PLATFORM_FOLDER
    return entry.module_name


# --- resolution -----------------------------------------------------------------------------------------------


def _resolve(rows_by_tier: list[tuple[Source, list[ReportPlacement]]]) -> dict[str, Resolved]:
    """Layers tiers (nearest first) into one `Resolved` per key."""
    folder: dict[str, tuple[str, Source]] = {}
    hidden: dict[str, tuple[bool, Source]] = {}
    keys: set[str] = set()
    for source, rows in rows_by_tier:
        for row in rows:
            keys.add(row.report_key)
            if row.folder is not None and row.report_key not in folder:
                folder[row.report_key] = (row.folder, source)
            if row.hidden is not None and row.report_key not in hidden:
                hidden[row.report_key] = (row.hidden, source)
    return {
        key: Resolved(
            folder=folder[key][0] if key in folder else None, folder_from=folder[key][1] if key in folder else None,
            hidden=hidden[key][0] if key in hidden else False, hidden_from=hidden[key][1] if key in hidden else None,
        )
        for key in keys
    }


def resolve_for_organization(db: Session, organization_id: uuid.UUID) -> dict[str, Resolved]:
    """The organisation tier's placements by key."""
    rows = db.scalars(
        select(ReportPlacement).where(ReportPlacement.organization_id == organization_id, ReportPlacement.project_id.is_(None))
    ).all()
    return _resolve([("organization", list(rows))])


def resolve_for_project(db: Session, project: Project) -> dict[str, Resolved]:
    """A project's placements layered over its ancestors' and the organisation's, nearest first."""
    chain = get_project_chain_ids(db, project.id)  # the project, then its parent ... the root
    rows = db.scalars(
        select(ReportPlacement).where(
            ReportPlacement.organization_id == project.organization_id,
            (ReportPlacement.project_id.is_(None)) | (ReportPlacement.project_id.in_(chain)),
        )
    ).all()
    tiers: list[tuple[Source, list[ReportPlacement]]] = []
    for index, project_id in enumerate(chain):
        tiers.append(("project" if index == 0 else "ancestor", [r for r in rows if r.project_id == project_id]))
    tiers.append(("organization", [r for r in rows if r.project_id is None]))
    return _resolve(tiers)


def apply_to_catalogue(
    entries: list[ReportCatalogueEntryOut], resolved: dict[str, Resolved], *, drop_hidden: bool = True,
) -> list[ReportCatalogueEntryOut]:
    """Fills each entry's `placement_key` and effective `folder`, and (by default) leaves out hidden module reports.

    Args:
        entries: Catalogue entries (changed in place).
        resolved: The scope's resolved placements.
        drop_hidden: Leave out entries a placement hides.

    Returns:
        The entries to list, in their original order.
    """
    out: list[ReportCatalogueEntryOut] = []
    for entry in entries:
        key = entry_key(entry)
        placed = resolved.get(key)
        entry.placement_key = key
        entry.folder = placed.folder if placed is not None and placed.folder is not None else default_folder_for(entry)
        if drop_hidden and placed is not None and placed.hidden and is_hideable(key):
            continue
        out.append(entry)
    return out


# --- what a manager can place ----------------------------------------------------------------------------------


def _candidate(entry: ReportCatalogueEntryOut) -> Candidate:
    return Candidate(
        key=entry_key(entry), title=entry.title, description=entry.description, kind=entry.kind,
        group=CUSTOM_FOLDER if entry.module_key == CUSTOM_MODULE_KEY else (
            PLATFORM_FOLDER if entry.module_key == _PLATFORM_MODULE else entry.module_name
        ),
        default_folder=default_folder_for(entry),
    )


def project_candidates(db: Session, user: User, project: Project) -> list[Candidate]:
    """Every report the project's picker can list, whether or not a placement hides it."""
    entries = [
        *([e] if (e := record_list_catalogue_entry(db, user, project)) else []),
        *project_catalogue(db, project), *custom_project_entries(db, project),
    ]
    out = [
        Candidate(
            REQUIREMENTS_REPORT_KEY, REQUIREMENTS_REPORT_TITLE, "The project's requirements as a document.", "report",
            PLATFORM_FOLDER, PLATFORM_FOLDER,
        ),
        *(_candidate(e) for e in entries),
    ]
    out.extend(
        Candidate(pack_key(s.pack.id), s.pack.name, s.pack.description, "pack", PACKS_FOLDER, s.pack.folder or PACKS_FOLDER)
        for s in report_pack_scope.resolve_project_packs(db, project) if not s.hidden
    )
    return out


def organization_candidates(db: Session, user: User, organization_id: uuid.UUID) -> list[Candidate]:
    """Every report an organisation's placement can reach, whether or not a placement hides it.

    An organisation's placement applies to the organisation overview *and* to every project's picker (a project may
    still override it), so this is every module report whose module the organisation has enabled, the platform's
    reports, the organisation's layouts and its packs.
    """
    out = [
        Candidate(
            report_key(_PLATFORM_MODULE, RECORD_LIST_KEY), RECORD_LIST_TITLE, "A table of any kind of record in a project.",
            "report", PLATFORM_FOLDER, PLATFORM_FOLDER,
        ),
        Candidate(
            REQUIREMENTS_REPORT_KEY, REQUIREMENTS_REPORT_TITLE, "A project's requirements as a document.", "report",
            PLATFORM_FOLDER, PLATFORM_FOLDER,
        ),
    ]
    for module_key, definition in get_all_reports():
        module = get_module(module_key)
        if module is None or module.get_project_router is None and not definition.org_level:
            continue
        if not report_enabled_for_organization(db, organization_id, module_key, definition):
            continue
        name = module.name
        out.append(Candidate(report_key(module_key, definition.key), definition.title, definition.description, "report", name, name))
    out.extend(_candidate(e) for e in custom_org_entries(db, user, organization_id))
    out.extend(
        Candidate(pack_key(p.id), p.name, p.description, "pack", PACKS_FOLDER, p.folder or PACKS_FOLDER)
        for p in report_pack_scope.list_org_packs(db, organization_id)
    )
    return out


# --- changes --------------------------------------------------------------------------------------------------


class PlacementError(ValueError):
    """A placement that cannot be stored (unknown report, a hide of a layout or pack, a bad folder)."""


def set_placement(
    db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID | None, key: str, folder: str | None,
    hidden: bool | None, valid_keys: set[str] | None, actor_id: uuid.UUID | None,
) -> None:
    """Sets (or, with both values `None`, removes) one scope's placement of a report.

    Args:
        db: Active session (changed, flushed, not committed).
        organization_id: The owning organisation.
        project_id: The project, or `None` for the organisation tier.
        key: The report's placement key.
        folder: Folder path (`""` for the top level), or `None` for no override.
        hidden: Hide it, show what a parent hid, or `None` for no override.
        valid_keys: The keys this scope can place; anything else is refused (`None` skips the check: an import has
            already resolved the key).
        actor_id: Who changed it.

    Raises:
        PlacementError: An unknown key, a hide of something other than a module or platform report, or a bad folder.
    """
    if valid_keys is not None and key not in valid_keys:
        raise PlacementError("There is no such report here.")
    if hidden is not None and not is_hideable(key):
        raise PlacementError("A layout or pack is hidden from its own list, not here.")
    try:
        new_folder = None if folder is None else clean_folder(folder)
    except ValueError as exc:
        raise PlacementError(str(exc)) from exc
    row = db.scalars(
        select(ReportPlacement).where(
            ReportPlacement.organization_id == organization_id, ReportPlacement.report_key == key,
            ReportPlacement.project_id.is_(None) if project_id is None else ReportPlacement.project_id == project_id,
        )
    ).first()
    if new_folder is None and hidden is None:
        if row is not None:
            db.delete(row)
            action = "reset"
        else:
            return
    else:
        if row is None:
            row = ReportPlacement(organization_id=organization_id, project_id=project_id, report_key=key)
            db.add(row)
        row.folder, row.hidden, row.updated_by = new_folder, hidden, actor_id
        action = "set"
    db.flush()
    log_event(
        db, entity_type="report_placement", entity_id=row.id, action=action, actor_id=actor_id,
        organization_id=organization_id, project_id=project_id,
        detail={"report_key": key, "folder": new_folder, "hidden": hidden},
    )
