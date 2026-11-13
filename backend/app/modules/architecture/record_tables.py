"""
Module: modules.architecture.record_tables

The `RecordTableProvider`s of the module's three record types, the element, the connection and the diagram: each
list as a table, so it exports to CSV, PDF and Word and (element and connection) imports from the same CSV (a row
with a code updates that record, a blank code creates one). A diagram exports only (`NOT_IMPORTABLE` says why).

Responsibilities:
- Declare the columns (name, type, symbol, parent, owner, status, ports; or type, ends, ports, protocol) and
  filters, and share the create and edit logic with the endpoints (`records.create_element` and so on), so
  validation, the version counter and the audit event are the ones the screen applies.

Design decisions:
- The type is written by its name (the project's effective list, or the organisation's rows at the organisation
  tier); the parent by the code of an element of the same owner, which must already exist. A connection end
  that another owner shares is written qualified by the owner's code (`PLAT-ELM-004`, or the organisation's code),
  because a bare code would name one of the project's own elements; the parser resolves it through
  `visibility`, so a file cannot reach an element the person cannot read.
- The symbol is written by its name (the owner's effective library) and left blank for the type's own; a name is shown
  only for a symbol the reader may read (`symbols.visible_symbol_ids`), so an element another owner shares never
  discloses a symbol the person cannot see.
- `status` is importable because the module has no approval gate (a record may make any move
  `transitions.STATUS_MOVES` lists, and a row asking for another is a row error); a new record can be created
  `Draft`, `Proposed` or `Active`, not `Retired` or `Rejected`.
- `ports` is one list cell, `name:direction` per port (`Main:both;Debug:in`), the way the export writes it. An
  import *adds* the ports a cell names that the element lacks and never removes or edits one, so a round trip
  changes nothing and removing a port stays a deliberate act on the element.
- An import update quotes the record's current `version`: a file is applied to the record as it is now.

The organisation tier (`OrganizationRecordTable`) lists the organisation-owned elements the person may read and
imports through the organisation endpoints' own path (`records.ElementOwner.of_organization`).

Dependencies: `records` (rules), `record_routes` (filters), `visibility`, `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.architecture import diagrams, folders, records
from app.modules.architecture._shared import (
    CONNECTION_MANAGE_PERMISSION,
    DIAGRAM_MANAGE_PERMISSION,
    ELEMENT_MANAGE_PERMISSION,
    require_architect,
)
from app.modules.architecture.connection_tree import closure_of
from app.modules.architecture.diagram_routes import filter_diagrams
from app.modules.architecture.enums import PortDirection, RecordStatus
from app.modules.architecture.labels import PORT_DIRECTION_LABEL, RECORD_STATUS_LABEL
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitecturePort,
    ArchitectureSymbol,
)
from app.modules.architecture.record_routes import filter_connections, filter_elements
from app.modules.architecture.records import ElementOwner
from app.modules.architecture.schemas import (
    ConnectionCreate,
    ConnectionUpdate,
    ElementCreate,
    ElementUpdate,
    PortCreate,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    CONNECTION_TYPES,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
    ELEMENT_SUBCOMPONENT_KEY,
    ELEMENT_TYPES,
    SYMBOLS,
)
from app.modules.architecture.symbols import visible_symbol_ids
from app.modules.architecture.visibility import Viewer, is_architecture_org_admin, visible_element_ids
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.services import tags as tag_service
from app.services.lookups import project_or_404
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells, find_many_by_code
from app.services.record_tables_core import (
    cached_lookup,
    count_rows,
    enum_filter,
    enum_parser,
    list_cell,
    list_parser,
    person_parser,
    text_parser,
)

ELEMENT_FILTERS = frozenset({"include_archived", "status", "type", "open_only", "search", "roots_only", "folder", "subfolders"})
CONNECTION_FILTERS = frozenset({"include_archived", "status", "type", "open_only", "search", "folder", "subfolders"})
DIAGRAM_FILTERS = frozenset({"include_archived", "status", "open_only", "search", "folder", "subfolders"})

_STATUS_TONES = {"Draft": "info", "Active": "accent", "Retired": "muted"}
_DIRECTION_BY_LABEL = {label.casefold(): value for value, label in PORT_DIRECTION_LABEL.items()}


def _payload(model: type[BaseModel], values: Mapping[str, Any]) -> Any:
    """Builds the endpoint's request payload from parsed cells.

    Raises:
        RecordCellError: The model refuses a value; the message names the field.
    """
    try:
        return model(**values)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise RecordCellError(f"{'.'.join(str(p) for p in first['loc']) or 'value'}: {first['msg']}") from None


def _rule(call: Callable[[], Any]) -> Any:
    """Runs a rule from `records`, turning a refusal into the row error the engine reports."""
    try:
        return call()
    except records.RuleError as exc:
        raise RecordCellError(str(exc)) from None


def _allowed(db: Session, user: User, project_id: uuid.UUID, permission: str) -> bool:
    """Whether `user` passes the Architect gate (the endpoints' own check) in the project."""
    try:
        require_architect(db, user, project_or_404(db, project_id), permission)
    except HTTPException:
        return False
    return True


def _effective_rows(vocabulary: Any, db: Session, scope: Project | Organization) -> list:
    """The types an owner may use: a project's effective list, or an organisation's own rows."""
    if isinstance(scope, Project):
        return vocabulary.resolve_effective(db, scope.id, scope.organization_id).rows
    return vocabulary.org_rows(db, scope.id)


def _owner_of(ctx: RecordImportContext) -> ElementOwner:
    """The owner an import writes as: the project, or the organisation at the organisation tier."""
    return ElementOwner.of_project(ctx.project) if ctx.project is not None else ElementOwner.of_organization(ctx.organization)


def _type_names(vocabulary: Any, db: Session, scope: Project | Organization) -> dict[str, uuid.UUID]:
    """`{lower-case name: id}` of the owner's effective types."""
    return {row.name.casefold(): row.id for row in _effective_rows(vocabulary, db, scope)}


def _type_parser(vocabulary: Any, kind: str) -> Callable[[RecordImportContext, str], uuid.UUID]:
    """A parser for a type name of the importing project (required: an empty cell is refused)."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID:
        if not text:
            raise RecordCellError(f"A {vocabulary.label.lower()} is required.")
        scope = ctx.project if ctx.project is not None else ctx.organization
        found = cached_lookup(ctx, f"{kind}:names", lambda: _type_names(vocabulary, ctx.db, scope)).get(text.casefold())
        if found is None:
            raise RecordCellError(f"Unknown {vocabulary.label.lower()} '{text}'.")
        return found

    return parse


def _symbol_parser(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
    """A parser for a symbol name of the importing owner's effective library; an empty cell means the type's own."""
    if not text:
        return None
    scope = ctx.project if ctx.project is not None else ctx.organization
    found = cached_lookup(ctx, "symbols:names", lambda: _type_names(SYMBOLS, ctx.db, scope)).get(text.casefold())
    if found is None:
        raise RecordCellError(f"Unknown symbol '{text}'.")
    return found


def _element_by_code_parser(field_name: str, *, blank_clears: bool) -> Callable[[RecordImportContext, str], uuid.UUID | None]:
    """A parser for the code of an element of the importing owner (`ELM-004`); an empty cell means none."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            if blank_clears:
                return None
            raise RecordCellError(f"{field_name} is required.")
        codes = cached_lookup(ctx, "elements:codes", lambda: {
            code.upper(): element_id for element_id, code in ctx.db.execute(
                select(ArchitectureElement.id, ArchitectureElement.unique_code).where(_owner_of(ctx).element_filter)
            )
        })
        found = codes.get(text.upper())
        if found is None:
            raise RecordCellError(f"{field_name} '{text}' is not an element of this {'project' if ctx.project else 'organisation'}.")
        return found

    return parse


def _end_parser(field_name: str) -> Callable[[RecordImportContext, str], uuid.UUID | None]:
    """A parser for a connection end: a bare code names the project's own element, a code qualified by a project's
    or the organisation's code (`PLAT-ELM-004`) names an element that owner shares, which the person must be able to
    read. The cell is required."""
    own = _element_by_code_parser(field_name, blank_clears=False)

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        owner_code, separator, rest = text.upper().rpartition(f"-{ELEMENT_CODE_PREFIX}-")
        if not text or not separator or not owner_code:
            return own(ctx, text)
        code = f"{ELEMENT_CODE_PREFIX}-{rest}"
        organization_id = ctx.organization_id
        found = ctx.db.scalar(
            select(ArchitectureElement.id).join(Project, Project.id == ArchitectureElement.project_id).where(
                func.upper(Project.code) == owner_code, Project.organization_id == organization_id,
                ArchitectureElement.unique_code == code,
            )
        ) or ctx.db.scalar(
            select(ArchitectureElement.id).join(Organization, Organization.id == ArchitectureElement.organization_id).where(
                func.upper(Organization.code) == owner_code, Organization.id == organization_id,
                ArchitectureElement.unique_code == code,
            )
        )
        if found is None or found not in visible_element_ids(ctx.db, Viewer.of_user(ctx.user, ctx.project), [found]):
            raise RecordCellError(f"{field_name} '{text}' is not an element this project can use.")
        return found

    return parse


def _folder_parser(kind: str) -> Callable[[RecordImportContext, str], uuid.UUID | None]:
    """A parser for a folder path of the importing owner (`Software/Modules`); an empty cell means the top level."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            return None
        found = cached_lookup(ctx, f"{kind}:folders", lambda: folders.path_index(ctx.db, _owner_of(ctx), kind)).get(text.strip().casefold())
        if found is None:
            raise RecordCellError(f"Unknown folder '{text}'.")
        return found

    return parse


def _folder_column(kind: str) -> RecordColumn:
    return RecordColumn("folder", "Folder", lambda t, r: t.folders.get(r.folder_id, "") if r.folder_id else "", _folder_parser(kind))


def _folder_filtered(
    db: Session, owner: ElementOwner, kind: str, rows: list[Any], filters: RecordFilters,
) -> list[Any]:
    """The rows in the folder the list's `folder` filter names (and, with `subfolders`, below it)."""
    wanted = folders.filter_ids(db, owner, kind, filters.one("folder"), include_subfolders=bool(filters.flag("subfolders")))
    return rows if wanted is None else [r for r in rows if r.folder_id in wanted]


def _status_column() -> RecordColumn:
    return RecordColumn(
        "status", "Status", lambda t, r: RECORD_STATUS_LABEL[r.status], enum_parser(RecordStatus, "Status"),
        kind="enum", editable=True, choices=tuple(RECORD_STATUS_LABEL.values()), tones=_STATUS_TONES,
    )


class _Prepared:
    """Lookups handed to every column's `get`: type names, people, tags, parent and end codes, port text."""

    def __init__(self, db: Session, scope: Project | Organization, records_: Sequence[Any], artefact_type: str) -> None:
        ids = [r.id for r in records_]
        self.tags = tag_service.tag_names_for_records(db, artefact_type, ids) if ids else {}
        self.element_types = {row.id: row.name for row in _effective_rows(ELEMENT_TYPES, db, scope)}
        self.connection_types = {row.id: row.name for row in _effective_rows(CONNECTION_TYPES, db, scope)}
        self.folders = folders.paths_for(db, (r.folder_id for r in records_))
        self.codes: dict[uuid.UUID, str] = {}
        self.symbols: dict[uuid.UUID, str] = {}
        self.ports_text: dict[uuid.UUID, str] = {}
        self.port_names: dict[uuid.UUID, str] = {}
        self.people = PrincipalCells.load(db, [])
        if artefact_type == ELEMENT_ARTEFACT_TYPE:
            self.people = PrincipalCells.load(db, [principal_ref(r.owner_type, r.owner_id) for r in records_])
            wanted = {r.parent_id for r in records_ if r.parent_id}
            symbol_ids = {r.symbol_id for r in records_ if r.symbol_id}
            if symbol_ids:
                viewer = Viewer.of_project(scope.id, scope.organization_id) if isinstance(scope, Project) else Viewer(scope.id)
                readable = visible_symbol_ids(db, viewer, symbol_ids)
                self.symbols = {
                    row.id: row.name for row in db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.id.in_(readable)))
                }
            for element_id, port_list in records.ports_for(db, ids).items():
                self.ports_text[element_id] = list_cell([f"{p.name}:{PORT_DIRECTION_LABEL.get(p.direction, p.direction)}" for p in port_list])
        else:
            wanted = {r.source_element_id for r in records_} | {r.target_element_id for r in records_}
            port_ids = {p for r in records_ for p in (r.source_port_id, r.target_port_id) if p}
            if port_ids:
                self.port_names = {
                    row.id: row.name for row in db.scalars(select(ArchitecturePort).where(ArchitecturePort.id.in_(port_ids)))
                }
        if wanted:
            # An end another owner shares is written qualified by that owner's code (a bare code would name one of
            # this project's own elements on re-import).
            rows = db.execute(
                select(
                    ArchitectureElement.id, ArchitectureElement.unique_code, ArchitectureElement.project_id,
                    Project.code, Organization.code,
                ).outerjoin(Project, Project.id == ArchitectureElement.project_id)
                .outerjoin(Organization, Organization.id == ArchitectureElement.organization_id)
                .where(ArchitectureElement.id.in_(wanted))
            ).all()
            for element_id, code, element_project_id, project_code, org_code in rows:
                own = element_project_id == scope.id if isinstance(scope, Project) else element_project_id is None
                self.codes[element_id] = code if own else f"{project_code or org_code}-{code}"


def _tags_column() -> RecordColumn:
    return RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list")


# --- Element ---------------------------------------------------------------


def _prepare_elements(db: Session, scope: Project | Organization, records_: list[ArchitectureElement]) -> _Prepared:
    return _Prepared(db, scope, records_, ELEMENT_ARTEFACT_TYPE)


def _filtered_elements(
    db: Session, scope: Project | Organization, rows: list[ArchitectureElement], filters: RecordFilters,
) -> list[ArchitectureElement]:
    """The rows the list's filters keep (shared by the project and organisation tiers)."""
    type_name = filters.one("type")
    type_id = None
    if type_name is not None:
        type_id = _type_names(ELEMENT_TYPES, db, scope).get(type_name.casefold())
        if type_id is None:
            return []
    status = enum_filter(filters, "status", RecordStatus)
    owner = ElementOwner.of_project(scope) if isinstance(scope, Project) else ElementOwner.of_organization(scope)
    return _folder_filtered(db, owner, "element", filter_elements(
        rows, status_=status.value if status else None, element_type_id=type_id,
        roots_only=bool(filters.flag("roots_only")), open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    ), filters)


def _list_elements(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ArchitectureElement]:
    project = project_or_404(db, project_id)
    return _filtered_elements(
        db, project, records.list_elements(db, project_id, include_archived=bool(filters.flag("include_archived"))), filters,
    )


def _list_org_elements(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[ArchitectureElement]:
    return _filtered_elements(
        db, organization,
        records.list_org_elements_for(db, user, organization.id, include_archived=bool(filters.flag("include_archived"))),
        filters,
    )


def _element_columns(db: Session, project: Project | Organization) -> list[RecordColumn]:
    return [
        RecordColumn("name", "Name", lambda t, r: r.name, text_parser, editable=False, required=True),
        RecordColumn("description", "Description", lambda t, r: r.description, text_parser),
        RecordColumn("display_note", "Display note", lambda t, r: r.display_note, text_parser),
        RecordColumn(
            "type", "Type", lambda t, r: t.element_types.get(r.element_type_id, ""), _type_parser(ELEMENT_TYPES, "element"),
            kind="enum", required=True, choices=tuple(_type_names_ordered(ELEMENT_TYPES, db, project)),
        ),
        RecordColumn(
            "symbol", "Symbol", lambda t, r: t.symbols.get(r.symbol_id, "") if r.symbol_id else "", _symbol_parser,
            kind="enum", choices=tuple(_type_names_ordered(SYMBOLS, db, project)),
        ),
        RecordColumn(
            "parent", "Parent element", lambda t, r: t.codes.get(r.parent_id, "") if r.parent_id else "",
            _element_by_code_parser("Parent element", blank_clears=True),
        ),
        _folder_column("element"),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(r.owner_type, r.owner_id), person_parser("owner"), kind="principal",
        ),
        _status_column(),
        RecordColumn("ports", "Ports", lambda t, r: t.ports_text.get(r.id, ""), list_parser, kind="list"),
        _tags_column(),
    ]


def _type_names_ordered(vocabulary: Any, db: Session, scope: Project | Organization) -> list[str]:
    return [row.name for row in _effective_rows(vocabulary, db, scope)]


def _ports_from_cell(entries: list[str]) -> list[PortCreate]:
    """The ports a cell names: `name` or `name:direction` per entry."""
    ports = []
    for entry in entries:
        name, _, direction = entry.partition(":")
        key = direction.strip().casefold()
        if key and key not in _DIRECTION_BY_LABEL and key not in {d.value for d in PortDirection}:
            raise RecordCellError(f"Port direction '{direction.strip()}' is not one of: In, Out, Both.")
        ports.append(PortCreate(name=name.strip(), direction=PortDirection(_DIRECTION_BY_LABEL.get(key, key or "both"))))
    return ports


def _create_element(ctx: RecordImportContext, values: Mapping[str, Any]) -> ArchitectureElement:
    status = values.get("status")
    if status in (RecordStatus.RETIRED, RecordStatus.REJECTED):
        raise RecordCellError(f"A new element cannot be created {RECORD_STATUS_LABEL[status.value]}.")
    payload = _payload(ElementCreate, {
        "name": values.get("name", ""), "description": values.get("description", ""),
        "display_note": values.get("display_note", ""), "element_type_id": values.get("type"),
        "symbol_id": values.get("symbol"), "parent_id": values.get("parent"),
        "folder_id": values.get("folder"), "owner": values.get("owner"), "activate": status is RecordStatus.ACTIVE,
        "ports": _ports_from_cell(values.get("ports", [])),
    })
    element = _rule(lambda: records.create_element(ctx.db, _owner_of(ctx), ctx.user, payload))
    if status is RecordStatus.PROPOSED:
        _rule(lambda: records.change_element_status(ctx.db, _owner_of(ctx), ctx.user, element.id, element.version, status))
    return element


def _update_element(ctx: RecordImportContext, element: ArchitectureElement, values: Mapping[str, Any]) -> None:
    fields: dict[str, Any] = {}
    for key, field in (
        ("name", "name"), ("description", "description"), ("display_note", "display_note"),
        ("type", "element_type_id"), ("symbol", "symbol_id"), ("parent", "parent_id"), ("folder", "folder_id"), ("owner", "owner"),
    ):
        if key in values:
            fields[field] = values[key]
    if fields:
        payload = _payload(ElementUpdate, {"version": element.version, **fields})
        _rule(lambda: records.update_element(ctx.db, _owner_of(ctx), ctx.user, element.id, payload))
    if "ports" in values:
        existing = {p.name.casefold() for p in records.ports_for(ctx.db, [element.id]).get(element.id, [])}
        for port in _ports_from_cell(values["ports"]):
            if port.name.casefold() not in existing:
                _rule(partial(records.add_port, ctx.db, _owner_of(ctx), ctx.user, element.id, port))
                existing.add(port.name.casefold())
    if values.get("status") is not None and values["status"].value != element.status:
        ctx.db.refresh(element)
        _rule(lambda: records.change_element_status(
            ctx.db, _owner_of(ctx), ctx.user, element.id, element.version, values["status"],
        ))


def _find_element(db: Session, project: Project, code: str) -> ArchitectureElement | None:
    return db.scalar(select(ArchitectureElement).where(
        ArchitectureElement.project_id == project.id, ArchitectureElement.unique_code == code.upper(),
    ))


def _find_org_element(db: Session, organization: Organization, code: str) -> ArchitectureElement | None:
    return db.scalar(select(ArchitectureElement).where(
        ArchitectureElement.organization_id == organization.id, ArchitectureElement.unique_code == code.upper(),
    ))


ELEMENT_TABLE = RecordTableProvider(
    label="Elements",
    columns=_element_columns,
    list_records=_list_elements,
    find=_find_element,
    find_many=find_many_by_code(ArchitectureElement, "project_id"),
    prepare=_prepare_elements,
    create=_create_element,
    update=_update_element,
    filter_params=ELEMENT_FILTERS,
    gate=(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY),
    can_create=lambda db, user, project_id: _allowed(db, user, project_id, ELEMENT_MANAGE_PERMISSION),
    can_update=lambda db, user, project_id: _allowed(db, user, project_id, ELEMENT_MANAGE_PERMISSION),
    count=lambda db, user, project_id: count_rows(db, ArchitectureElement, project_id, live_only=True),
    organization=OrganizationRecordTable(
        subcomponent=ELEMENT_SUBCOMPONENT_KEY,
        columns=_element_columns,
        list_records=_list_org_elements,
        find=_find_org_element,
        find_many=find_many_by_code(ArchitectureElement, "organization_id"),
        prepare=_prepare_elements,
        create=_create_element,
        update=_update_element,
        filter_params=ELEMENT_FILTERS,
        can_create=lambda db, user, organization_id: is_architecture_org_admin(db, user, organization_id),
        can_update=lambda db, user, organization_id: is_architecture_org_admin(db, user, organization_id),
    ),
)


# --- Connection ------------------------------------------------------------


def _prepare_connections(db: Session, project: Project, records_: list[ArchitectureConnection]) -> _Prepared:
    return _Prepared(db, project, records_, CONNECTION_ARTEFACT_TYPE)


def _list_connections(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ArchitectureConnection]:
    project = project_or_404(db, project_id)
    type_name = filters.one("type")
    type_id = None
    if type_name is not None:
        type_id = _type_names(CONNECTION_TYPES, db, project).get(type_name.casefold())
        if type_id is None:
            return []
    status = enum_filter(filters, "status", RecordStatus)
    return _folder_filtered(db, ElementOwner.of_project(project), "connection", filter_connections(
        records.list_connections(db, project_id, include_archived=bool(filters.flag("include_archived"))),
        status_=status.value if status else None,
        connection_type_ids=closure_of(db, [type_id]) if type_id is not None else None,
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    ), filters)


def _port_by_name(ctx: RecordImportContext, element_id: uuid.UUID | None, name: str, side: str) -> uuid.UUID | None:
    """The id of the named port of an element; an empty name means no port."""
    if not name:
        return None
    if element_id is None:
        raise RecordCellError(f"Name the {side} element before its port.")
    for port in records.ports_for(ctx.db, [element_id]).get(element_id, []):
        if port.name.casefold() == name.casefold():
            return port.id
    raise RecordCellError(f"The {side} element has no port '{name}'.")


def _connection_columns(db: Session, project: Project) -> list[RecordColumn]:
    def end(side: str) -> RecordColumn:
        def get(t: _Prepared, r: ArchitectureConnection) -> str:
            return t.codes.get(getattr(r, f"{side}_element_id"), "")

        return RecordColumn(
            side, f"{side.capitalize()} element", get,
            _end_parser(f"{side.capitalize()} element"), required=True,
        )

    def port(side: str) -> RecordColumn:
        def get(t: _Prepared, r: ArchitectureConnection) -> str:
            port_id = getattr(r, f"{side}_port_id")
            return t.port_names.get(port_id, "") if port_id else ""

        return RecordColumn(f"{side}_port", f"{side.capitalize()} port", get, text_parser)

    return [
        RecordColumn("name", "Name", lambda t, r: r.name, text_parser),
        RecordColumn(
            "type", "Type", lambda t, r: t.connection_types.get(r.connection_type_id, ""), _type_parser(CONNECTION_TYPES, "connection"),
            kind="enum", required=True, choices=tuple(_type_names_ordered(CONNECTION_TYPES, db, project)),
        ),
        end("source"), port("source"), end("target"), port("target"),
        RecordColumn("protocol", "Protocol", lambda t, r: r.protocol, text_parser),
        RecordColumn("description", "Description", lambda t, r: r.description, text_parser),
        _folder_column("connection"),
        _status_column(),
        _tags_column(),
    ]


def _create_connection(ctx: RecordImportContext, values: Mapping[str, Any]) -> ArchitectureConnection:
    status = values.get("status")
    if status in (RecordStatus.RETIRED, RecordStatus.REJECTED):
        raise RecordCellError(f"A new connection cannot be created {RECORD_STATUS_LABEL[status.value]}.")
    source, target = values.get("source"), values.get("target")
    payload = _payload(ConnectionCreate, {
        "name": values.get("name", ""), "connection_type_id": values.get("type"), "source_element_id": source,
        "source_port_id": _port_by_name(ctx, source, values.get("source_port", ""), "source"),
        "target_element_id": target, "target_port_id": _port_by_name(ctx, target, values.get("target_port", ""), "target"),
        "protocol": values.get("protocol", ""), "description": values.get("description", ""),
        "folder_id": values.get("folder"), "activate": status is RecordStatus.ACTIVE,
    })
    connection = _rule(lambda: records.create_connection(ctx.db, ctx.project, ctx.user, payload))
    if status is RecordStatus.PROPOSED:
        _rule(lambda: records.change_connection_status(ctx.db, ctx.project, ctx.user, connection.id, connection.version, status))
    return connection


def _update_connection(ctx: RecordImportContext, connection: ArchitectureConnection, values: Mapping[str, Any]) -> None:
    fields: dict[str, Any] = {}
    for key, field in (
        ("name", "name"), ("type", "connection_type_id"), ("protocol", "protocol"), ("description", "description"),
        ("folder", "folder_id"),
    ):
        if key in values:
            fields[field] = values[key]
    source = values.get("source", connection.source_element_id)
    target = values.get("target", connection.target_element_id)
    for side, element_id in (("source", source), ("target", target)):
        if side in values:
            fields[f"{side}_element_id"] = element_id
        if f"{side}_port" in values or side in values:
            fields[f"{side}_port_id"] = _port_by_name(ctx, element_id, values.get(f"{side}_port", ""), side)
    if fields:
        payload = _payload(ConnectionUpdate, {"version": connection.version, **fields})
        _rule(lambda: records.update_connection(ctx.db, ctx.project, ctx.user, connection.id, payload))
    if values.get("status") is not None and values["status"].value != connection.status:
        ctx.db.refresh(connection)
        _rule(lambda: records.change_connection_status(
            ctx.db, ctx.project, ctx.user, connection.id, connection.version, values["status"],
        ))


def _find_connection(db: Session, project: Project, code: str) -> ArchitectureConnection | None:
    return db.scalar(select(ArchitectureConnection).where(
        ArchitectureConnection.project_id == project.id, ArchitectureConnection.unique_code == code.upper(),
    ))


CONNECTION_TABLE = RecordTableProvider(
    label="Connections",
    columns=_connection_columns,
    list_records=_list_connections,
    find=_find_connection,
    find_many=find_many_by_code(ArchitectureConnection, "project_id"),
    prepare=_prepare_connections,
    create=_create_connection,
    update=_update_connection,
    filter_params=CONNECTION_FILTERS,
    gate=(ARCHITECTURE_MODULE_KEY, CONNECTION_SUBCOMPONENT_KEY),
    can_create=lambda db, user, project_id: _allowed(db, user, project_id, CONNECTION_MANAGE_PERMISSION),
    can_update=lambda db, user, project_id: _allowed(db, user, project_id, CONNECTION_MANAGE_PERMISSION),
    count=lambda db, user, project_id: count_rows(db, ArchitectureConnection, project_id, live_only=True),
)

# --- Diagram ---------------------------------------------------------------


class _DiagramPrepared:
    """Lookups handed to every diagram column's `get`: tags, scope element codes and placement counts."""

    def __init__(self, db: Session, project: Project, records_: Sequence[ArchitectureDiagram]) -> None:
        ids = [r.id for r in records_]
        self.tags = tag_service.tag_names_for_records(db, DIAGRAM_ARTEFACT_TYPE, ids) if ids else {}
        self.folders = folders.paths_for(db, (r.folder_id for r in records_))
        scope_ids = {r.scope_element_id for r in records_ if r.scope_element_id}
        self.scopes: dict[uuid.UUID, str] = {}
        if scope_ids:
            readable = visible_element_ids(db, Viewer.of_project(project.id, project.organization_id), scope_ids)
            self.scopes = {
                element_id: code for element_id, code in db.execute(
                    select(ArchitectureElement.id, ArchitectureElement.unique_code).where(ArchitectureElement.id.in_(readable))
                )
            }
        self.counts = {
            d.id: d for d in diagrams.diagram_outs(db, list(records_), Viewer.of_project(project.id, project.organization_id))
        }


def _prepare_diagrams(db: Session, project: Project, records_: list[ArchitectureDiagram]) -> _DiagramPrepared:
    return _DiagramPrepared(db, project, records_)


def _list_diagrams(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ArchitectureDiagram]:
    status = enum_filter(filters, "status", RecordStatus)
    project = project_or_404(db, project_id)
    return _folder_filtered(db, ElementOwner.of_project(project), "diagram", filter_diagrams(
        diagrams.list_diagrams(db, project_id, include_archived=bool(filters.flag("include_archived"))),
        status_=status.value if status else None, open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    ), filters)


def _diagram_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        RecordColumn("name", "Name", lambda t, r: r.name, text_parser, editable=False),
        RecordColumn("purpose", "Purpose", lambda t, r: r.purpose, text_parser),
        RecordColumn("scope", "Scope element", lambda t, r: t.scopes.get(r.scope_element_id, "") if r.scope_element_id else "", text_parser),
        RecordColumn(
            "connection_detail", "Connection detail", lambda t, r: "Yes" if r.connection_detail else "No", text_parser,
        ),
        RecordColumn("placements", "Elements", lambda t, r: str(t.counts[r.id].placement_count), text_parser),
        _folder_column("diagram"),
        # A diagram has no import or update through its table, so its status is not edited in the bulk grid either.
        replace(_status_column(), editable=False),
        _tags_column(),
    ]


def _find_diagram(db: Session, project: Project, code: str) -> ArchitectureDiagram | None:
    return db.scalar(select(ArchitectureDiagram).where(
        ArchitectureDiagram.project_id == project.id, ArchitectureDiagram.unique_code == code.upper(),
    ))


#: Why a diagram has no import: its layout is authored visually, so a row of cells cannot describe it.
NOT_IMPORTABLE: dict[str, str] = {
    DIAGRAM_ARTEFACT_TYPE: (
        "A diagram's content is a layout of boxes, toggles and notes drawn in the editor, which a row of cells cannot "
        "describe; its list exports, and the project bundle and the JSON interchange carry the diagram itself."
    ),
}

DIAGRAM_TABLE = RecordTableProvider(
    label="Diagrams",
    columns=_diagram_columns,
    list_records=_list_diagrams,
    find=_find_diagram,
    find_many=find_many_by_code(ArchitectureDiagram, "project_id"),
    prepare=_prepare_diagrams,
    filter_params=DIAGRAM_FILTERS,
    gate=(ARCHITECTURE_MODULE_KEY, DIAGRAM_SUBCOMPONENT_KEY),
    # The table cannot import, but the Links panel's "Create new" asks it who may create a diagram.
    can_create=lambda db, user, project_id: _allowed(db, user, project_id, DIAGRAM_MANAGE_PERMISSION),
    count=lambda db, user, project_id: count_rows(db, ArchitectureDiagram, project_id, live_only=True),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {
    ELEMENT_ARTEFACT_TYPE: ELEMENT_TABLE,
    CONNECTION_ARTEFACT_TYPE: CONNECTION_TABLE,
    DIAGRAM_ARTEFACT_TYPE: DIAGRAM_TABLE,
}
