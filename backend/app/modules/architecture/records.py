"""
Module: modules.architecture.records

The rules for elements, their ports and connections, and the bulk reads behind
their API shapes.

Responsibilities:
- Create, edit, move, change the status of, archive and delete an element; add,
  edit and remove its ports; create, edit, archive and delete a connection. Each
  change validates its references, advances the record's `version`, and writes one
  audit event holding ids and field names, never free text.
- Read lists in bulk (`element_outs`, `connection_outs`): one query per kind of
  related row however many records are listed.
- Register the vocabulary usage checks, so a type a record uses is never deleted.

Design decisions:
- A save quotes the `version` it was based on (`VersionConflict` otherwise), and the
  row is locked while it is checked, so two saves cannot both win.
- Tree rules: a parent belongs to the same project, a move may not create a cycle,
  and the tree is at most `MAX_DEPTH` levels deep (a move counts the subtree it carries).
- Retiring or archiving an element needs every child to be retired or archived
  first; deleting needs no children and no connection ending at it. These are
  integrity rules (a hidden child would be orphaned from its parent's view, and a
  connection would lose an end).
- A status may move between any two states: there is no approval gate on this
  module's records.
- Port changes advance the element's `version`, so an editor holding a stale copy
  is told before overwriting.

Dependencies: `service` (vocabularies, constants), core `services.sequences`,
`services.principals`, `services.relationships`, `services.tags`,
`services.placements`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.architecture.enums import RecordStatus
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionType,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitecturePort,
)
from app.modules.architecture.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionUpdate,
    ElementCreate,
    ElementOut,
    ElementUpdate,
    PortCreate,
    PortOut,
    PortUpdate,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_CODE_PREFIX,
    CONNECTION_TYPES,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
    ELEMENT_TYPES,
)
from app.schemas.principal import PrincipalRef
from app.services import placements as placement_service
from app.services import tags as tag_service
from app.services.audit import log_event
from app.services.principals import label_of, principal_columns, principal_labels, principal_ref, validate_principal
from app.services.relationships import delete_link, get_all_links
from app.services.sequences import generate_unique_code

#: The deepest an element tree may be (a root is depth 1).
MAX_DEPTH = 12

_NO_STATUS_CHANGE_NEEDED = "The record already has this status."


class RuleError(Exception):
    """A change the rules refuse.

    Attributes:
        status_code: The HTTP status the router answers with (400 for a bad reference, 404 for a missing
            record, 409 for a conflict with the record's state or version).
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class VersionConflict(RuleError):
    """The record changed since the version the caller based the save on."""

    def __init__(self) -> None:
        super().__init__("This record was changed by someone else. Reload it and apply your change again.", 409)


# --- Lookups ---------------------------------------------------------------


def get_element(db: Session, project_id: uuid.UUID, element_id: uuid.UUID, *, lock: bool = False) -> ArchitectureElement:
    """The element in the project; `lock` takes a row lock for a write.

    Raises:
        RuleError: 404 if it does not exist in the project.
    """
    query = select(ArchitectureElement).where(
        ArchitectureElement.id == element_id, ArchitectureElement.project_id == project_id,
    )
    element = db.scalar(query.with_for_update() if lock else query)
    if element is None:
        raise RuleError("Element not found.", 404)
    return element


def get_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, *, lock: bool = False,
) -> ArchitectureConnection:
    """The connection in the project; `lock` takes a row lock for a write.

    Raises:
        RuleError: 404 if it does not exist in the project.
    """
    query = select(ArchitectureConnection).where(
        ArchitectureConnection.id == connection_id, ArchitectureConnection.project_id == project_id,
    )
    connection = db.scalar(query.with_for_update() if lock else query)
    if connection is None:
        raise RuleError("Connection not found.", 404)
    return connection


def get_port(db: Session, element: ArchitectureElement, port_id: uuid.UUID) -> ArchitecturePort:
    """The port of `element`.

    Raises:
        RuleError: 404 if the element has no such port.
    """
    port = db.scalar(
        select(ArchitecturePort).where(ArchitecturePort.id == port_id, ArchitecturePort.element_id == element.id)
    )
    if port is None:
        raise RuleError("Port not found.", 404)
    return port


def list_elements(db: Session, project_id: uuid.UUID, *, include_archived: bool = False) -> list[ArchitectureElement]:
    """The project's elements ordered by code."""
    query = select(ArchitectureElement).where(ArchitectureElement.project_id == project_id)
    if not include_archived:
        query = query.where(ArchitectureElement.is_archived.is_(False))
    return list(db.scalars(query.order_by(ArchitectureElement.unique_code)))


def list_connections(
    db: Session, project_id: uuid.UUID, *, include_archived: bool = False,
) -> list[ArchitectureConnection]:
    """The project's connections ordered by code."""
    query = select(ArchitectureConnection).where(ArchitectureConnection.project_id == project_id)
    if not include_archived:
        query = query.where(ArchitectureConnection.is_archived.is_(False))
    return list(db.scalars(query.order_by(ArchitectureConnection.unique_code)))


# --- Shared checks ---------------------------------------------------------


def _check_version(record: ArchitectureElement | ArchitectureConnection, version: int) -> None:
    """Raises `VersionConflict` unless `version` is the record's current one."""
    if record.version != version:
        raise VersionConflict()


def _validate_owner(db: Session, project: Project, owner: PrincipalRef | None) -> None:
    """Rejects an owner who is not valid for the project (a non-member user, a foreign group)."""
    from fastapi import HTTPException

    try:
        validate_principal(db, owner, organization_id=project.organization_id, project_id=project.id, field="owner")
    except HTTPException as exc:
        raise RuleError(str(exc.detail), 400) from exc


def _touch(record: ArchitectureElement | ArchitectureConnection, **changes: Any) -> None:
    """Applies `changes` and advances the version."""
    for key, value in changes.items():
        setattr(record, key, value)
    record.version += 1


def _detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    """An audit detail without its empty entries, or `None` when nothing is left."""
    return {k: v for k, v in detail.items() if v not in (None, [], "")} or None


def _audit_element(
    db: Session, record_id: uuid.UUID, action: str, actor: User, project_id: uuid.UUID, **detail: Any,
) -> None:
    """Writes the audit event for a change to an element: ids and field names only."""
    log_event(
        db, entity_type=ELEMENT_ARTEFACT_TYPE, entity_id=record_id, action=action, actor_id=actor.id,
        project_id=project_id, detail=_detail(detail),
    )


def _audit_connection(
    db: Session, record_id: uuid.UUID, action: str, actor: User, project_id: uuid.UUID, **detail: Any,
) -> None:
    """Writes the audit event for a change to a connection: ids and field names only."""
    log_event(
        db, entity_type=CONNECTION_ARTEFACT_TYPE, entity_id=record_id, action=action, actor_id=actor.id,
        project_id=project_id, detail=_detail(detail),
    )


def _depth_of(parents: dict[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID) -> int:
    """Levels from `element_id` to its root, inclusive (cycle-safe)."""
    depth, seen = 0, set()
    current: uuid.UUID | None = element_id
    while current is not None and current not in seen:
        seen.add(current)
        depth += 1
        current = parents.get(current)
    return depth


def _height_of(children: dict[uuid.UUID, list[uuid.UUID]], element_id: uuid.UUID) -> int:
    """Levels in the subtree under `element_id`, inclusive (iterative, cycle-safe)."""
    best, frontier, seen = 0, [(element_id, 1)], {element_id}
    while frontier:
        current, level = frontier.pop()
        best = max(best, level)
        for child in children.get(current, ()):
            if child not in seen:
                seen.add(child)
                frontier.append((child, level + 1))
    return best


def _check_parent(db: Session, project_id: uuid.UUID, element_id: uuid.UUID | None, parent_id: uuid.UUID) -> None:
    """Checks `parent_id` can hold `element_id` (a new element when `element_id` is `None`).

    Raises:
        RuleError: 400 if the parent is not in the project or archived, the move makes a cycle, or the tree
            would be deeper than `MAX_DEPTH`.
    """
    rows = db.execute(
        select(ArchitectureElement.id, ArchitectureElement.parent_id, ArchitectureElement.is_archived)
        .where(ArchitectureElement.project_id == project_id)
    ).all()
    parents = {row.id: row.parent_id for row in rows}
    if parent_id not in parents:
        raise RuleError("The parent element is not in this project.", 400)
    if next(row.is_archived for row in rows if row.id == parent_id):
        raise RuleError("An archived element cannot hold children.", 400)
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for child, parent in parents.items():
        if parent is not None:
            children[parent].append(child)
    carried = 1
    if element_id is not None:
        # The new parent may not be the element or one of its descendants.
        seen = set()
        current: uuid.UUID | None = parent_id
        while current is not None and current not in seen:
            if current == element_id:
                raise RuleError("An element cannot be moved under itself or one of its own children.", 400)
            seen.add(current)
            current = parents.get(current)
        carried = _height_of(children, element_id)
    if _depth_of(parents, parent_id) + carried > MAX_DEPTH:
        raise RuleError(f"The element tree can be at most {MAX_DEPTH} levels deep.", 400)


def _usable_element_type(db: Session, project: Project, type_id: uuid.UUID):
    try:
        return ELEMENT_TYPES.usable_row(db, project.id, project.organization_id, type_id)
    except ValueError as exc:
        raise RuleError(str(exc), 400) from exc


def _usable_connection_type(db: Session, project: Project, type_id: uuid.UUID):
    try:
        return CONNECTION_TYPES.usable_row(db, project.id, project.organization_id, type_id)
    except ValueError as exc:
        raise RuleError(str(exc), 400) from exc


def _validate_ports(ports: Sequence[PortCreate]) -> None:
    """Raises 400 if two ports of one element share a name (ignoring case)."""
    names = [p.name.strip().lower() for p in ports]
    if len(set(names)) != len(names):
        raise RuleError("Two ports of an element cannot share a name.", 400)


# --- Elements --------------------------------------------------------------


def create_element(db: Session, project: Project, actor: User, payload: ElementCreate) -> ArchitectureElement:
    """Creates an element (and its initial ports). The caller commits.

    Raises:
        RuleError: 400 for a type, parent, owner or port that is not valid.
    """
    _usable_element_type(db, project, payload.element_type_id)
    if payload.parent_id is not None:
        _check_parent(db, project.id, None, payload.parent_id)
    _validate_owner(db, project, payload.owner)
    _validate_ports(payload.ports)
    for port in payload.ports:
        if port.connection_type_id is not None:
            _usable_connection_type(db, project, port.connection_type_id)
    element = ArchitectureElement(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, ELEMENT_ARTEFACT_TYPE, ELEMENT_CODE_PREFIX),
        name=payload.name.strip(), description=payload.description, element_type_id=payload.element_type_id,
        parent_id=payload.parent_id, status=(RecordStatus.ACTIVE if payload.activate else RecordStatus.DRAFT).value,
        version=1, creator_id=actor.id, is_archived=False, **principal_columns("owner", payload.owner),
    )
    db.add(element)
    db.flush()
    for order, port in enumerate(payload.ports):
        db.add(ArchitecturePort(
            element_id=element.id, name=port.name.strip(), direction=port.direction.value,
            connection_type_id=port.connection_type_id, sort_order=order,
        ))
    db.flush()
    _audit_element(
        db, element.id, "created", actor, project.id,
        unique_code=element.unique_code, ports=len(payload.ports), status=element.status,
    )
    return element


def update_element(
    db: Session, project: Project, actor: User, element_id: uuid.UUID, payload: ElementUpdate,
) -> ArchitectureElement:
    """Applies the fields the body names to an element. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for an invalid type, parent or owner.
    """
    element = get_element(db, project.id, element_id, lock=True)
    _check_version(element, payload.version)
    given = payload.model_fields_set
    changes: dict[str, Any] = {}
    if payload.name is not None and payload.name.strip() != element.name:
        changes["name"] = payload.name.strip()
    if payload.description is not None and payload.description != element.description:
        changes["description"] = payload.description
    if payload.element_type_id is not None and payload.element_type_id != element.element_type_id:
        _usable_element_type(db, project, payload.element_type_id)
        changes["element_type_id"] = payload.element_type_id
    if "parent_id" in given and payload.parent_id != element.parent_id:
        if payload.parent_id is not None:
            _check_parent(db, project.id, element.id, payload.parent_id)
        changes["parent_id"] = payload.parent_id
    if "owner" in given and principal_ref(element.owner_type, element.owner_id) != _ref(payload.owner):
        _validate_owner(db, project, payload.owner)
        changes.update(principal_columns("owner", payload.owner))
    if not changes:
        return element
    _touch(element, **changes)
    db.flush()
    fields = sorted({"owner" if k.startswith("owner_") else k for k in changes})
    _audit_element(db, element.id, "moved" if fields == ["parent_id"] else "updated", actor, project.id, fields=fields)
    return element


def _ref(owner: PrincipalRef | None):
    """A request principal as the `PrincipalRef` the stored columns compare equal to."""
    return principal_ref(owner.type.value, owner.id) if owner is not None else None


def change_element_status(
    db: Session, project: Project, actor: User, element_id: uuid.UUID, version: int, status: RecordStatus,
) -> ArchitectureElement:
    """Moves an element to `status`. Retiring needs every child to be retired or archived. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale version, when the status is unchanged or a child is still in use.
    """
    element = get_element(db, project.id, element_id, lock=True)
    _check_version(element, version)
    if element.status == status.value:
        raise RuleError(_NO_STATUS_CHANGE_NEEDED, 409)
    if status is RecordStatus.RETIRED:
        _require_children_finished(db, element, "retire")
    previous = element.status
    _touch(element, status=status.value)
    db.flush()
    _audit_element(db, element.id, "status_changed", actor, project.id, previous=previous, status=status.value)
    return element


def _require_children_finished(db: Session, element: ArchitectureElement, verb: str) -> None:
    """Raises 409 when a child of `element` is neither retired nor archived."""
    open_children = db.scalar(
        select(func.count()).select_from(ArchitectureElement).where(
            ArchitectureElement.parent_id == element.id, ArchitectureElement.is_archived.is_(False),
            ArchitectureElement.status != RecordStatus.RETIRED.value,
        )
    )
    if open_children:
        raise RuleError(f"This element still has {open_children} child element(s) in use; retire them first to {verb} it.", 409)


def set_element_archived(
    db: Session, project: Project, actor: User, element_id: uuid.UUID, archived: bool,
) -> ArchitectureElement:
    """Archives or unarchives an element (archiving needs every child retired or archived). The caller commits.

    Raises:
        RuleError: 404 if absent; 409 if archiving with children in use or the parent is archived on restore.
    """
    element = get_element(db, project.id, element_id, lock=True)
    if element.is_archived == archived:
        return element
    if archived:
        _require_children_finished(db, element, "archive")
    elif element.parent_id is not None:
        parent = db.get(ArchitectureElement, element.parent_id)
        if parent is not None and parent.is_archived:
            raise RuleError("Restore the parent element first.", 409)
    element.is_archived = archived
    element.archived_at = datetime.now(UTC) if archived else None
    element.archived_by = actor.id if archived else None
    element.version += 1
    db.flush()
    _audit_element(db, element.id, "archived" if archived else "unarchived", actor, project.id)
    return element


def delete_element(db: Session, project: Project, actor: User, element_id: uuid.UUID) -> None:
    """Deletes an element, its ports, links, tags and places. The caller commits.

    Raises:
        RuleError: 404 if absent; 409 while it has children or a connection ends at it.
    """
    element = get_element(db, project.id, element_id, lock=True)
    if db.scalar(select(func.count()).select_from(ArchitectureElement).where(ArchitectureElement.parent_id == element.id)):
        raise RuleError("This element has child elements; move or delete them first.", 409)
    if db.scalar(select(func.count()).select_from(ArchitectureConnection).where(
        or_(ArchitectureConnection.source_element_id == element.id, ArchitectureConnection.target_element_id == element.id)
    )):
        raise RuleError("A connection ends at this element; delete the connection first.", 409)
    _forget(db, ELEMENT_ARTEFACT_TYPE, element.id)
    db.delete(element)
    db.flush()
    _audit_element(db, element.id, "deleted", actor, project.id)


def _forget(db: Session, artefact_type: str, record_id: uuid.UUID) -> None:
    """Removes the links, tags and places that refer to a record being deleted."""
    for link in get_all_links(db, artefact_type, record_id, include_cross_project=True):
        delete_link(db, link)
    tag_service.forget_record_tags(db, artefact_type, record_id)
    placement_service.forget_record_placements(db, artefact_type, record_id)


# --- Ports -----------------------------------------------------------------


def add_port(
    db: Session, project: Project, actor: User, element_id: uuid.UUID, payload: PortCreate,
) -> ArchitecturePort:
    """Adds a port at the end of the element's list. The caller commits.

    Raises:
        RuleError: 404 if the element is absent; 400 for a duplicate name or an invalid connection type.
    """
    element = get_element(db, project.id, element_id, lock=True)
    name = payload.name.strip()
    if db.scalar(select(ArchitecturePort.id).where(
        ArchitecturePort.element_id == element.id, func.lower(ArchitecturePort.name) == name.lower(),
    )):
        raise RuleError("This element already has a port with that name.", 400)
    if payload.connection_type_id is not None:
        _usable_connection_type(db, project, payload.connection_type_id)
    count = db.scalar(select(func.count()).select_from(ArchitecturePort).where(ArchitecturePort.element_id == element.id)) or 0
    port = ArchitecturePort(
        element_id=element.id, name=name, direction=payload.direction.value,
        connection_type_id=payload.connection_type_id, sort_order=count,
    )
    db.add(port)
    element.version += 1
    db.flush()
    _audit_element(db, element.id, "updated", actor, project.id, fields=["ports"], port_added=str(port.id))
    return port


def update_port(
    db: Session, project: Project, actor: User, element_id: uuid.UUID, port_id: uuid.UUID, payload: PortUpdate,
) -> ArchitecturePort:
    """Edits a port. The caller commits.

    Raises:
        RuleError: 404 if absent; 400 for a duplicate name or an invalid connection type.
    """
    element = get_element(db, project.id, element_id, lock=True)
    port = get_port(db, element, port_id)
    given = payload.model_fields_set
    if payload.name is not None and payload.name.strip().lower() != port.name.lower():
        if db.scalar(select(ArchitecturePort.id).where(
            ArchitecturePort.element_id == element.id, func.lower(ArchitecturePort.name) == payload.name.strip().lower(),
        )):
            raise RuleError("This element already has a port with that name.", 400)
    if payload.name is not None:
        port.name = payload.name.strip()
    if payload.direction is not None:
        port.direction = payload.direction.value
    if "connection_type_id" in given:
        if payload.connection_type_id is not None:
            _usable_connection_type(db, project, payload.connection_type_id)
        port.connection_type_id = payload.connection_type_id
    element.version += 1
    db.flush()
    _audit_element(db, element.id, "updated", actor, project.id, fields=["ports"], port_changed=str(port.id))
    return port


def delete_port(db: Session, project: Project, actor: User, element_id: uuid.UUID, port_id: uuid.UUID) -> None:
    """Removes a port. The caller commits.

    Raises:
        RuleError: 404 if absent; 409 while a connection uses the port.
    """
    element = get_element(db, project.id, element_id, lock=True)
    port = get_port(db, element, port_id)
    if db.scalar(select(func.count()).select_from(ArchitectureConnection).where(
        or_(ArchitectureConnection.source_port_id == port.id, ArchitectureConnection.target_port_id == port.id)
    )):
        raise RuleError("A connection uses this port; change the connection first.", 409)
    db.delete(port)
    element.version += 1
    db.flush()
    _audit_element(db, element.id, "updated", actor, project.id, fields=["ports"], port_removed=str(port_id))


# --- Connections -----------------------------------------------------------


def _check_end(db: Session, project_id: uuid.UUID, element_id: uuid.UUID, port_id: uuid.UUID | None, side: str) -> None:
    """Checks one end of a connection: an unarchived element of the project and, if named, one of its ports.

    Raises:
        RuleError: 400 otherwise.
    """
    element = db.scalar(select(ArchitectureElement).where(
        ArchitectureElement.id == element_id, ArchitectureElement.project_id == project_id,
    ))
    if element is None or element.is_archived:
        raise RuleError(f"The {side} element is not an available element of this project.", 400)
    if port_id is not None and db.scalar(
        select(ArchitecturePort.id).where(ArchitecturePort.id == port_id, ArchitecturePort.element_id == element_id)
    ) is None:
        raise RuleError(f"The {side} port does not belong to the {side} element.", 400)


def create_connection(db: Session, project: Project, actor: User, payload: ConnectionCreate) -> ArchitectureConnection:
    """Creates a connection. The caller commits.

    Raises:
        RuleError: 400 for an invalid type, end or port, or when both ends are the same element.
    """
    _usable_connection_type(db, project, payload.connection_type_id)
    if payload.source_element_id == payload.target_element_id:
        raise RuleError("A connection joins two different elements.", 400)
    _check_end(db, project.id, payload.source_element_id, payload.source_port_id, "source")
    _check_end(db, project.id, payload.target_element_id, payload.target_port_id, "target")
    connection = ArchitectureConnection(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, CONNECTION_ARTEFACT_TYPE, CONNECTION_CODE_PREFIX),
        name=payload.name.strip(), connection_type_id=payload.connection_type_id,
        source_element_id=payload.source_element_id, source_port_id=payload.source_port_id,
        target_element_id=payload.target_element_id, target_port_id=payload.target_port_id,
        protocol=payload.protocol.strip(), description=payload.description,
        status=(RecordStatus.ACTIVE if payload.activate else RecordStatus.DRAFT).value,
        version=1, creator_id=actor.id, is_archived=False,
    )
    db.add(connection)
    db.flush()
    _audit_connection(db, connection.id, "created", actor, project.id, unique_code=connection.unique_code, status=connection.status)
    return connection


def update_connection(
    db: Session, project: Project, actor: User, connection_id: uuid.UUID, payload: ConnectionUpdate,
) -> ArchitectureConnection:
    """Applies the fields the body names to a connection. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for an invalid type, end or port.
    """
    connection = get_connection(db, project.id, connection_id, lock=True)
    _check_version(connection, payload.version)
    given = payload.model_fields_set
    changes: dict[str, Any] = {}
    if payload.connection_type_id is not None and payload.connection_type_id != connection.connection_type_id:
        _usable_connection_type(db, project, payload.connection_type_id)
        changes["connection_type_id"] = payload.connection_type_id
    for key in ("name", "protocol"):
        value = getattr(payload, key)
        if value is not None and value.strip() != getattr(connection, key):
            changes[key] = value.strip()
    if payload.description is not None and payload.description != connection.description:
        changes["description"] = payload.description
    ends: dict[str, Any] = {
        "source_element_id": connection.source_element_id, "source_port_id": connection.source_port_id,
        "target_element_id": connection.target_element_id, "target_port_id": connection.target_port_id,
    }
    wanted: dict[str, Any] = dict(ends)
    for key in ends:
        if key in given and (key.endswith("_port_id") or getattr(payload, key) is not None):
            wanted[key] = getattr(payload, key)
    # Changing an end's element without naming its port drops the old port, which belongs to the old element.
    for side in ("source", "target"):
        if wanted[f"{side}_element_id"] != ends[f"{side}_element_id"] and f"{side}_port_id" not in given:
            wanted[f"{side}_port_id"] = None
    if wanted != ends:
        if wanted["source_element_id"] == wanted["target_element_id"]:
            raise RuleError("A connection joins two different elements.", 400)
        for side in ("source", "target"):
            if wanted[f"{side}_element_id"] != ends[f"{side}_element_id"] or wanted[f"{side}_port_id"] != ends[f"{side}_port_id"]:
                _check_end(db, project.id, wanted[f"{side}_element_id"], wanted[f"{side}_port_id"], side)
        changes.update({k: v for k, v in wanted.items() if v != ends[k]})
    if not changes:
        return connection
    _touch(connection, **changes)
    db.flush()
    _audit_connection(db, connection.id, "updated", actor, project.id, fields=sorted(changes))
    return connection


def change_connection_status(
    db: Session, project: Project, actor: User, connection_id: uuid.UUID, version: int, status: RecordStatus,
) -> ArchitectureConnection:
    """Moves a connection to `status`. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale version or when the status is unchanged.
    """
    connection = get_connection(db, project.id, connection_id, lock=True)
    _check_version(connection, version)
    if connection.status == status.value:
        raise RuleError(_NO_STATUS_CHANGE_NEEDED, 409)
    previous = connection.status
    _touch(connection, status=status.value)
    db.flush()
    _audit_connection(db, connection.id, "status_changed", actor, project.id, previous=previous, status=status.value)
    return connection


def set_connection_archived(
    db: Session, project: Project, actor: User, connection_id: uuid.UUID, archived: bool,
) -> ArchitectureConnection:
    """Archives or unarchives a connection. Restoring needs both ends to be unarchived. The caller commits.

    Raises:
        RuleError: 404 if absent; 409 if an end is archived on restore.
    """
    connection = get_connection(db, project.id, connection_id, lock=True)
    if connection.is_archived == archived:
        return connection
    if not archived and db.scalar(select(func.count()).select_from(ArchitectureElement).where(
        ArchitectureElement.id.in_((connection.source_element_id, connection.target_element_id)),
        ArchitectureElement.is_archived.is_(True),
    )):
        raise RuleError("An end of this connection is archived; restore it first.", 409)
    connection.is_archived = archived
    connection.archived_at = datetime.now(UTC) if archived else None
    connection.archived_by = actor.id if archived else None
    connection.version += 1
    db.flush()
    _audit_connection(db, connection.id, "archived" if archived else "unarchived", actor, project.id)
    return connection


def delete_connection(db: Session, project: Project, actor: User, connection_id: uuid.UUID) -> None:
    """Deletes a connection and the links, tags and places that refer to it. The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    connection = get_connection(db, project.id, connection_id, lock=True)
    _forget(db, CONNECTION_ARTEFACT_TYPE, connection.id)
    db.delete(connection)
    db.flush()
    _audit_connection(db, connection.id, "deleted", actor, project.id)


# --- API shapes (bulk) -----------------------------------------------------


def _type_names(db: Session, model: Any, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """`{type id: name}` for the type rows with the given ids."""
    wanted = set(ids)
    if not wanted:
        return {}
    return {row.id: row.name for row in db.scalars(select(model).where(model.id.in_(wanted)))}


def ports_for(db: Session, element_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ArchitecturePort]]:
    """`{element id: its ports in order}` in one query."""
    found: dict[uuid.UUID, list[ArchitecturePort]] = defaultdict(list)
    if element_ids:
        for port in db.scalars(
            select(ArchitecturePort).where(ArchitecturePort.element_id.in_(element_ids))
            .order_by(ArchitecturePort.sort_order, ArchitecturePort.name)
        ):
            found[port.element_id].append(port)
    return found


def port_out(port: ArchitecturePort, connection_type_names: dict[uuid.UUID, str]) -> PortOut:
    """A port's API shape."""
    return PortOut(
        id=port.id, element_id=port.element_id, name=port.name, direction=port.direction,
        connection_type_id=port.connection_type_id,
        connection_type_name=connection_type_names.get(port.connection_type_id) if port.connection_type_id else None,
        sort_order=port.sort_order,
    )


def element_outs(db: Session, elements: Sequence[ArchitectureElement]) -> list[ElementOut]:
    """API shapes for `elements`: related rows are read in bulk, so the cost does not grow with the list."""
    ids = [e.id for e in elements]
    ports = ports_for(db, ids)
    element_types = _type_names(db, ArchitectureElementType, (e.element_type_id for e in elements))
    connection_types = _type_names(
        db, ArchitectureConnectionType, (p.connection_type_id for ps in ports.values() for p in ps if p.connection_type_id),
    )
    child_counts: dict[uuid.UUID, int] = {}
    connection_counts: dict[uuid.UUID, int] = defaultdict(int)
    if ids:
        child_counts = {
            parent_id: count for parent_id, count in db.execute(
                select(ArchitectureElement.parent_id, func.count()).where(ArchitectureElement.parent_id.in_(ids))
                .group_by(ArchitectureElement.parent_id)
            ).tuples() if parent_id is not None
        }
        live = ArchitectureConnection.is_archived.is_(False)
        for column in (ArchitectureConnection.source_element_id, ArchitectureConnection.target_element_id):
            for element_id, count in db.execute(
                select(column, func.count()).where(column.in_(ids), live).group_by(column)
            ).tuples():
                connection_counts[element_id] += count
    labels = principal_labels(db, [principal_ref(e.owner_type, e.owner_id) for e in elements])
    return [
        ElementOut(
            id=e.id, project_id=e.project_id, unique_code=e.unique_code, name=e.name, description=e.description,
            element_type_id=e.element_type_id, element_type_name=element_types.get(e.element_type_id, ""),
            parent_id=e.parent_id, owner=label_of(labels, e.owner_type, e.owner_id), status=e.status, version=e.version,
            creator_id=e.creator_id, is_archived=e.is_archived, archived_at=e.archived_at, created_at=e.created_at,
            updated_at=e.updated_at, child_count=child_counts.get(e.id, 0), connection_count=connection_counts.get(e.id, 0),
            ports=[port_out(p, connection_types) for p in ports.get(e.id, ())],
        )
        for e in elements
    ]


def connection_outs(db: Session, connections: Sequence[ArchitectureConnection]) -> list[ConnectionOut]:
    """API shapes for `connections`: types, ends and ports are read in bulk."""
    end_ids = {c.source_element_id for c in connections} | {c.target_element_id for c in connections}
    ends = {
        row.id: row for row in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(end_ids)))
    } if end_ids else {}
    port_ids = {p for c in connections for p in (c.source_port_id, c.target_port_id) if p}
    port_names = {
        row.id: row.name for row in db.scalars(select(ArchitecturePort).where(ArchitecturePort.id.in_(port_ids)))
    } if port_ids else {}
    types = {
        row.id: row for row in db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
        ))
    } if connections else {}
    return [
        ConnectionOut(
            id=c.id, project_id=c.project_id, unique_code=c.unique_code, name=c.name,
            connection_type_id=c.connection_type_id, connection_type_name=types[c.connection_type_id].name,
            directional=types[c.connection_type_id].directional,
            source_element_id=c.source_element_id, source_element_code=ends[c.source_element_id].unique_code,
            source_element_name=ends[c.source_element_id].name, source_port_id=c.source_port_id,
            source_port_name=port_names.get(c.source_port_id) if c.source_port_id else None,
            target_element_id=c.target_element_id, target_element_code=ends[c.target_element_id].unique_code,
            target_element_name=ends[c.target_element_id].name, target_port_id=c.target_port_id,
            target_port_name=port_names.get(c.target_port_id) if c.target_port_id else None,
            protocol=c.protocol, description=c.description, status=c.status, version=c.version,
            creator_id=c.creator_id, is_archived=c.is_archived, archived_at=c.archived_at, created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in connections
    ]


# --- Vocabulary usage ------------------------------------------------------


def _element_type_in_use(db: Session, type_id: uuid.UUID) -> bool:
    return db.scalar(select(ArchitectureElement.id).where(ArchitectureElement.element_type_id == type_id).limit(1)) is not None


def _connection_type_in_use(db: Session, type_id: uuid.UUID) -> bool:
    return (
        db.scalar(select(ArchitectureConnection.id).where(ArchitectureConnection.connection_type_id == type_id).limit(1)) is not None
        or db.scalar(select(ArchitecturePort.id).where(ArchitecturePort.connection_type_id == type_id).limit(1)) is not None
    )


def register_usage_checks() -> None:
    """Registers the checks that stop a type a record uses from being deleted (idempotent). Called when the module
    is registered, so it holds whichever router a request arrives through."""
    for vocabulary, check in ((ELEMENT_TYPES, _element_type_in_use), (CONNECTION_TYPES, _connection_type_in_use)):
        if check not in vocabulary.usage_checks:
            vocabulary.usage_checks.append(check)
