"""
Module: routers.orgs.service_users

An organisation administrator's management of service users and the personal access tokens issued to them.

Responsibilities:
- Create, list, read, change and reactivate service users (deactivate and archive reuse the ordinary organisation user
  endpoints, which apply to a service user unchanged).
- Issue, list and revoke a service user's tokens on its behalf; the secret is returned once and never stored or logged.

Design decisions:
- Every endpoint needs the organisation administrator role in the service user's own organisation, and answers 404 for
  an account that is not one of its service users, so another organisation's administrator learns nothing.
- Creating, changing, reactivating and issuing refuse a Personal Access Token (`refuse_personal_access_token`): a token
  that could mint or widen another credential would make its own scope and expiry only a suggestion.
- Token creation goes through `services.pats.create_token`, so the hash-only storage, scope rules, expiry ceiling and
  organisation lifetime cap are the same as for a person's own tokens; the issuer is recorded beside the owner.

Dependencies: `services.service_users`, `services.pats`, `services.principals`, `services.audit`, `services.rbac`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import refuse_personal_access_token
from app.models.enums import OrgRole
from app.models.organization import Organization, UserOrgRole
from app.models.pat import PersonalAccessToken
from app.models.project import Project
from app.models.service_user import ServiceUserProfile
from app.models.user import User
from app.schemas.pat import PersonalAccessTokenProjectRef
from app.schemas.service_user import (
    ServiceUserCreate,
    ServiceUserOut,
    ServiceUserTokenCreate,
    ServiceUserTokenCreateOut,
    ServiceUserTokenOut,
    ServiceUserUpdate,
)
from app.services import service_users
from app.services.audit import log_event
from app.services.pats import create_token, effective_expiry
from app.services.principals import principal_labels, principal_ref
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-service-users"])

_NO_PAT = [Depends(refuse_personal_access_token)]


def _outs(db: Session, rows: list[tuple[User, ServiceUserProfile]]) -> list[ServiceUserOut]:
    """Builds the responses for many service users with one query each for roles, tokens, names and labels."""
    if not rows:
        return []
    user_ids = [u.id for u, _ in rows]
    organization_id = rows[0][1].organization_id
    roles: dict[UUID, set[OrgRole]] = {}
    for user_id, role in db.execute(
        select(UserOrgRole.user_id, UserOrgRole.role).where(
            UserOrgRole.organization_id == organization_id, UserOrgRole.user_id.in_(user_ids)
        )
    ):
        roles.setdefault(user_id, set()).add(role)
    now = datetime.now(UTC)
    active: dict[UUID, int] = {}
    last_used: dict[UUID, datetime] = {}
    for pat in db.scalars(select(PersonalAccessToken).where(PersonalAccessToken.user_id.in_(user_ids))):
        if pat.last_used_at is not None and (pat.user_id not in last_used or pat.last_used_at > last_used[pat.user_id]):
            last_used[pat.user_id] = pat.last_used_at
        if pat.revoked_at is None and now < effective_expiry(db, pat):
            active[pat.user_id] = active.get(pat.user_id, 0) + 1
    creators = {
        i: n for i, n in db.execute(
            select(User.id, User.display_name).where(User.id.in_({p.created_by for _, p in rows if p.created_by}))
        )
    }
    labels = principal_labels(db, [principal_ref(p.responsible_type, p.responsible_id) for _, p in rows])
    out = []
    for user, profile in rows:
        ref = principal_ref(profile.responsible_type, profile.responsible_id)
        deliverable = service_users.can_receive_email(user)
        out.append(ServiceUserOut(
            user_id=user.id, name=user.display_name, description=profile.description,
            email=user.email if deliverable else None, has_deliverable_email=deliverable,
            is_active=user.is_active, is_archived=user.is_archived,
            responsible=labels[(ref.type.value, ref.id)] if ref else None,
            roles=sorted(roles.get(user.id, set()), key=lambda r: r.value),
            flags=service_users.access_flags(profile, roles.get(user.id, set())),
            active_token_count=active.get(user.id, 0), last_used_at=last_used.get(user.id),
            created_at=user.created_at, created_by_display_name=creators.get(profile.created_by) if profile.created_by else None,
        ))
    return out


def _token_out(db: Session, pat: PersonalAccessToken, creators: dict[UUID, str]) -> dict:
    projects = (
        db.scalars(select(Project).where(Project.id.in_([UUID(i) for i in pat.allowed_project_ids]))).all()
        if pat.allowed_project_ids else []
    )
    issuer = pat.created_by_user_id or pat.user_id
    return {
        "id": pat.id, "name": pat.name, "token_prefix": pat.token_prefix,
        "allowed_projects": [PersonalAccessTokenProjectRef(id=p.id, name=p.name) for p in projects],
        "expires_at": effective_expiry(db, pat), "revoked_at": pat.revoked_at, "last_used_at": pat.last_used_at,
        "created_at": pat.created_at, "created_by_display_name": creators.get(issuer),
    }


def _creator_names(db: Session, pats: list[PersonalAccessToken]) -> dict[UUID, str]:
    ids = {p.created_by_user_id or p.user_id for p in pats}
    return {i: n for i, n in db.execute(select(User.id, User.display_name).where(User.id.in_(ids)))} if ids else {}


def _require_issuable(user: User) -> None:
    """Raises 409 for a service user that cannot be issued a token (deactivated or archived)."""
    if not user.is_active or user.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reactivate this service user before issuing a token.")


@router.get("/{organization_id}/service-users", response_model=list[ServiceUserOut])
def list_service_users(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> list[ServiceUserOut]:
    """Lists the organisation's service users (archived ones only on request), by name."""
    query = (
        select(User, ServiceUserProfile).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id)
        .where(ServiceUserProfile.organization_id == organization_id)
        .order_by(func.lower(User.display_name))
    )
    if not include_archived:
        query = query.where(User.is_archived.is_(False))
    return _outs(db, [(u, p) for u, p in db.execute(query).all()])


@router.post(
    "/{organization_id}/service-users", response_model=ServiceUserOut, status_code=status.HTTP_201_CREATED,
    dependencies=_NO_PAT,
)
def create_service_user(
    organization_id: UUID, payload: ServiceUserCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ServiceUserOut:
    """Creates a service user: no password and no sign-in, the `member` role, and no token until one is issued.

    Raises:
        HTTPException: 400 for a blank name, an undeliverable address or an invalid responsible principal; 409 for
            a name or address already in use.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    user, profile = service_users.create_service_user(
        db, organization=organization, actor_id=current_user.id, name=payload.name, description=payload.description,
        email=payload.email, responsible=payload.responsible,
    )
    db.commit()
    return _outs(db, [(user, profile)])[0]


@router.get("/{organization_id}/service-users/{user_id}", response_model=ServiceUserOut)
def get_service_user(
    organization_id: UUID, user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ServiceUserOut:
    """One service user (404 for any other account)."""
    return _outs(db, [service_users.get_service_user(db, organization_id, user_id)])[0]


@router.patch("/{organization_id}/service-users/{user_id}", response_model=ServiceUserOut, dependencies=_NO_PAT)
def update_service_user(
    organization_id: UUID, user_id: UUID, payload: ServiceUserUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ServiceUserOut:
    """Changes the fields sent; an audit event names the fields changed, never their values."""
    user, profile = service_users.get_service_user(db, organization_id, user_id)
    service_users.update_service_user(
        db, user, profile, actor_id=current_user.id, fields=set(payload.model_fields_set),
        name=payload.name, description=payload.description, email=payload.email, responsible=payload.responsible,
    )
    db.commit()
    return _outs(db, [(user, profile)])[0]


@router.post(
    "/{organization_id}/service-users/{user_id}/reactivate", response_model=ServiceUserOut, dependencies=_NO_PAT,
)
def reactivate_service_user(
    organization_id: UUID, user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ServiceUserOut:
    """Reactivates a deactivated service user; tokens revoked earlier stay revoked."""
    user, profile = service_users.get_service_user(db, organization_id, user_id)
    service_users.reactivate(db, user, profile, actor_id=current_user.id)
    db.commit()
    return _outs(db, [(user, profile)])[0]


@router.get("/{organization_id}/service-users/{user_id}/pats", response_model=list[ServiceUserTokenOut])
def list_service_user_tokens(
    organization_id: UUID, user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> list[ServiceUserTokenOut]:
    """The service user's tokens, revoked ones included so the history stays visible; never a secret or hash."""
    service_users.get_service_user(db, organization_id, user_id)
    pats = list(db.scalars(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id).order_by(PersonalAccessToken.created_at.desc())
    ))
    creators = _creator_names(db, pats)
    return [ServiceUserTokenOut(**_token_out(db, p, creators)) for p in pats]


@router.post(
    "/{organization_id}/service-users/{user_id}/pats", response_model=ServiceUserTokenCreateOut,
    status_code=status.HTTP_201_CREATED, dependencies=_NO_PAT,
)
def issue_service_user_token(
    organization_id: UUID, user_id: UUID, payload: ServiceUserTokenCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ServiceUserTokenCreateOut:
    """Issues a token for the service user, scoped to this organisation (and optionally to projects of it).

    The secret is in this response only. The audit event names the issuer, the service user and the token, never
    the secret.

    Raises:
        HTTPException: 400 for a blank name or a project the service user cannot reach; 409 for a deactivated or
            archived service user.
    """
    user, _profile = service_users.get_service_user(db, organization_id, user_id)
    _require_issuable(user)
    pat, raw = create_token(
        db, owner=user, issuer=current_user, name=payload.name, organization_ids=[organization_id],
        project_ids=payload.allowed_project_ids, requested_expires_at=payload.requested_expires_at,
    )
    log_event(
        db, entity_type="personal_access_token", entity_id=pat.id, action="service_user_pat_issued",
        actor_id=current_user.id, organization_id=organization_id, detail={"service_user_id": str(user.id)},
    )
    db.commit()
    db.refresh(pat)
    return ServiceUserTokenCreateOut(**_token_out(db, pat, {current_user.id: current_user.display_name}), token=raw)


@router.delete(
    "/{organization_id}/service-users/{user_id}/pats/{pat_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_service_user_token(
    organization_id: UUID, user_id: UUID, pat_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> None:
    """Revokes one of the service user's tokens (idempotent). 404 for a token that is not this service user's."""
    service_users.get_service_user(db, organization_id, user_id)
    pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.id == pat_id, PersonalAccessToken.user_id == user_id))
    if pat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personal access token not found.")
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(UTC)
        log_event(
            db, entity_type="personal_access_token", entity_id=pat.id, action="service_user_pat_revoked",
            actor_id=current_user.id, organization_id=organization_id, detail={"service_user_id": str(user_id)},
        )
        db.commit()
