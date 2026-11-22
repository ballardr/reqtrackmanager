"""
Module: modules.architecture.symbol_library

The read model of the symbol library page: a filtered, sorted, paged list of the symbols a project or the organisation
offers, each with its folder, the kind of file it came from and where it is used, and the full list of where one symbol
is used.

Responsibilities:
- `library_page`: the rows for one place (the organisation's library, or a project's effective library) after the
  search, source, file type, used and folder filters, the sort and the page.
- `usage_for`: the owners that use one symbol, with counts.

Design decisions:
- **One effective list, filtered in memory.** The library is the vocabulary's own resolved list (`SymbolLibrary.
  resolve_effective`, which applies hiding and the nested fallback), so the page can never offer a symbol a picker would
  not. Filtering, sorting and paging happen on that list; its size is the number of symbols (hundreds), and only the
  page's rows are read for their owners. The usage figures are two grouped statements however many rows there are.
- **Used means referred to directly** by an element type or an element (`symbol_id`); an element drawn with its type's
  symbol counts for the type. In a project, usage is the project's own types and elements; the organisation's page counts
  every owner.
- **Owners are named only when the viewer may open them.** The organisation page shows a project's name to a person who
  can open that project and counts the others together as "Other projects". Element names are never listed (an element
  may be restricted); element type names are vocabulary and are.
- **A folder is per-owner content.** An organisation symbol is filed under an organisation folder (shown to every project
  that offers the symbol, by path), a project's own symbol under a project folder, and a symbol inherited from an ancestor
  project is not filed.
- **File type** is read from the stored name: an EPS or PDF is converted to SVG at upload and keeps its name with `.svg`
  appended (`logo.eps.svg`).

Dependencies: `service` (the library), `folders`, the models, and core `report_converter`, `project_access`, `files`.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.architecture import folders as folder_rules
from app.modules.architecture.models import ArchitectureElement, ArchitectureElementType, ArchitectureSymbol
from app.modules.architecture.records import ElementOwner
from app.modules.architecture.schemas import (
    SymbolLibraryFolderOut,
    SymbolLibraryPageOut,
    SymbolLibraryRow,
    SymbolUsageOut,
    SymbolUsageOwnerOut,
)
from app.modules.architecture.service import SYMBOLS
from app.services import report_converter
from app.services.project_access import accessible_project_ids

#: The most element type names listed for one owner in a usage answer.
MAX_TYPE_NAMES = 20
#: The most owners named in a row; more than this and the row shows a count instead.
MAX_NAMED_OWNERS = 2

#: The `(symbol, project, organisation)` columns of each table whose rows refer to a symbol.
_USERS = (
    (ArchitectureElementType.symbol_id, ArchitectureElementType.project_id, ArchitectureElementType.organization_id),
    (ArchitectureElement.symbol_id, ArchitectureElement.project_id, ArchitectureElement.organization_id),
)

#: `(symbol id, owning project id, owning organisation id)`: one owner of one symbol's users.
_OwnerKey = tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None]

SORT_KEYS = ("name", "source", "folder")
FILE_TYPES = ("svg", "eps", "pdf")


@dataclass(frozen=True)
class LibraryScope:
    """The place a library is read from: the organisation's own, or a project's effective one.

    Attributes:
        organization: The organisation.
        project: The project, or `None` for the organisation's own library.
    """

    organization: Organization
    project: Project | None = None


@dataclass(frozen=True)
class LibraryQuery:
    """The filters, sort and page of a library listing.

    Attributes:
        search: Text the name contains (ignoring case).
        source: `builtin` or `uploaded`, or `None` for both.
        file_type: `svg`, `eps` or `pdf` (an upload's original kind), or `None`.
        used: `used` or `unused`, or `None`.
        folder: A folder path, or `None`; with `folder_scope` `organization` it names an organisation folder (a project's
            view of the organisation's symbols), otherwise one of the page's own folders.
        folder_scope: `organization` or `own`.
        subfolders: Whether the folder filter includes the folders below it.
        sort: One of `SORT_KEYS`, or `None` for the library's own order.
        descending: Reverse the sort.
        offset: Rows to skip.
        limit: Rows in the page.
    """

    search: str | None = None
    source: str | None = None
    file_type: str | None = None
    used: str | None = None
    folder: str | None = None
    folder_scope: str | None = None
    subfolders: bool = True
    sort: str | None = None
    descending: bool = False
    offset: int = 0
    limit: int = 100


def _rows(db: Session, scope: LibraryScope) -> list[ArchitectureSymbol]:
    """The library's rows in the library's order: the organisation's, or a project's effective list."""
    if scope.project is None:
        return SYMBOLS.org_rows(db, scope.organization.id)
    return SYMBOLS.resolve_effective(db, scope.project.id, scope.organization.id).rows


def _tier(scope: LibraryScope, row: ArchitectureSymbol) -> str:
    """`organization`, `project` (this project's own) or `inherited` (an ancestor project's)."""
    if row.organization_id is not None:
        return "organization"
    return "project" if scope.project is not None and row.project_id == scope.project.id else "inherited"


def _file_types(db: Session, rows: list[ArchitectureSymbol]) -> dict[uuid.UUID, str]:
    """`{symbol id: builtin | svg | eps | pdf}`, reading the stored names in one statement."""
    names = {
        asset_id: name.lower()
        for asset_id, name in db.execute(
            select(FileAsset.id, FileAsset.filename).where(FileAsset.id.in_([r.file_asset_id for r in rows if r.file_asset_id]))
        ).tuples()
    } if any(r.file_asset_id for r in rows) else {}
    out: dict[uuid.UUID, str] = {}
    for row in rows:
        if row.builtin_key is not None:
            out[row.id] = "builtin"
            continue
        name = names.get(row.file_asset_id, "") if row.file_asset_id else ""
        out[row.id] = "eps" if name.endswith(".eps.svg") else "pdf" if name.endswith(".pdf.svg") else "svg"
    return out


def _usage_totals(db: Session, symbol_ids: list[uuid.UUID], project_id: uuid.UUID | None) -> Counter[uuid.UUID]:
    """How many element types and elements refer to each symbol (a project's page: its own only), in two statements."""
    totals: Counter[uuid.UUID] = Counter()
    if not symbol_ids:
        return totals
    for symbol_column, project_column, _organization_column in _USERS:
        query = select(symbol_column, func.count()).where(symbol_column.in_(symbol_ids))
        if project_id is not None:
            query = query.where(project_column == project_id)
        for symbol_id, count in db.execute(query.group_by(symbol_column)).tuples():
            if symbol_id is not None:
                totals[symbol_id] += count
    return totals


def usage_owners(
    db: Session, scope: LibraryScope, viewer: User, symbol_ids: list[uuid.UUID], *, with_type_names: bool,
) -> dict[uuid.UUID, list[SymbolUsageOwnerOut]]:
    """The owners that use each symbol, named for what `viewer` may open, in a few statements however many symbols.

    Args:
        db: The session.
        scope: The library's place; a project's page has itself as the only owner.
        viewer: The person asking (decides which projects are named).
        symbol_ids: The symbols to describe.
        with_type_names: Also list the element type names (up to `MAX_TYPE_NAMES` each), for the detail answer.

    Returns:
        `{symbol id: owners}`, owners sorted by name; a symbol nobody uses is absent.
    """
    if not symbol_ids:
        return {}
    project_id = scope.project.id if scope.project is not None else None
    counts: dict[_OwnerKey, list[int]] = defaultdict(lambda: [0, 0])
    type_names: dict[_OwnerKey, list[str]] = defaultdict(list)
    for position, (symbol_column, project_column, organization_column) in enumerate(_USERS):
        query = select(symbol_column, project_column, organization_column, func.count()).where(symbol_column.in_(symbol_ids))
        if project_id is not None:
            query = query.where(project_column == project_id)
        for symbol_id, owner_project, owner_org, count in db.execute(query.group_by(symbol_column, project_column, organization_column)).tuples():
            if symbol_id is not None:
                counts[(symbol_id, owner_project, owner_org)][position] = count
    if with_type_names:
        type_symbol, type_project, type_org = _USERS[0]
        names = select(type_symbol, type_project, type_org, ArchitectureElementType.name).where(
            type_symbol.in_(symbol_ids)
        ).order_by(func.lower(ArchitectureElementType.name))
        if project_id is not None:
            names = names.where(type_project == project_id)
        for symbol_id, owner_project, owner_org, name in db.execute(names).tuples():
            if symbol_id is not None:
                type_names[(symbol_id, owner_project, owner_org)].append(name)

    project_ids = {p for _s, p, _o in counts if p is not None}
    project_names = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).tuples().all()) if project_ids else {}
    openable = accessible_project_ids(db, viewer.id) if project_ids and scope.project is None else set(project_ids)

    result: dict[uuid.UUID, list[SymbolUsageOwnerOut]] = defaultdict(list)
    others: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0])
    for (symbol_id, owner_project, owner_org), (type_count, element_count) in counts.items():
        if owner_project is not None and owner_project not in openable:
            others[symbol_id][0] += type_count
            others[symbol_id][1] += element_count
            continue
        kind = "project" if owner_project is not None else "organization"
        name = project_names.get(owner_project, "") if owner_project is not None else scope.organization.name
        result[symbol_id].append(SymbolUsageOwnerOut(
            kind=kind, name=name, element_type_count=type_count, element_count=element_count,
            element_types=type_names.get((symbol_id, owner_project, owner_org), [])[:MAX_TYPE_NAMES],
        ))
    for symbol_id, (type_count, element_count) in others.items():
        result[symbol_id].append(SymbolUsageOwnerOut(
            kind="other_projects", name="Other projects", element_type_count=type_count, element_count=element_count, element_types=[],
        ))
    for owners in result.values():
        owners.sort(key=lambda o: (o.kind == "other_projects", o.name.casefold()))
    return dict(result)


def _folder_context(db: Session, scope: LibraryScope) -> tuple[dict[uuid.UUID, Any], dict[uuid.UUID, Any]]:
    """`(organisation folders by id, the project's folders by id)` of the `symbol` kind; the second is empty at the
    organisation level."""
    org_owner = ElementOwner.of_organization(scope.organization)
    org_folders = {f.id: f for f in folder_rules.list_folders(db, org_owner, "symbol")}
    own_folders = (
        {f.id: f for f in folder_rules.list_folders(db, ElementOwner.of_project(scope.project), "symbol")}
        if scope.project is not None else {}
    )
    return org_folders, own_folders


def _folder_ids(db: Session, scope: LibraryScope, query: LibraryQuery) -> set[uuid.UUID] | None:
    """The folder ids the folder filter keeps, or `None` for no folder filter."""
    if not query.folder:
        return None
    owner = (
        ElementOwner.of_project(scope.project)
        if scope.project is not None and query.folder_scope != "organization"
        else ElementOwner.of_organization(scope.organization)
    )
    return folder_rules.filter_ids(db, owner, "symbol", query.folder, include_subfolders=query.subfolders)


def library_page(db: Session, scope: LibraryScope, viewer: User, query: LibraryQuery) -> SymbolLibraryPageOut:
    """The library page for `scope` after the filters, the sort and the page.

    Args:
        db: The session.
        scope: The organisation's library, or a project's effective one.
        viewer: The person reading (decides which projects the "used by" names).
        query: The filters, sort and page.

    Returns:
        The page, with the unfiltered total and, for a project, the organisation folders its symbols are filed in.
    """
    rows = _rows(db, scope)
    project_id = scope.project.id if scope.project is not None else None
    file_types = _file_types(db, rows)
    totals = _usage_totals(db, [r.id for r in rows], project_id)
    org_folders, own_folders = _folder_context(db, scope)

    def folder_path(row: ArchitectureSymbol) -> str | None:
        if row.folder_id is None:
            return None
        by_id = org_folders if row.organization_id is not None else own_folders
        return folder_rules.path_of(by_id, row.folder_id) if row.folder_id in by_id else None

    keep = _folder_ids(db, scope, query)
    needle = (query.search or "").strip().casefold()
    shown = []
    for row in rows:
        if needle and needle not in row.name.casefold():
            continue
        if query.source == "builtin" and row.builtin_key is None or query.source == "uploaded" and row.builtin_key is not None:
            continue
        if query.file_type and file_types[row.id] != query.file_type:
            continue
        if query.used == "used" and totals[row.id] == 0 or query.used == "unused" and totals[row.id] > 0:
            continue
        if keep is not None and row.folder_id not in keep:
            continue
        shown.append(row)

    paths = {row.id: folder_path(row) for row in shown}
    if query.sort == "name":
        shown.sort(key=lambda r: r.name.casefold(), reverse=query.descending)
    elif query.sort == "source":
        shown.sort(key=lambda r: (r.builtin_key is None, r.name.casefold()), reverse=query.descending)
    elif query.sort == "folder":
        shown.sort(key=lambda r: ((paths[r.id] or "").casefold(), r.name.casefold()), reverse=query.descending)

    page = shown[query.offset: query.offset + query.limit]
    owners = usage_owners(db, scope, viewer, [r.id for r in page if totals[r.id] > 0], with_type_names=False)
    items = []
    for row in page:
        tier = _tier(scope, row)
        named = owners.get(row.id, [])
        # A project's page has itself as its only owner, so it shows a count; the organisation's names its owners.
        used_by = [o.name for o in named] if scope.project is None and len(named) <= MAX_NAMED_OWNERS else []
        items.append(SymbolLibraryRow(
            id=row.id, project_id=row.project_id, organization_id=row.organization_id, name=row.name, builtin_key=row.builtin_key,
            is_builtin=row.is_builtin, sort_order=row.sort_order, tier=tier, folder_id=row.folder_id if paths.get(row.id) else None,
            folder_path=paths[row.id], file_type=file_types[row.id],
            can_file=row.builtin_key is None and tier == ("organization" if scope.project is None else "project"),
            usage_count=totals[row.id], used_by=used_by, usage_owner_count=len(named) if scope.project is None else int(totals[row.id] > 0),
        ))

    org_counts: Counter[str] = Counter()
    if scope.project is not None:
        for row in rows:
            if row.organization_id is not None and row.folder_id in org_folders:
                org_counts[folder_rules.path_of(org_folders, row.folder_id)] += 1
    return SymbolLibraryPageOut(
        items=items, total=len(shown), library_total=len(rows), offset=query.offset, limit=query.limit,
        converter_available=report_converter.is_configured(),
        organization_folders=[SymbolLibraryFolderOut(path=p, symbol_count=n) for p, n in sorted(org_counts.items(), key=lambda kv: kv[0].casefold())],
    )


def usage_for(db: Session, scope: LibraryScope, viewer: User, symbol_id: uuid.UUID) -> SymbolUsageOut | None:
    """Where one symbol is used, or `None` when the library does not offer the symbol (indistinguishable from a missing one)."""
    if symbol_id not in {r.id for r in _rows(db, scope)}:
        return None
    return SymbolUsageOut(owners=usage_owners(db, scope, viewer, [symbol_id], with_type_names=True).get(symbol_id, []))
