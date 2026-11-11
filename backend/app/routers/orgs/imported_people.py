"""
Module: routers.orgs.imported_people

The organisation administrator's view of its imported people (stand-ins created by a bundle import for people who are
not members, `services.imported_people`): list them with whether anything still refers to them, anonymise one, and
remove one nothing refers to. The retention age that decides which are offered for removal is the organisation's
`imported_person_retention_days` (set through the advanced settings). Nothing here deletes automatically.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.org import ImportedPeopleOut, ImportedPersonRowOut
from app.services import imported_people
from app.services.audit import log_event
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-imported-people"])


def _organization_or_404(db: Session, organization_id: UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _stand_in_or_404(db: Session, organization_id: UUID, user_id: UUID) -> User:
    """The organisation's own imported person; any other id (a member, another organisation's) is a 404."""
    user = db.get(User, user_id)
    if user is None or user.imported_organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Imported person not found.")
    return user


@router.get("/{organization_id}/imported-people", response_model=ImportedPeopleOut)
def list_imported_people(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
) -> ImportedPeopleOut:
    """Lists the organisation's imported people with whether each is still referred to and whether it is due for removal."""
    org = _organization_or_404(db, organization_id)
    rows = list(db.scalars(
        select(User).where(User.imported_organization_id == organization_id).order_by(User.display_name, User.created_at)
    ).all())
    used = imported_people.referenced_ids(db, [u.id for u in rows])
    due = {u.id for u in imported_people.unused_stand_ins(db, org)}
    return ImportedPeopleOut(
        retention_days=org.imported_person_retention_days,
        people=[
            ImportedPersonRowOut(
                id=u.id, display_name=u.display_name, created_at=u.created_at, in_use=u.id in used, due_for_removal=u.id in due,
            )
            for u in rows
        ],
    )


@router.post("/{organization_id}/imported-people/{user_id}/anonymise", status_code=status.HTTP_204_NO_CONTENT)
def anonymise_imported_person(
    organization_id: UUID, user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    """Renames an imported person "Former person"; the records and history that name them stay."""
    user = _stand_in_or_404(db, organization_id, user_id)
    imported_people.anonymise(db, user)
    log_event(
        db, entity_type="imported_person", entity_id=user.id, action="anonymised", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.delete("/{organization_id}/imported-people/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_imported_person(
    organization_id: UUID, user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    """Removes an imported person nothing refers to.

    Raises:
        HTTPException: 404 when the id is not one of this organisation's imported people; 409 when a record, history
            entry or field still refers to them (anonymise them instead).
    """
    user = _stand_in_or_404(db, organization_id, user_id)
    if imported_people.references(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This imported person is still named by records or history; anonymise them instead.")
    log_event(
        db, entity_type="imported_person", entity_id=user.id, action="removed", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.delete(user)
    db.commit()
