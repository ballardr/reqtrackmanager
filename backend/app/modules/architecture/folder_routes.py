"""
Module: modules.architecture.folder_routes

The endpoints for folders, added to the project router (`add_project_folder_routes`) and the organisation router
(`add_org_folder_routes`). Each kind has its own routes (`/element-folders`, `/connection-folders`, `/diagram-folders`,
`/symbol-folders`) so the matching sub-component and manage permission gate it.

Responsibilities:
- Declare the routes and translate `records.RuleError` to its HTTP status.

RBAC: a project's folders of a kind are readable by its members with that kind's sub-component enabled and changed by
the project `architect` (the kind's manage permission); symbol folders belong to the symbol library, so the Types and
symbols sub-component gates them and `architecture_admin` changes them. The organisation's element and symbol folders
are read and changed by `architecture_org_admin`; another member sees only the path to an element or symbol they may
read, in the record itself. Every
lookup is scoped to the owner in the URL, so another owner's folder ids look absent.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.architecture import folders
from app.modules.architecture._shared import (
    CONNECTION_MANAGE_PERMISSION,
    DIAGRAM_MANAGE_PERMISSION,
    ELEMENT_MANAGE_PERMISSION,
    require_architect,
    require_architecture_admin,
    require_architecture_org_admin,
)
from app.modules.architecture.enums import FolderKind
from app.modules.architecture.record_routes import as_http
from app.modules.architecture.records import ElementOwner
from app.modules.architecture.schemas import FolderCreate, FolderMove, FolderMoveOut, FolderOut, FolderUpdate
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_SUBCOMPONENT_KEY,
    TYPE_SUBCOMPONENT_KEY,
)
from app.services.lookups import project_or_404
from app.services.rbac import require_org_subcomponent_enabled, require_project_subcomponent_enabled

#: Each kind's sub-component and the permission that manages it in a project (`None`: the symbol library's
#: `architecture_admin` role, which also manages the project's types).
_KINDS: dict[FolderKind, tuple[str, str | None]] = {
    FolderKind.ELEMENT: (ELEMENT_SUBCOMPONENT_KEY, ELEMENT_MANAGE_PERMISSION),
    FolderKind.CONNECTION: (CONNECTION_SUBCOMPONENT_KEY, CONNECTION_MANAGE_PERMISSION),
    FolderKind.DIAGRAM: (DIAGRAM_SUBCOMPONENT_KEY, DIAGRAM_MANAGE_PERMISSION),
    FolderKind.SYMBOL: (TYPE_SUBCOMPONENT_KEY, None),
}

#: The kinds of the organisation's own folders, with the sub-component that gates each.
_ORG_KINDS: dict[FolderKind, str] = {FolderKind.ELEMENT: ELEMENT_SUBCOMPONENT_KEY, FolderKind.SYMBOL: TYPE_SUBCOMPONENT_KEY}


def add_project_folder_routes(router: APIRouter) -> None:
    """Adds the folder routes of a project's elements, connections, diagrams and symbols to `router` (the project router)."""
    for kind, (subcomponent, permission) in _KINDS.items():
        _add_project_kind(router, kind, require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, subcomponent), permission)


def _add_project_kind(router: APIRouter, kind: FolderKind, view, permission: str | None) -> None:
    base = f"/{kind.value}-folders"

    def owner_for_write(db: Session, user: User, project_id: uuid.UUID) -> ElementOwner:
        project = project_or_404(db, project_id)
        if permission is None:
            require_architecture_admin(db, user, project)
        else:
            require_architect(db, user, project, permission)
        return ElementOwner.of_project(project)

    def out(db: Session, owner: ElementOwner, folder_id: uuid.UUID) -> FolderOut:
        return folders.folder_outs(db, owner, [folders.get_folder(db, owner, folder_id, kind=kind.value)])[0]

    @router.get(base, response_model=list[FolderOut], name=f"list_project_{kind.value}_folders")
    def list_folders(project_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The project's folders of this kind with their paths and the number of records directly in each."""
        owner = ElementOwner.of_project(project_or_404(db, project_id))
        return folders.folder_outs(db, owner, folders.list_folders(db, owner, kind.value))

    @router.post(base, response_model=FolderOut, status_code=status.HTTP_201_CREATED, name=f"create_project_{kind.value}_folder")
    def create_folder(
        project_id: uuid.UUID, payload: FolderCreate, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Creates a folder. Needs the Architect role."""
        owner = owner_for_write(db, current_user, project_id)
        folder = as_http(lambda: folders.create_folder(db, owner, current_user, kind, payload))
        db.commit()
        return out(db, owner, folder.id)

    @router.put(f"{base}/{{folder_id}}", response_model=FolderOut, name=f"update_project_{kind.value}_folder")
    def update_folder(
        project_id: uuid.UUID, folder_id: uuid.UUID, payload: FolderUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Renames, moves or reorders a folder."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: folders.get_folder(db, owner, folder_id, kind=kind.value))
        as_http(lambda: folders.update_folder(db, owner, current_user, folder_id, payload))
        db.commit()
        return out(db, owner, folder_id)

    @router.delete(f"{base}/{{folder_id}}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_project_{kind.value}_folder")
    def delete_folder(
        project_id: uuid.UUID, folder_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Deletes a folder; its records and sub-folders move to its parent."""
        owner = owner_for_write(db, current_user, project_id)
        as_http(lambda: folders.get_folder(db, owner, folder_id, kind=kind.value))
        as_http(lambda: folders.delete_folder(db, owner, current_user, folder_id))
        db.commit()

    @router.post(f"{base}/move-records", response_model=FolderMoveOut, name=f"move_project_{kind.value}_records")
    def move_records(
        project_id: uuid.UUID, payload: FolderMove, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Puts records in a folder (`null` for the top level)."""
        owner = owner_for_write(db, current_user, project_id)
        moved = as_http(lambda: folders.move_records(db, owner, current_user, kind, payload.record_ids, payload.folder_id))
        db.commit()
        return FolderMoveOut(moved=moved)


def add_org_folder_routes(router: APIRouter) -> None:
    """Adds the folder routes of the organisation's own elements and symbols to `router` (the organisation router)."""
    for kind, subcomponent in _ORG_KINDS.items():
        _add_org_kind(router, kind, require_org_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, subcomponent))


def _add_org_kind(router: APIRouter, kind: FolderKind, view) -> None:
    base = f"/{kind.value}-folders"

    def owner_for(db: Session, user: User, organization_id: uuid.UUID) -> ElementOwner:
        require_architecture_org_admin(db, user, organization_id=organization_id)
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
        return ElementOwner.of_organization(organization)

    def out(db: Session, owner: ElementOwner, folder_id: uuid.UUID) -> FolderOut:
        return folders.folder_outs(db, owner, [folders.get_folder(db, owner, folder_id, kind=kind.value)])[0]

    @router.get(base, response_model=list[FolderOut], name=f"list_org_{kind.value}_folders")
    def list_folders(organization_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The organisation's folders of this kind with their paths and the number of records directly in each."""
        owner = owner_for(db, current_user, organization_id)
        return folders.folder_outs(db, owner, folders.list_folders(db, owner, kind.value))

    @router.post(base, response_model=FolderOut, status_code=status.HTTP_201_CREATED, name=f"create_org_{kind.value}_folder")
    def create_folder(
        organization_id: uuid.UUID, payload: FolderCreate, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Creates a folder."""
        owner = owner_for(db, current_user, organization_id)
        folder = as_http(lambda: folders.create_folder(db, owner, current_user, kind, payload))
        db.commit()
        return out(db, owner, folder.id)

    @router.put(f"{base}/{{folder_id}}", response_model=FolderOut, name=f"update_org_{kind.value}_folder")
    def update_folder(
        organization_id: uuid.UUID, folder_id: uuid.UUID, payload: FolderUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Renames, moves or reorders a folder."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: folders.get_folder(db, owner, folder_id, kind=kind.value))
        as_http(lambda: folders.update_folder(db, owner, current_user, folder_id, payload))
        db.commit()
        return out(db, owner, folder_id)

    @router.delete(f"{base}/{{folder_id}}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_org_{kind.value}_folder")
    def delete_folder(
        organization_id: uuid.UUID, folder_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Deletes a folder; its records and sub-folders move to its parent."""
        owner = owner_for(db, current_user, organization_id)
        as_http(lambda: folders.get_folder(db, owner, folder_id, kind=kind.value))
        as_http(lambda: folders.delete_folder(db, owner, current_user, folder_id))
        db.commit()

    @router.post(f"{base}/move-records", response_model=FolderMoveOut, name=f"move_org_{kind.value}_records")
    def move_records(
        organization_id: uuid.UUID, payload: FolderMove, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Puts records in a folder (`null` for the top level)."""
        owner = owner_for(db, current_user, organization_id)
        moved = as_http(lambda: folders.move_records(db, owner, current_user, kind, payload.record_ids, payload.folder_id))
        db.commit()
        return FolderMoveOut(moved=moved)
