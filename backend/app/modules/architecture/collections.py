"""
Module: modules.architecture.collections

Collections, their members and their grants: how an owner shares elements.

A collection belongs to a project or to the organisation (`records.ElementOwner`) and holds that owner's elements.
A grant gives a project (optionally with every descendant project, now or later) or a group read access to the
collection's members and everything below them; the reading rules themselves are `visibility`.

Responsibilities:
- Create, rename and delete collections; add and remove members; add and revoke grants.
- Validate every target: a grant reaches only the owner's organisation, and a collection holds only its owner's
  elements.
- Write one audit event per change holding ids and counts, never a name or description.

Design decisions:
- A grant is a security-sensitive change (it publishes data to other projects), so it is audited and, in the
  routes, gated by the owner's manage permission. A foreign-organisation project or group is always refused; a
  project group of any project in the organisation may be granted (its effective members, with its nested
  organisation groups, see the collection).
- Deleting a collection removes its members and grants with it (the database cascades); the elements stay.
- A grant to a group the person later leaves, or to a project they cannot open, simply stops applying; nothing is
  copied, so revocation is immediate.

Dependencies: this module's models and `records` (owner, rule errors); core `services.principals`,
`services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.project import Project, ProjectGroup
from app.models.user import User
from app.modules.architecture.models import (
    ArchitectureCollection,
    ArchitectureCollectionGrant,
    ArchitectureCollectionMember,
    ArchitectureElement,
)
from app.modules.architecture.records import ElementOwner, RuleError
from app.modules.architecture.schemas import (
    CollectionCreate,
    CollectionGrantCreate,
    CollectionGrantOut,
    CollectionMemberOut,
    CollectionOut,
    CollectionUpdate,
)
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.principals import label_of, principal_labels, validate_principal

COLLECTION_ENTITY_TYPE = "architecture_collection"


def _owner_filter(owner: ElementOwner) -> ColumnElement[bool]:
    """The condition selecting the owner's collections."""
    if owner.project is not None:
        return ArchitectureCollection.project_id == owner.project.id
    return ArchitectureCollection.organization_id == owner.organization_id


def _audit(
    db: Session, collection_id: uuid.UUID, action: str, actor: User, owner: ElementOwner, **detail: Any,
) -> None:
    """Writes the audit event for a change to a collection: ids and counts only."""
    log_event(
        db, entity_type=COLLECTION_ENTITY_TYPE, entity_id=collection_id, action=action, actor_id=actor.id,
        detail={k: v for k, v in detail.items() if v not in (None, [], "")} or None, **owner.place,
    )


def get_collection(db: Session, owner: ElementOwner, collection_id: uuid.UUID, *, lock: bool = False) -> ArchitectureCollection:
    """The collection the owner owns; `lock` takes a row lock for a write.

    Raises:
        RuleError: 404 if it does not exist or another owner owns it.
    """
    query = select(ArchitectureCollection).where(ArchitectureCollection.id == collection_id, _owner_filter(owner))
    collection = db.scalar(query.with_for_update() if lock else query)
    if collection is None:
        raise RuleError("Collection not found.", 404)
    return collection


def _check_name(db: Session, owner: ElementOwner, name: str, exclude_id: uuid.UUID | None = None) -> None:
    """Rejects a name another of the owner's collections already uses (ignoring case).

    Raises:
        RuleError: 400 on a clash.
    """
    query = select(ArchitectureCollection.id).where(
        _owner_filter(owner), func.lower(ArchitectureCollection.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.where(ArchitectureCollection.id != exclude_id)
    if db.scalar(query.limit(1)) is not None:
        raise RuleError("A collection with that name already exists.", 400)


def create_collection(db: Session, owner: ElementOwner, actor: User, payload: CollectionCreate) -> ArchitectureCollection:
    """Creates an empty collection. The caller commits.

    Raises:
        RuleError: 400 if the name is already used.
    """
    name = payload.name.strip()
    _check_name(db, owner, name)
    collection = ArchitectureCollection(**owner.columns, name=name, description=payload.description, creator_id=actor.id)
    db.add(collection)
    db.flush()
    _audit(db, collection.id, "created", actor, owner)
    return collection


def update_collection(
    db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID, payload: CollectionUpdate,
) -> ArchitectureCollection:
    """Renames or re-describes a collection. The caller commits.

    Raises:
        RuleError: 404 if absent; 400 if the new name is already used.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    fields: list[str] = []
    if payload.name is not None and payload.name.strip() != collection.name:
        _check_name(db, owner, payload.name.strip(), collection.id)
        collection.name = payload.name.strip()
        fields.append("name")
    if payload.description is not None and payload.description != collection.description:
        collection.description = payload.description
        fields.append("description")
    if fields:
        db.flush()
        _audit(db, collection.id, "updated", actor, owner, fields=fields)
    return collection


def delete_collection(db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID) -> None:
    """Deletes a collection with its members and grants (the elements stay). The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    members = _count(db, ArchitectureCollectionMember, collection.id)
    grants = _count(db, ArchitectureCollectionGrant, collection.id)
    db.delete(collection)
    db.flush()
    _audit(db, collection.id, "deleted", actor, owner, members=members, grants=grants)


def _count(db: Session, model: Any, collection_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.collection_id == collection_id)) or 0


# --- Members ----------------------------------------------------------------


def add_members(
    db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID, element_ids: Sequence[uuid.UUID],
) -> int:
    """Adds the owner's elements to a collection (those already in it are skipped). The caller commits.

    Returns:
        How many were added.

    Raises:
        RuleError: 404 if the collection is absent; 400 if an element is not one of the owner's.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    wanted = set(element_ids)
    owned = set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.id.in_(wanted), owner.element_filter)))
    if owned != wanted:
        raise RuleError("A collection can hold only its own owner's elements.", 400)
    present = set(db.scalars(select(ArchitectureCollectionMember.element_id).where(
        ArchitectureCollectionMember.collection_id == collection.id,
    )))
    added = wanted - present
    for element_id in sorted(added):
        db.add(ArchitectureCollectionMember(collection_id=collection.id, element_id=element_id))
    db.flush()
    if added:
        _audit(db, collection.id, "members_added", actor, owner, added=len(added))
    return len(added)


def remove_member(db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID, element_id: uuid.UUID) -> None:
    """Takes an element out of a collection. The caller commits.

    Raises:
        RuleError: 404 if the collection is absent or the element is not in it.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    member = db.scalar(select(ArchitectureCollectionMember).where(
        ArchitectureCollectionMember.collection_id == collection.id, ArchitectureCollectionMember.element_id == element_id,
    ))
    if member is None:
        raise RuleError("That element is not in the collection.", 404)
    db.delete(member)
    db.flush()
    _audit(db, collection.id, "member_removed", actor, owner, element_id=str(element_id))


def member_outs(db: Session, collection_id: uuid.UUID) -> list[CollectionMemberOut]:
    """The collection's members (the tops of the shared subtrees) ordered by code."""
    rows = db.execute(
        select(ArchitectureElement.id, ArchitectureElement.unique_code, ArchitectureElement.name)
        .join(ArchitectureCollectionMember, ArchitectureCollectionMember.element_id == ArchitectureElement.id)
        .where(ArchitectureCollectionMember.collection_id == collection_id).order_by(ArchitectureElement.unique_code)
    ).all()
    return [CollectionMemberOut(element_id=r[0], unique_code=r[1], name=r[2]) for r in rows]


# --- Grants -----------------------------------------------------------------


def _check_grant_target(db: Session, owner: ElementOwner, payload: CollectionGrantCreate) -> dict[str, Any]:
    """Validates the grant's target and returns the columns that record it.

    Raises:
        RuleError: 400 unless exactly one target is given, in the owner's organisation (and not the owning project
            itself, which already sees its own elements); 400 for an organisation-owned collection granted to a
            project group.
    """
    if (payload.project_id is None) == (payload.group is None):
        raise RuleError("Name either a project or a group to grant access to.", 400)
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.organization_id != owner.organization_id:
            raise RuleError("That project is not in this organisation.", 400)
        if owner.project_id == project.id:
            raise RuleError("A collection is always visible to the project that owns it.", 400)
        return {"project_id": project.id, "include_descendants": payload.include_descendants}
    group = payload.group
    assert group is not None
    if payload.include_descendants:
        raise RuleError("Including descendants applies to a project grant only.", 400)
    if group.type is PrincipalType.USER:
        raise RuleError("Access is granted to a project or a group, not a person.", 400)
    if group.type is PrincipalType.PROJECT_GROUP:
        project_group = db.get(ProjectGroup, group.id)
        project = db.get(Project, project_group.project_id) if project_group is not None else None
        if project is None or project.organization_id != owner.organization_id:
            raise RuleError("That group is not in this organisation.", 400)
    else:
        from fastapi import HTTPException

        try:
            validate_principal(db, group, organization_id=owner.organization_id, field="group")
        except HTTPException as exc:
            raise RuleError("That group is not in this organisation.", 400) from exc
    return {"group_type": group.type.value, "group_id": group.id, "include_descendants": False}


def add_grant(
    db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID, payload: CollectionGrantCreate,
) -> ArchitectureCollectionGrant:
    """Grants a project or a group access to a collection. The caller commits.

    Raises:
        RuleError: 404 if the collection is absent; 400 for an invalid target; 409 if the target already has a grant.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    columns = _check_grant_target(db, owner, payload)
    existing = select(ArchitectureCollectionGrant.id).where(ArchitectureCollectionGrant.collection_id == collection.id)
    if "project_id" in columns:
        existing = existing.where(ArchitectureCollectionGrant.project_id == columns["project_id"])
    else:
        existing = existing.where(
            ArchitectureCollectionGrant.group_type == columns["group_type"], ArchitectureCollectionGrant.group_id == columns["group_id"],
        )
    if db.scalar(existing.limit(1)) is not None:
        raise RuleError("That target already has access to the collection.", 409)
    grant = ArchitectureCollectionGrant(collection_id=collection.id, created_by=actor.id, **columns)
    db.add(grant)
    db.flush()
    _audit(
        db, collection.id, "grant_added", actor, owner, grant_id=str(grant.id),
        target="project" if grant.project_id is not None else grant.group_type,
        target_id=str(grant.project_id or grant.group_id), include_descendants=grant.include_descendants or None,
    )
    return grant


def revoke_grant(db: Session, owner: ElementOwner, actor: User, collection_id: uuid.UUID, grant_id: uuid.UUID) -> None:
    """Revokes a grant; the access it gave ends at once. The caller commits.

    Raises:
        RuleError: 404 if the collection or the grant is absent.
    """
    collection = get_collection(db, owner, collection_id, lock=True)
    grant = db.scalar(select(ArchitectureCollectionGrant).where(
        ArchitectureCollectionGrant.id == grant_id, ArchitectureCollectionGrant.collection_id == collection.id,
    ))
    if grant is None:
        raise RuleError("Grant not found.", 404)
    target = "project" if grant.project_id is not None else grant.group_type
    target_id = str(grant.project_id or grant.group_id)
    db.delete(grant)
    db.flush()
    _audit(db, collection.id, "grant_revoked", actor, owner, grant_id=str(grant_id), target=target, target_id=target_id)


def grant_outs(db: Session, collection_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[CollectionGrantOut]]:
    """`{collection id: its grants}` with the target's name, in a fixed number of queries."""
    found: dict[uuid.UUID, list[CollectionGrantOut]] = {c: [] for c in collection_ids}
    if not collection_ids:
        return found
    grants = list(db.scalars(
        select(ArchitectureCollectionGrant).where(ArchitectureCollectionGrant.collection_id.in_(collection_ids))
        .order_by(ArchitectureCollectionGrant.created_at)
    ))
    projects = {
        p.id: p for p in db.scalars(select(Project).where(Project.id.in_({g.project_id for g in grants if g.project_id})))
    } if any(g.project_id for g in grants) else {}
    labels = principal_labels(
        db, [PrincipalRef(type=PrincipalType(g.group_type), id=g.group_id) for g in grants if g.group_id and g.group_type],
    )
    for g in grants:
        group = None
        if g.group_id is not None and g.group_type is not None:
            group = label_of(labels, g.group_type, g.group_id)
        found[g.collection_id].append(CollectionGrantOut(
            id=g.id, project_id=g.project_id, project_name=projects[g.project_id].name if g.project_id else None,
            project_code=projects[g.project_id].code if g.project_id else None, group=group,
            include_descendants=g.include_descendants, created_at=g.created_at,
        ))
    return found


def collection_outs(db: Session, collections: Sequence[ArchitectureCollection], *, with_grants: bool) -> list[CollectionOut]:
    """API shapes for `collections`: counts, and (for a reader allowed to see them) grants, in bulk."""
    ids = [c.id for c in collections]
    members = dict(db.execute(
        select(ArchitectureCollectionMember.collection_id, func.count())
        .where(ArchitectureCollectionMember.collection_id.in_(ids)).group_by(ArchitectureCollectionMember.collection_id)
    ).tuples().all()) if ids else {}
    grants = grant_outs(db, ids) if with_grants else {}
    counts = dict(db.execute(
        select(ArchitectureCollectionGrant.collection_id, func.count())
        .where(ArchitectureCollectionGrant.collection_id.in_(ids)).group_by(ArchitectureCollectionGrant.collection_id)
    ).tuples().all()) if ids else {}
    return [
        CollectionOut(
            id=c.id, project_id=c.project_id, organization_id=c.organization_id, name=c.name, description=c.description,
            member_count=members.get(c.id, 0), grant_count=counts.get(c.id, 0), grants=grants.get(c.id, []),
            created_at=c.created_at, updated_at=c.updated_at,
        )
        for c in collections
    ]


def list_collections(db: Session, owner: ElementOwner) -> list[ArchitectureCollection]:
    """The owner's collections ordered by name."""
    return list(db.scalars(select(ArchitectureCollection).where(_owner_filter(owner)).order_by(ArchitectureCollection.name)))
