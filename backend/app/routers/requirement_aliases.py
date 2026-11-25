"""
Module: routers.requirement_aliases

The requirement alias API: a requirement placed in further components and categories, each with a code of its own
(`services.requirement_aliases`), and the setting that allows new aliases.

Responsibilities:
- Project setting: read the effective value and its source with the alias count, and set the project's own value
  (`require_project_manage`).
- Organisation setting: read it (any member) and set it (organisation administrator).
- Per requirement: set the further places (the authority to tag a requirement, as for any placement), retire an alias,
  promote an alias to the primary place, and make an alias independent (a requirement editor).
- In bulk: make many aliases independent, so a project can move to one code per record on purpose.

Design decisions:
- Changing places is metadata like a tag and so ignores an approved requirement's lock; promoting moves the primary
  place and make independent creates a record, so both need the editing roles, and promoting follows the lock.
- A requirement the caller cannot open is a 404. The setting only stops new aliases; no endpoint removes existing
  ones because of it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement_alias import RequirementAlias
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project, _require_edit_role, _to_out
from app.schemas.requirement import RequirementOut
from app.schemas.requirement_alias import (
    AliasModeSet,
    AliasPlacesSet,
    AliasSettingsOut,
    IndependentFailureOut,
    IndependentOut,
    MakeIndependentBulkIn,
    MakeIndependentBulkOut,
    MakeIndependentIn,
    OrgAliasSettingsOut,
    SkippedItemOut,
)
from app.services import pubsub
from app.services import requirement_aliases as alias_service
from app.services.link_graph import ArtefactResolver
from app.services.lookups import project_or_404
from app.services.placements import PlacementPair
from app.services.rbac import require_org_role, require_project_manage, require_project_view
from app.services.requirements import get_current_version
from app.services.tags import can_tag

project_router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["requirement-aliases"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/requirement-aliases", tags=["requirement-aliases"])

#: Most aliases one `all_aliases` request makes independent (the caller repeats until none remain).
BULK_BATCH = 100
_ANY_ORG_ROLE = (OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)
_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _settings_out(db: Session, project: Project) -> AliasSettingsOut:
    """The project's effective setting, its own value and the alias count."""
    resolved = alias_service.resolve_mode(db, project)
    organisation = db.get(Organization, project.organization_id)
    return AliasSettingsOut(
        mode=resolved.mode, source=resolved.source, own_mode=project.requirement_aliases,
        organization_mode=organisation.requirement_aliases if organisation else alias_service.MODE_ALLOWED,
        has_parent=project.parent_project_id is not None, alias_count=alias_service.alias_count(db, project.id),
    )


def _require_place_authority(db: Session, project: Project, user: User) -> None:
    """Raises 403 unless the user may place requirements (the authority to tag them)."""
    if not can_tag(ArtefactResolver(db, project, user.id), "requirement"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to place this requirement.")


def _independent_out(result: alias_service.IndependentResult) -> IndependentOut:
    """The response for one made-independent alias."""
    return IndependentOut(
        requirement_id=result.requirement.id, unique_code=result.requirement.unique_code, original_id=result.original_id,
        links_copied=result.links_copied, comments_copied=result.comments_copied,
        attachments_copied=result.attachments_copied, tags_copied=result.tags_copied,
        related_link_made=result.related_link_made,
        skipped=[SkippedItemOut(kind=s.kind, label=s.label, reason=s.reason) for s in result.skipped],
    )


# --- the setting ------------------------------------------------------------------------------


@project_router.get("/requirement-aliases", response_model=AliasSettingsOut)
def get_project_alias_settings(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> AliasSettingsOut:
    """The project's effective alias setting, where it came from, and how many aliases it holds."""
    return _settings_out(db, project_or_404(db, project_id))


@project_router.put("/requirement-aliases", response_model=AliasSettingsOut)
def set_project_alias_mode(
    project_id: UUID, body: AliasModeSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> AliasSettingsOut:
    """Sets the project's own value (`null` follows the nearest ancestor project, else the organisation)."""
    alias_service.set_mode(db, project=project, organization=None, actor_id=current_user.id, mode=body.mode)
    db.commit()
    return _settings_out(db, project)


@org_router.get("", response_model=OrgAliasSettingsOut)
def get_org_alias_settings(
    organization_id: UUID, current_user: User = Depends(require_org_role(*_ANY_ORG_ROLE)), db: Session = Depends(get_db),
) -> OrgAliasSettingsOut:
    """The organisation's alias setting, the default for projects that do not set their own."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgAliasSettingsOut(mode=org.requirement_aliases)


@org_router.put("", response_model=OrgAliasSettingsOut)
def set_org_alias_mode(
    organization_id: UUID, body: AliasModeSet, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OrgAliasSettingsOut:
    """Sets the organisation's value (Allowed or Disabled)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    alias_service.set_mode(db, project=None, organization=org, actor_id=current_user.id, mode=body.mode)
    db.commit()
    return OrgAliasSettingsOut(mode=org.requirement_aliases)


# --- a requirement's aliases ------------------------------------------------------------------


@project_router.put("/requirements/{requirement_id}/aliases", response_model=RequirementOut)
def set_requirement_aliases(
    project_id: UUID, requirement_id: UUID, body: AliasPlacesSet,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RequirementOut:
    """Makes the requirement sit in exactly its own place plus `places`.

    A place already held keeps its code; one no longer listed is retired (its code keeps resolving); a new one gets
    a fresh code and needs the project's setting to be Allowed (409 otherwise)."""
    project = project_or_404(db, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    _require_place_authority(db, project, current_user)
    alias_service.set_aliases(
        db, project=project, requirement=requirement, actor_id=current_user.id,
        pairs=[PlacementPair(p.component_id, p.category_id) for p in body.places],
    )
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "updated", "id": str(requirement.id)})
    return _to_out(db, requirement, get_current_version(db, requirement.id), current_user.id)


@project_router.delete("/requirements/{requirement_id}/aliases/{alias_id}", response_model=RequirementOut)
def retire_requirement_alias(
    project_id: UUID, requirement_id: UUID, alias_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RequirementOut:
    """Takes the requirement out of the alias's place. The code is retired, never reused, and still resolves."""
    project = project_or_404(db, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    _require_place_authority(db, project, current_user)
    alias = alias_service.get_alias(db, project_id, requirement_id, alias_id)
    alias_service.retire_alias(db, project, requirement, alias, current_user.id)
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "updated", "id": str(requirement.id)})
    return _to_out(db, requirement, get_current_version(db, requirement.id), current_user.id)


@project_router.post("/requirements/{requirement_id}/aliases/{alias_id}/promote", response_model=RequirementOut)
def promote_requirement_alias(
    project_id: UUID, requirement_id: UUID, alias_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RequirementOut:
    """Makes the alias's place the requirement's own, swapping the two places and their codes (409 when approved)."""
    _require_edit_role(db, current_user, project_id)
    project = project_or_404(db, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    alias = alias_service.get_alias(db, project_id, requirement_id, alias_id)
    alias_service.promote_alias(db, project, requirement, alias, current_user.id)
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "updated", "id": str(requirement.id)})
    return _to_out(db, requirement, get_current_version(db, requirement.id), current_user.id)


@project_router.post("/requirements/{requirement_id}/aliases/{alias_id}/make-independent", response_model=IndependentOut)
def make_alias_independent(
    project_id: UUID, requirement_id: UUID, alias_id: UUID, body: MakeIndependentIn,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> IndependentOut:
    """Turns the alias into a requirement of its own: a new draft holding the alias code and the original's content,
    links, comments, tags and attachments (what could not be copied is listed). It cannot be undone."""
    _require_edit_role(db, current_user, project_id)
    project = project_or_404(db, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    alias = alias_service.get_alias(db, project_id, requirement.id, alias_id)
    result = alias_service.make_independent(
        db, project=project, alias=alias, actor=current_user, related_link_type_id=body.related_link_type_id,
    )
    out = _independent_out(result)
    db.commit()
    pubsub.notify(project_id, {"type": "requirement", "action": "created", "id": str(result.requirement.id)})
    return out


@project_router.post("/requirement-aliases/make-independent", response_model=MakeIndependentBulkOut)
def make_aliases_independent(
    project_id: UUID, body: MakeIndependentBulkIn, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> MakeIndependentBulkOut:
    """Makes several of the project's aliases independent in one request; one that cannot be made is reported and
    the rest still are."""
    _require_edit_role(db, current_user, project_id)
    project = project_or_404(db, project_id)
    if not body.alias_ids and not body.all_aliases:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name the aliases, or ask for all of them.")
    wanted = list(dict.fromkeys(body.alias_ids))
    if body.all_aliases:
        wanted = [a.id for a in alias_service.project_aliases(db, project_id)[:BULK_BATCH]]
    aliases = {
        a.id: a for a in db.scalars(select(RequirementAlias).where(
            RequirementAlias.project_id == project_id, RequirementAlias.id.in_(wanted),
            RequirementAlias.is_retired.is_(False),
        ))
    }
    made: list[IndependentOut] = []
    failed: list[IndependentFailureOut] = []
    for alias_id in wanted:
        alias = aliases.get(alias_id)
        if alias is None:
            failed.append(IndependentFailureOut(alias_id=alias_id, unique_code="", reason="Alias not found."))
            continue
        code = alias.unique_code
        try:
            with db.begin_nested():
                result = alias_service.make_independent(
                    db, project=project, alias=alias, actor=current_user, related_link_type_id=body.related_link_type_id,
                )
            made.append(_independent_out(result))
        except HTTPException as exc:
            failed.append(IndependentFailureOut(alias_id=alias_id, unique_code=code, reason=str(exc.detail)))
    db.commit()
    for item in made:
        pubsub.notify(project_id, {"type": "requirement", "action": "created", "id": str(item.requirement_id)})
    return MakeIndependentBulkOut(made=made, failed=failed)
