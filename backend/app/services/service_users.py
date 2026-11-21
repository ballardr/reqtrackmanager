"""
Module: services.service_users

Service users: an organisation's integration identity (an agent, a build job) that holds personal access tokens an
organisation administrator issues, instead of running as a named person.

Responsibilities:
- Create, change and reactivate a service user (`create_service_user`, `update_service_user`, `reactivate`), with the
  name unique within the organisation and the responsible principal validated.
- Answer the questions the rest of the product asks about one: is this account a service user, may it receive email
  (`can_receive_email`), what should the access review flag (`access_flags`).
- Hold the constants every sign-in path checks (`SERVICE_AUTH_BACKEND`).

Design decisions:
- A service user is an ordinary `User` row (`is_service_account`) with no password and an `auth_backend` no sign-in
  backend matches, so every picker, role grant, owner field, group, notification and audit actor works unchanged
  (users and groups on parity). The facts specific to it live in `ServiceUserProfile`.
- It belongs to one organisation, which `services.org_membership.external_account_refusal` enforces for every
  administrator-driven grant; a token it holds is always scoped to that organisation.
- Its address is optional. Left blank it takes a generated address on the reserved `.invalid` domain, which is never
  delivered to; a supplied address receives notifications only and never signs in or adopts an account (the SSO,
  SCIM and recovery paths skip service users).
- Callers authorise; this module raises `HTTPException` for what a request got wrong.

Dependencies: `models.user`, `models.service_user`, `services.principals`, `services.audit`, `services.rbac`.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.service_user import ServiceUserProfile
from app.models.user import User
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.principals import (
    principal_columns,
    principal_from_bundle,
    principal_ref,
    principal_to_bundle,
    validate_principal,
)

#: `User.auth_backend` of a service user. No sign-in backend is named this, so native sign-in, single sign-on matching
#: and every other lookup keyed on a backend name leave the account alone.
SERVICE_AUTH_BACKEND = "service"

#: The reserved top-level domain (RFC 2606) of a generated address: it can never be delivered to.
UNDELIVERABLE_TLD = ".invalid"

_GENERATED_DOMAIN = "service" + UNDELIVERABLE_TLD

#: What the access review flags on a service user.
ServiceUserFlag = Literal["no_responsible", "administrator"]

_ADMINISTRATOR_ROLES = {OrgRole.ORG_ADMIN}


def generated_address(user_id: uuid.UUID) -> str:
    """The non-deliverable address a service user takes when none is supplied (`svc-<id>@service.invalid`)."""
    return f"svc-{user_id}@{_GENERATED_DOMAIN}"


def can_receive_email(user: User) -> bool:
    """Whether email may be sent to `user`: false for an address on the reserved `.invalid` domain.

    One rule at the recipient, so every notification path (instant, digest) shares it instead of each type
    deciding.
    """
    return not user.email.lower().endswith(UNDELIVERABLE_TLD)


def clean_address(email: str | None) -> str | None:
    """A supplied address, lower-cased, or `None` when blank.

    Raises:
        HTTPException: 400 for an address on the reserved `.invalid` domain (it could never receive anything).
    """
    cleaned = (email or "").strip().lower()
    if not cleaned:
        return None
    if cleaned.endswith(UNDELIVERABLE_TLD):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter an address that can receive email, or leave it blank.")
    return cleaned


def profile_of(db: Session, user_id: uuid.UUID) -> ServiceUserProfile | None:
    """The profile of a service user, or `None` for an ordinary account."""
    return db.scalar(select(ServiceUserProfile).where(ServiceUserProfile.user_id == user_id))


def get_service_user(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> tuple[User, ServiceUserProfile]:
    """Loads a service user of one organisation.

    Args:
        db: Active session.
        organization_id: The organisation acted in.
        user_id: The account.

    Returns:
        The account and its profile.

    Raises:
        HTTPException: 404 when the account is not a service user of this organisation (an ordinary account and
            another organisation's service user read the same).
    """
    row = db.execute(
        select(User, ServiceUserProfile).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id).where(
            User.id == user_id, User.is_service_account.is_(True), ServiceUserProfile.organization_id == organization_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service user not found.")
    return row[0], row[1]


def _require_unused_name(db: Session, organization_id: uuid.UUID, name: str, *, except_user_id: uuid.UUID | None = None) -> None:
    """Rejects a name another service user of the organisation already has (case-insensitive).

    Raises:
        HTTPException: 409 when it is taken.
    """
    query = select(User.id).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id).where(
        ServiceUserProfile.organization_id == organization_id, func.lower(User.display_name) == name.lower(),
    )
    if except_user_id is not None:
        query = query.where(User.id != except_user_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A service user with this name already exists in this organisation.")


def _require_unused_address(db: Session, email: str, *, except_user_id: uuid.UUID | None = None) -> None:
    """Rejects an address another account already has.

    Raises:
        HTTPException: 409 when it is taken (the same message every account-creation path gives).
    """
    query = select(User.id).where(func.lower(User.email) == email)
    if except_user_id is not None:
        query = query.where(User.id != except_user_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")


def _check_responsible(db: Session, organization_id: uuid.UUID, ref: PrincipalRef | None, *, own_id: uuid.UUID | None) -> None:
    """Validates the responsible principal: a member or group of the organisation, and never the service user itself.

    Raises:
        HTTPException: 400 when it is not valid.
    """
    if ref is not None and own_id is not None and ref.id == own_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A service user cannot be responsible for itself.")
    validate_principal(db, ref, organization_id=organization_id, project_id=None, field="Responsible")


def create_service_user(
    db: Session, *, organization: Organization, actor_id: uuid.UUID, name: str, description: str,
    email: str | None, responsible: PrincipalRef | None,
) -> tuple[User, ServiceUserProfile]:
    """Creates a service user with the `member` role in `organization`.

    Args:
        db: Active session; the rows are added and flushed, not committed.
        organization: The one organisation it belongs to.
        actor_id: The administrator creating it (audit actor).
        name: Its display name; unique among the organisation's service users.
        description: What it is for.
        email: A deliverable address for notifications, or `None` for a generated one.
        responsible: The user or organisation group answerable for it, or `None`.

    Returns:
        The account and its profile.

    Raises:
        HTTPException: 400 blank name, an undeliverable address or an invalid responsible principal; 409 name or
            address already in use.
    """
    name = name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name is required.")
    db.execute(select(Organization.id).where(Organization.id == organization.id).with_for_update())
    _require_unused_name(db, organization.id, name)
    address = clean_address(email)
    if address is not None:
        _require_unused_address(db, address)
    _check_responsible(db, organization.id, responsible, own_id=None)

    user_id = uuid.uuid4()
    user = User(
        id=user_id, email=address or generated_address(user_id), display_name=name, password_hash=None,
        auth_backend=SERVICE_AUTH_BACKEND, is_service_account=True,
    )
    db.add(user)
    db.flush()
    db.add(UserOrgRole(user_id=user.id, organization_id=organization.id, role=OrgRole.MEMBER))
    profile = ServiceUserProfile(
        user_id=user.id, organization_id=organization.id, description=description.strip(), created_by=actor_id,
        **principal_columns("responsible", responsible),
    )
    db.add(profile)
    db.flush()
    log_event(
        db, entity_type="service_user", entity_id=user.id, action="created", actor_id=actor_id,
        organization_id=organization.id,
        detail={"has_responsible": responsible is not None, "has_email": address is not None},
    )
    return user, profile


def update_service_user(
    db: Session, user: User, profile: ServiceUserProfile, *, actor_id: uuid.UUID, fields: set[str],
    name: str | None, description: str | None, email: str | None, responsible: PrincipalRef | None,
) -> list[str]:
    """Changes the fields named in `fields` (those the request sent), leaving the others as they are.

    Args:
        db: Active session; changes are flushed, not committed.
        user / profile: The service user (from `get_service_user`).
        actor_id: The administrator acting.
        fields: Which of `name`, `description`, `email` and `responsible` the request carried; a sent `email` of
            `None` returns the account to a generated address, and a sent `responsible` of `None` clears it.
        name / description / email / responsible: The new values.

    Returns:
        The names of the fields that changed (empty when nothing did).

    Raises:
        HTTPException: as `create_service_user`.
    """
    changed: list[str] = []
    organization_id = profile.organization_id
    if "name" in fields:
        new_name = (name or "").strip()
        if not new_name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name is required.")
        if new_name != user.display_name:
            db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())
            _require_unused_name(db, organization_id, new_name, except_user_id=user.id)
            user.display_name = new_name
            changed.append("name")
    if "description" in fields and (description or "").strip() != profile.description:
        profile.description = (description or "").strip()
        changed.append("description")
    if "email" in fields:
        address = clean_address(email)
        target = address or generated_address(user.id)
        if target != user.email:
            if address is not None:
                _require_unused_address(db, address, except_user_id=user.id)
            user.email = target
            changed.append("email")
    if "responsible" in fields:
        _check_responsible(db, organization_id, responsible, own_id=user.id)
        if principal_ref(profile.responsible_type, profile.responsible_id) != responsible:
            for column, value in principal_columns("responsible", responsible).items():
                setattr(profile, column, value)
            changed.append("responsible")
    if changed:
        db.flush()
        log_event(
            db, entity_type="service_user", entity_id=user.id, action="updated", actor_id=actor_id,
            organization_id=organization_id, detail={"fields": changed},
        )
    return changed


def reactivate(db: Session, user: User, profile: ServiceUserProfile, *, actor_id: uuid.UUID) -> None:
    """Reactivates a deactivated service user (its revoked tokens stay revoked; new ones are issued).

    Args:
        db: Active session; flushed, not committed.
        user / profile: The service user.
        actor_id: The administrator acting.

    Raises:
        HTTPException: 403 when a server administrator banned it; 409 when it is archived.
    """
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been banned and cannot be reactivated.")
    if user.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "An archived service user cannot be reactivated.")
    if user.is_active:
        return
    user.is_active = True
    user.deactivated_at = None
    log_event(
        db, entity_type="service_user", entity_id=user.id, action="reactivated", actor_id=actor_id,
        organization_id=profile.organization_id,
    )


def access_flags(profile: ServiceUserProfile, roles: set[OrgRole]) -> list[ServiceUserFlag]:
    """What the access review flags on a service user: no responsible principal, and administrator rights held.

    Args:
        profile: The service user's profile.
        roles: Its organisation roles.
    """
    flags: list[ServiceUserFlag] = []
    if profile.responsible_id is None:
        flags.append("no_responsible")
    if roles & _ADMINISTRATOR_ROLES:
        flags.append("administrator")
    return flags


def export_org(db: Session, organization: Organization) -> list[dict[str, Any]]:
    """The organisation bundle's `service_users` section: configuration only, never a token, hash or address.

    A service user is not a member entry of the bundle (its generated address would import as an invitation), so this
    section carries what an import needs to create it afresh: name, description, roles, group names, whether it is
    active and the responsible principal by portable key.

    Args:
        db: Active session (read-only).
        organization: The organisation exported.
    """
    rows = db.execute(
        select(User, ServiceUserProfile).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id)
        .where(ServiceUserProfile.organization_id == organization.id, User.is_archived.is_(False))
        .order_by(func.lower(User.display_name))
    ).all()
    out: list[dict[str, Any]] = []
    for user, profile in rows:
        roles = sorted(
            r.value for r in db.scalars(
                select(UserOrgRole.role).where(UserOrgRole.user_id == user.id, UserOrgRole.organization_id == organization.id)
            )
        )
        groups = sorted(
            db.scalars(
                select(OrgGroup.name).join(OrgGroupMember, OrgGroupMember.org_group_id == OrgGroup.id).where(
                    OrgGroupMember.user_id == user.id, OrgGroup.organization_id == organization.id
                )
            )
        )
        out.append({
            "name": user.display_name, "description": profile.description, "org_roles": roles, "group_names": groups,
            "is_active": user.is_active,
            "responsible": principal_to_bundle(db, profile.responsible_type, profile.responsible_id),
        })
    return out


def import_org(
    db: Session, organization: Organization, entries: list[dict[str, Any]], actor_id: uuid.UUID, warn: Any,
) -> int:
    """Creates the bundle's service users in `organization` (after its members and groups exist).

    A service user whose name the organisation already has is left as it is (a merge never overwrites). Each created
    one gets a generated address and no token; a deactivated one is imported deactivated. A responsible principal that
    cannot be matched is left empty, with a warning.

    Args:
        db: Active session; rows are added and flushed, not committed.
        organization: The importing organisation.
        entries: The bundle's `service_users` section.
        actor_id: The importing administrator.
        warn: Collects a warning message (`BundleImportWarnings.add`).

    Returns:
        How many were created.
    """
    created = 0
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        existing = db.scalar(
            select(User.id).join(ServiceUserProfile, ServiceUserProfile.user_id == User.id).where(
                ServiceUserProfile.organization_id == organization.id, func.lower(User.display_name) == name.lower()
            )
        )
        if existing is not None:
            warn(f"Service user '{name}' already exists in this organisation and was left as it is.")
            continue
        ref, warning = principal_from_bundle(
            db, entry.get("responsible"), organization_id=organization.id, project_id=None, fallback_user_id=actor_id,
            required=False,
        )
        if warning:
            warn(f"Service user '{name}': {warning}")
        user, _profile = create_service_user(
            db, organization=organization, actor_id=actor_id, name=name, description=str(entry.get("description") or "")[:500],
            email=None, responsible=ref,
        )
        for role_value in entry.get("org_roles") or []:
            try:
                role = OrgRole(role_value)
            except ValueError:
                continue
            if role is not OrgRole.MEMBER:
                db.add(UserOrgRole(user_id=user.id, organization_id=organization.id, role=role))
        for group_name in entry.get("group_names") or []:
            group = db.scalar(select(OrgGroup).where(OrgGroup.organization_id == organization.id, OrgGroup.name == group_name))
            if group is not None:
                db.add(OrgGroupMember(org_group_id=group.id, user_id=user.id))
        if entry.get("is_active") is False:
            user.is_active = False
        created += 1
    db.flush()
    return created
