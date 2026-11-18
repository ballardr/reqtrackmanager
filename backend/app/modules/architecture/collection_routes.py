"""
Module: modules.architecture.collection_routes

The endpoints for collections, their members and their grants, added to the project router
(`add_project_collection_routes`) and the organisation router (`add_org_collection_routes`).

Responsibilities:
- Declare the routes and translate `records.RuleError` to its HTTP status.

RBAC: a project's collections are readable by its members (with the `architecture_element` sub-component enabled)
and changed by the project `architect`; an organisation's collections are read and changed by
`architecture_org_admin` only, since a grant publishes organisation-owned elements. Every lookup is scoped to the
owner in the URL, so another owner's collection ids look absent.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.architecture import collections
from app.modules.architecture._shared import ELEMENT_MANAGE_PERMISSION, require_architect, require_architecture_org_admin
from app.modules.architecture.record_routes import as_http
from app.modules.architecture.records import ElementOwner
from app.modules.architecture.schemas import (
    CollectionCreate,
    CollectionGrantCreate,
    CollectionGrantOut,
    CollectionMemberOut,
    CollectionMembersAdd,
    CollectionOut,
    CollectionUpdate,
)
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY
from app.services.lookups import project_or_404
from app.services.rbac import require_org_subcomponent_enabled, require_project_subcomponent_enabled


def add_project_collection_routes(router: APIRouter) -> None:
    """Adds the collection routes of a project's own elements to `router` (the project router)."""
    view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)

    def owner_for_write(db: Session, user: User, project_id: uuid.UUID) -> ElementOwner:
        project = project_or_404(db, project_id)
        require_architect(db, user, project, ELEMENT_MANAGE_PERMISSION)
        return ElementOwner.of_project(project)

    def out(db: Session, owner: ElementOwner, collection_id: uuid.UUID) -> CollectionOut:
        return collections.collection_outs(db, [collections.get_collection(db, owner, collection_id)], with_grants=True)[0]

    @router.get("/collections", response_model=list[CollectionOut])
    def list_collections(project_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The project's collections with their members' count and who they are shared with."""
        owner = ElementOwner.of_project(project_or_404(db, project_id))
        return collections.collection_outs(db, collections.list_collections(db, owner), with_grants=True)

    @router.post("/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
    def create_collection(
        project_id: uuid.UUID, payload: CollectionCreate, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Creates an empty collection. Needs the Architect role."""
        owner = owner_for_write(db, current_user, project_id)
        collection = as_http(lambda: collections.create_collection(db, owner, current_user, payload))
        db.commit()
        return out(db, owner, collection.id)

    @router.get("/collections/{collection_id}", response_model=CollectionOut)
    def get_collection(
        project_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """One collection."""
        owner = ElementOwner.of_project(project_or_404(db, project_id))
        return as_http(lambda: out(db, owner, collection_id))

    @router.put("/collections/{collection_id}", response_model=CollectionOut)
    def update_collection(
        project_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Renames or re-describes a collection."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: collections.update_collection(db, owner, current_user, collection_id, payload))
        db.commit()
        return out(db, owner, collection_id)

    @router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_collection(
        project_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Deletes a collection with its members and grants; the elements stay."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: collections.delete_collection(db, owner, current_user, collection_id))
        db.commit()

    @router.get("/collections/{collection_id}/members", response_model=list[CollectionMemberOut])
    def list_members(
        project_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The elements in a collection."""
        owner = ElementOwner.of_project(project_or_404(db, project_id))
        as_http(lambda: collections.get_collection(db, owner, collection_id))
        return collections.member_outs(db, collection_id)

    @router.post("/collections/{collection_id}/members", response_model=list[CollectionMemberOut])
    def add_members(
        project_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionMembersAdd,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Adds the project's elements to a collection (each shares its whole subtree)."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: collections.add_members(db, owner, current_user, collection_id, payload.element_ids))
        db.commit()
        return collections.member_outs(db, collection_id)

    @router.delete("/collections/{collection_id}/members/{element_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_member(
        project_id: uuid.UUID, collection_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Takes an element out of a collection."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: collections.remove_member(db, owner, current_user, collection_id, element_id))
        db.commit()

    @router.post("/collections/{collection_id}/grants", response_model=CollectionGrantOut, status_code=status.HTTP_201_CREATED)
    def add_grant(
        project_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionGrantCreate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Shares a collection with a project (optionally with its descendants) or a group of the organisation."""
        owner = owner_for_write(db, current_user, project_id)
        grant = as_http(lambda: collections.add_grant(db, owner, current_user, collection_id, payload))
        db.commit()
        return next(g for g in collections.grant_outs(db, [collection_id])[collection_id] if g.id == grant.id)

    @router.delete("/collections/{collection_id}/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_grant(
        project_id: uuid.UUID, collection_id: uuid.UUID, grant_id: uuid.UUID,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Revokes a grant; the access it gave ends at once."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: collections.revoke_grant(db, owner, current_user, collection_id, grant_id))
        db.commit()


def add_org_collection_routes(router: APIRouter) -> None:
    """Adds the collection routes of the organisation's own elements to `router` (the organisation router)."""
    view = require_org_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)

    def owner_for(db: Session, user: User, organization_id: uuid.UUID) -> ElementOwner:
        require_architecture_org_admin(db, user, organization_id=organization_id)
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
        return ElementOwner.of_organization(organization)

    def out(db: Session, owner: ElementOwner, collection_id: uuid.UUID) -> CollectionOut:
        return collections.collection_outs(db, [collections.get_collection(db, owner, collection_id)], with_grants=True)[0]

    @router.get("/collections", response_model=list[CollectionOut])
    def list_collections(organization_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The organisation's collections with their members' count and who they are shared with."""
        owner = owner_for(db, current_user, organization_id)
        return collections.collection_outs(db, collections.list_collections(db, owner), with_grants=True)

    @router.post("/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
    def create_collection(
        organization_id: uuid.UUID, payload: CollectionCreate, current_user: User = Depends(view),
        db: Session = Depends(get_db),
    ):
        """Creates an empty collection of organisation-owned elements."""
        owner = owner_for(db, current_user, organization_id)
        collection = as_http(lambda: collections.create_collection(db, owner, current_user, payload))
        db.commit()
        return out(db, owner, collection.id)

    @router.get("/collections/{collection_id}", response_model=CollectionOut)
    def get_collection(
        organization_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view),
        db: Session = Depends(get_db),
    ):
        """One collection."""
        owner = owner_for(db, current_user, organization_id)
        return as_http(lambda: out(db, owner, collection_id))

    @router.put("/collections/{collection_id}", response_model=CollectionOut)
    def update_collection(
        organization_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Renames or re-describes a collection."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.update_collection(db, owner, current_user, collection_id, payload))
        db.commit()
        return out(db, owner, collection_id)

    @router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_collection(
        organization_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view),
        db: Session = Depends(get_db),
    ):
        """Deletes a collection with its members and grants; the elements stay."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.delete_collection(db, owner, current_user, collection_id))
        db.commit()

    @router.get("/collections/{collection_id}/members", response_model=list[CollectionMemberOut])
    def list_members(
        organization_id: uuid.UUID, collection_id: uuid.UUID, current_user: User = Depends(view),
        db: Session = Depends(get_db),
    ):
        """The elements in a collection."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.get_collection(db, owner, collection_id))
        return collections.member_outs(db, collection_id)

    @router.post("/collections/{collection_id}/members", response_model=list[CollectionMemberOut])
    def add_members(
        organization_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionMembersAdd,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Adds organisation-owned elements to a collection (each shares its whole subtree)."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.add_members(db, owner, current_user, collection_id, payload.element_ids))
        db.commit()
        return collections.member_outs(db, collection_id)

    @router.delete("/collections/{collection_id}/members/{element_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_member(
        organization_id: uuid.UUID, collection_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Takes an element out of a collection."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.remove_member(db, owner, current_user, collection_id, element_id))
        db.commit()

    @router.post("/collections/{collection_id}/grants", response_model=CollectionGrantOut, status_code=status.HTTP_201_CREATED)
    def add_grant(
        organization_id: uuid.UUID, collection_id: uuid.UUID, payload: CollectionGrantCreate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Shares a collection with a project (optionally with its descendants) or an organisation group."""
        owner = owner_for(db, current_user, organization_id)
        grant = as_http(lambda: collections.add_grant(db, owner, current_user, collection_id, payload))
        db.commit()
        return next(g for g in collections.grant_outs(db, [collection_id])[collection_id] if g.id == grant.id)

    @router.delete("/collections/{collection_id}/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_grant(
        organization_id: uuid.UUID, collection_id: uuid.UUID, grant_id: uuid.UUID,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Revokes a grant; the access it gave ends at once."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: collections.revoke_grant(db, owner, current_user, collection_id, grant_id))
        db.commit()
