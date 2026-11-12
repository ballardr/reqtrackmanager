"""
Module: modules.architecture.record_tables

The `RecordTableProvider`s of the module's two record types, the element and the connection: each list as a
table, so it exports to CSV, PDF and Word and imports from the same CSV (a row with a code updates that
record, a blank code creates one).

Responsibilities:
- Declare the columns (name, type, parent, owner, status, ports; or type, ends, ports, protocol) and
  filters, and share the create and edit logic with the endpoints (`records.create_element` and so on), so
  validation, the version counter and the audit event are the ones the screen applies.

Design decisions:
- The type is written by its name (the project's effective list); the parent and the two ends by the code of
  an element of the same project, which must already exist, so a file cannot reach another project's record.
- `status` is importable because the module has no approval gate (an element or a connection may move
  between any two states); a new record can be created `Draft` or `Active`, not `Retired`.
- `ports` is one list cell, `name:direction` per port (`Main:both;Debug:in`), the way the export writes it. An
  import *adds* the ports a cell names that the element lacks and never removes or edits one, so a round trip
  changes nothing and removing a port stays a deliberate act on the element.
- An import update quotes the record's current `version`: a file is applied to the record as it is now.

Dependencies: `records` (rules), `record_routes` (filters), `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.architecture import records
from app.modules.architecture._shared import CONNECTION_MANAGE_PERMISSION, ELEMENT_MANAGE_PERMISSION, require_architect
from app.modules.architecture.enums import PortDirection, RecordStatus
from app.modules.architecture.labels import PORT_DIRECTION_LABEL, RECORD_STATUS_LABEL
from app.modules.architecture.models import ArchitectureConnection, ArchitectureElement, ArchitecturePort
from app.modules.architecture.record_routes import filter_connections, filter_elements
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
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
    ELEMENT_TYPES,
)
from app.modules.registry import RecordCellError, RecordColumn, RecordFilters, RecordImportContext, RecordTableProvider
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

ELEMENT_FILTERS = frozenset({"include_archived", "status", "type", "open_only", "search", "roots_only"})
CONNECTION_FILTERS = frozenset({"include_archived", "status", "type", "open_only", "search"})

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


def _type_names(vocabulary: Any, db: Session, project: Project) -> dict[str, uuid.UUID]:
    """`{lower-case name: id}` of the project's effective types."""
    return {row.name.casefold(): row.id for row in vocabulary.resolve_effective(db, project.id, project.organization_id).rows}


def _type_parser(vocabulary: Any, kind: str) -> Callable[[RecordImportContext, str], uuid.UUID]:
    """A parser for a type name of the importing project (required: an empty cell is refused)."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID:
        if not text:
            raise RecordCellError(f"A {vocabulary.label.lower()} is required.")
        found = cached_lookup(ctx, f"{kind}:names", lambda: _type_names(vocabulary, ctx.db, ctx.project)).get(text.casefold())
        if found is None:
            raise RecordCellError(f"Unknown {vocabulary.label.lower()} '{text}'.")
        return found

    return parse


def _element_by_code_parser(field_name: str, *, blank_clears: bool) -> Callable[[RecordImportContext, str], uuid.UUID | None]:
    """A parser for the code of an element of the importing project (`ELM-004`); an empty cell means none."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            if blank_clears:
                return None
            raise RecordCellError(f"{field_name} is required.")
        codes = cached_lookup(ctx, "elements:codes", lambda: {
            code.upper(): element_id for element_id, code in ctx.db.execute(
                select(ArchitectureElement.id, ArchitectureElement.unique_code).where(
                    ArchitectureElement.project_id == ctx.project.id
                )
            )
        })
        found = codes.get(text.upper())
        if found is None:
            raise RecordCellError(f"{field_name} '{text}' is not an element of this project.")
        return found

    return parse


def _status_column() -> RecordColumn:
    return RecordColumn(
        "status", "Status", lambda t, r: RECORD_STATUS_LABEL[r.status], enum_parser(RecordStatus, "Status"),
        kind="enum", editable=True, choices=tuple(RECORD_STATUS_LABEL.values()), tones=_STATUS_TONES,
    )


class _Prepared:
    """Lookups handed to every column's `get`: type names, people, tags, parent and end codes, port text."""

    def __init__(self, db: Session, project: Project, records_: Sequence[Any], artefact_type: str) -> None:
        ids = [r.id for r in records_]
        self.tags = tag_service.tag_names_for_records(db, artefact_type, ids) if ids else {}
        self.element_types = {row.id: row.name for row in ELEMENT_TYPES.resolve_effective(db, project.id, project.organization_id).rows}
        self.connection_types = {
            row.id: row.name for row in CONNECTION_TYPES.resolve_effective(db, project.id, project.organization_id).rows
        }
        self.codes: dict[uuid.UUID, str] = {}
        self.ports_text: dict[uuid.UUID, str] = {}
        self.port_names: dict[uuid.UUID, str] = {}
        self.people = PrincipalCells.load(db, [])
        if artefact_type == ELEMENT_ARTEFACT_TYPE:
            self.people = PrincipalCells.load(db, [principal_ref(r.owner_type, r.owner_id) for r in records_])
            wanted = {r.parent_id for r in records_ if r.parent_id}
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
            self.codes = dict(db.execute(
                select(ArchitectureElement.id, ArchitectureElement.unique_code).where(ArchitectureElement.id.in_(wanted))
            ).tuples().all())


def _tags_column() -> RecordColumn:
    return RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list")


# --- Element ---------------------------------------------------------------


def _prepare_elements(db: Session, project: Project, records_: list[ArchitectureElement]) -> _Prepared:
    return _Prepared(db, project, records_, ELEMENT_ARTEFACT_TYPE)


def _list_elements(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ArchitectureElement]:
    project = project_or_404(db, project_id)
    type_name = filters.one("type")
    type_id = None
    if type_name is not None:
        type_id = _type_names(ELEMENT_TYPES, db, project).get(type_name.casefold())
        if type_id is None:
            return []
    status = enum_filter(filters, "status", RecordStatus)
    return filter_elements(
        records.list_elements(db, project_id, include_archived=bool(filters.flag("include_archived"))),
        status_=status.value if status else None, element_type_id=type_id, roots_only=bool(filters.flag("roots_only")),
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    )


def _element_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        RecordColumn("name", "Name", lambda t, r: r.name, text_parser, editable=False, required=True),
        RecordColumn("description", "Description", lambda t, r: r.description, text_parser),
        RecordColumn(
            "type", "Type", lambda t, r: t.element_types.get(r.element_type_id, ""), _type_parser(ELEMENT_TYPES, "element"),
            kind="enum", required=True, choices=tuple(_type_names_ordered(ELEMENT_TYPES, db, project)),
        ),
        RecordColumn(
            "parent", "Parent element", lambda t, r: t.codes.get(r.parent_id, "") if r.parent_id else "",
            _element_by_code_parser("Parent element", blank_clears=True),
        ),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(r.owner_type, r.owner_id), person_parser("owner"), kind="principal",
        ),
        _status_column(),
        RecordColumn("ports", "Ports", lambda t, r: t.ports_text.get(r.id, ""), list_parser, kind="list"),
        _tags_column(),
    ]


def _type_names_ordered(vocabulary: Any, db: Session, project: Project) -> list[str]:
    return [row.name for row in vocabulary.resolve_effective(db, project.id, project.organization_id).rows]


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
    if status is RecordStatus.RETIRED:
        raise RecordCellError("A new element cannot be created Retired.")
    payload = _payload(ElementCreate, {
        "name": values.get("name", ""), "description": values.get("description", ""),
        "element_type_id": values.get("type"), "parent_id": values.get("parent"), "owner": values.get("owner"),
        "activate": status is RecordStatus.ACTIVE, "ports": _ports_from_cell(values.get("ports", [])),
    })
    return _rule(lambda: records.create_element(ctx.db, ctx.project, ctx.user, payload))


def _update_element(ctx: RecordImportContext, element: ArchitectureElement, values: Mapping[str, Any]) -> None:
    fields: dict[str, Any] = {}
    for key, field in (("name", "name"), ("description", "description"), ("type", "element_type_id"), ("parent", "parent_id"), ("owner", "owner")):
        if key in values:
            fields[field] = values[key]
    if fields:
        payload = _payload(ElementUpdate, {"version": element.version, **fields})
        _rule(lambda: records.update_element(ctx.db, ctx.project, ctx.user, element.id, payload))
    if "ports" in values:
        existing = {p.name.casefold() for p in records.ports_for(ctx.db, [element.id]).get(element.id, [])}
        for port in _ports_from_cell(values["ports"]):
            if port.name.casefold() not in existing:
                _rule(partial(records.add_port, ctx.db, ctx.project, ctx.user, element.id, port))
                existing.add(port.name.casefold())
    if values.get("status") is not None and values["status"].value != element.status:
        ctx.db.refresh(element)
        _rule(lambda: records.change_element_status(
            ctx.db, ctx.project, ctx.user, element.id, element.version, values["status"],
        ))


def _find_element(db: Session, project: Project, code: str) -> ArchitectureElement | None:
    return db.scalar(select(ArchitectureElement).where(
        ArchitectureElement.project_id == project.id, ArchitectureElement.unique_code == code.upper(),
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
    return filter_connections(
        records.list_connections(db, project_id, include_archived=bool(filters.flag("include_archived"))),
        status_=status.value if status else None, connection_type_id=type_id,
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    )


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
            _element_by_code_parser(f"{side.capitalize()} element", blank_clears=False), required=True,
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
        _status_column(),
        _tags_column(),
    ]


def _create_connection(ctx: RecordImportContext, values: Mapping[str, Any]) -> ArchitectureConnection:
    status = values.get("status")
    if status is RecordStatus.RETIRED:
        raise RecordCellError("A new connection cannot be created Retired.")
    source, target = values.get("source"), values.get("target")
    payload = _payload(ConnectionCreate, {
        "name": values.get("name", ""), "connection_type_id": values.get("type"), "source_element_id": source,
        "source_port_id": _port_by_name(ctx, source, values.get("source_port", ""), "source"),
        "target_element_id": target, "target_port_id": _port_by_name(ctx, target, values.get("target_port", ""), "target"),
        "protocol": values.get("protocol", ""), "description": values.get("description", ""),
        "activate": status is RecordStatus.ACTIVE,
    })
    return _rule(lambda: records.create_connection(ctx.db, ctx.project, ctx.user, payload))


def _update_connection(ctx: RecordImportContext, connection: ArchitectureConnection, values: Mapping[str, Any]) -> None:
    fields: dict[str, Any] = {}
    for key, field in (("name", "name"), ("type", "connection_type_id"), ("protocol", "protocol"), ("description", "description")):
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

RECORD_TABLES: dict[str, RecordTableProvider] = {
    ELEMENT_ARTEFACT_TYPE: ELEMENT_TABLE,
    CONNECTION_ARTEFACT_TYPE: CONNECTION_TABLE,
}
