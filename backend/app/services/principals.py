"""
Module: services.principals

The one mechanism for a field that names "who": a user, an organisation group
or a project group (docs/plans/users-and-groups-parity-plan.md). A record
field becomes a `<name>_type` / `<name>_id` column pair (`models.principal`)
and everything about it goes through this module, so every module resolves,
filters, displays, notifies and deletes a group-owned record the same way.

Responsibilities:
- `validate_principal`: the write-time check (exists, same organisation, a
  project group only for a record in its own project, a user must be an
  organisation member).
- Membership: `principal_member_ids`, `is_principal_member` (effective
  membership, via `services.rbac`), `principal_recipients` (notification
  fan-out) and `principal_filter_clause` (a list's "mine" filter).
- Display: `principal_labels` (batch display names and member counts).
- Deletion: `compute_usage` / `prepare_group_deletion` use every declared
  `PrincipalReference` (core's `CORE_PRINCIPAL_REFERENCES` plus each module's
  `ModuleDefinition.principal_references`) to block deleting a group that
  still owns records, and to reassign or clear them with one audit event per row.
- Bundles: `principal_to_bundle` / `principal_from_bundle` round-trip a
  principal by name or email instead of a raw id.

Design decisions:
- A group never confers more than its members hold individually: this module
  answers "is this user in the group", nothing else. Callers keep their own
  role or permission checks and use membership only as an additional way to
  satisfy an "is the owner" test.
- Project-group membership counts even while the group holds no role
  (`rbac.effective_project_group_member_ids`): it is a named team.
- Users in a group who are inactive, archived or banned are excluded from
  notification fan-out but still count as members.
- Rows a `PrincipalReference.live_filter` excludes (older versions) are left
  untouched on group deletion and display as a deleted group.

Dependencies: `services.rbac` (membership), `services.audit`, `modules.registry`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, false, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.enums import PrincipalType
from app.models.organization import OrgGroup
from app.models.project import Project, ProjectGroup
from app.models.user import User
from app.modules.registry import PrincipalReference, get_module_principal_references
from app.schemas.principal import PrincipalOut, PrincipalRef, PrincipalUsageItem, PrincipalUsageOut
from app.services.audit import log_event
from app.services.rbac import (
    effective_org_group_ids_for_user,
    effective_org_group_member_ids,
    effective_project_group_member_ids,
    get_effective_org_roles,
    project_group_ids_for_user,
)

# Core fields built as principals (Phase 6 of the plan adds the requirement,
# action and change-request fields here).
CORE_PRINCIPAL_REFERENCES: tuple[PrincipalReference, ...] = ()

DELETED_GROUP_LABEL = "Deleted group"
UNKNOWN_USER_LABEL = "Unknown user"

PRINCIPAL_TYPE_LABEL: dict[PrincipalType, str] = {
    PrincipalType.USER: "User",
    PrincipalType.ORG_GROUP: "Org group",
    PrincipalType.PROJECT_GROUP: "Project group",
}


def all_principal_references() -> list[PrincipalReference]:
    """Core's declared principal fields followed by every module's."""
    return [*CORE_PRINCIPAL_REFERENCES, *get_module_principal_references()]


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


def validate_principal(
    db: Session,
    ref: PrincipalRef | None,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    field: str = "owner",
) -> None:
    """Rejects a principal that may not be named on a record.

    Args:
        db: An active database session (read-only use).
        ref: The principal, or None (an optional field left empty is valid).
        organization_id: The organisation the record belongs to.
        project_id: The record's project, or None for an organisation-scoped
            record (which cannot name a project group).
        field: Field name used in the error message.

    Raises:
        HTTPException: 400 when a user is not a member of the organisation, a group does not
            exist or belongs to another organisation, or a project group is not in `project_id`.
    """
    if ref is None:
        return
    if ref.type is PrincipalType.USER:
        if not get_effective_org_roles(db, ref.id, organization_id):
            raise _bad_request(f"{field} must be a member of this organisation.")
    elif ref.type is PrincipalType.ORG_GROUP:
        group = db.get(OrgGroup, ref.id)
        if group is None or group.organization_id != organization_id:
            raise _bad_request(f"{field} must be a group of this organisation.")
    else:
        if project_id is None:
            raise _bad_request(f"{field} cannot be a project group on an organisation-level record.")
        group = db.get(ProjectGroup, ref.id)
        project = db.get(Project, project_id)
        if group is None or project is None or group.project_id != project_id or project.organization_id != organization_id:
            raise _bad_request(f"{field} must be a group of this project.")


def principal_member_ids(db: Session, ref: PrincipalRef) -> set[uuid.UUID]:
    """The users a principal stands for: the user itself, or a group's effective members.

    Org groups resolve transitively through nested groups; project groups include their nested org
    groups and referenced source projects (`rbac.effective_project_group_member_ids`).
    """
    if ref.type is PrincipalType.USER:
        return {ref.id}
    if ref.type is PrincipalType.ORG_GROUP:
        return effective_org_group_member_ids(db, ref.id)
    return effective_project_group_member_ids(db, ref.id)


def is_principal_member(db: Session, ref: PrincipalRef | None, user_id: uuid.UUID) -> bool:
    """True when `user_id` is the principal or an effective member of it (False for no principal)."""
    if ref is None:
        return False
    if ref.type is PrincipalType.USER:
        return ref.id == user_id
    return user_id in principal_member_ids(db, ref)


def principal_recipients(
    db: Session, refs: Iterable[PrincipalRef | None], *, exclude: Iterable[uuid.UUID] = ()
) -> set[uuid.UUID]:
    """The deduplicated users to notify for these principals, minus `exclude` (usually the actor).

    Inactive, archived and banned users are dropped; a person in several of the groups is returned once.
    """
    ids: set[uuid.UUID] = set()
    for ref in refs:
        if ref is not None:
            ids |= principal_member_ids(db, ref)
    ids -= set(exclude)
    if not ids:
        return ids
    return set(
        db.scalars(
            select(User.id).where(
                User.id.in_(ids), User.is_active.is_(True), User.is_archived.is_(False), User.is_banned.is_(False)
            )
        ).all()
    )


def principal_filter_clause(
    db: Session,
    user_id: uuid.UUID,
    type_column: Any,
    id_column: Any,
    *,
    project_id: uuid.UUID | None = None,
) -> ColumnElement[bool]:
    """SQL condition matching rows whose principal is the user or a group they belong to.

    Args:
        db: An active database session (read-only use).
        user_id: The user whose "mine" view this is.
        type_column: The model's `<name>_type` column.
        id_column: The model's `<name>_id` column.
        project_id: The project the list is scoped to; project groups are only matched when given.

    Returns:
        A condition for `.where(...)`.
    """
    clauses: list[ColumnElement[bool]] = [
        and_(type_column == PrincipalType.USER.value, id_column == user_id)
    ]
    org_group_ids = effective_org_group_ids_for_user(db, user_id)
    if org_group_ids:
        clauses.append(and_(type_column == PrincipalType.ORG_GROUP.value, id_column.in_(org_group_ids)))
    if project_id is not None:
        project_group_ids = project_group_ids_for_user(db, user_id, project_id)
        if project_group_ids:
            clauses.append(and_(type_column == PrincipalType.PROJECT_GROUP.value, id_column.in_(project_group_ids)))
    return or_(*clauses) if clauses else false()


def principal_labels(
    db: Session, refs: Iterable[PrincipalRef | tuple[str, uuid.UUID] | None]
) -> dict[tuple[str, uuid.UUID], PrincipalOut]:
    """Display data for many principals at once, keyed by `(type value, id)`.

    A missing user or group yields a placeholder label with `exists=False`, never an error, so
    history rows that still name a deleted group render.

    Args:
        db: An active database session (read-only use).
        refs: `PrincipalRef`s or `(type, id)` pairs (None entries are skipped).
    """
    wanted: set[tuple[str, uuid.UUID]] = set()
    for ref in refs:
        if ref is None:
            continue
        wanted.add((ref.type.value, ref.id) if isinstance(ref, PrincipalRef) else (PrincipalType(ref[0]).value, ref[1]))
    out: dict[tuple[str, uuid.UUID], PrincipalOut] = {}

    user_ids = {i for t, i in wanted if t == PrincipalType.USER.value}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    for i in user_ids:
        user = users.get(i)
        out[(PrincipalType.USER.value, i)] = PrincipalOut(
            type=PrincipalType.USER, id=i, label=user.display_name if user else UNKNOWN_USER_LABEL,
            exists=user is not None,
        )

    org_ids = {i for t, i in wanted if t == PrincipalType.ORG_GROUP.value}
    org_names = (
        {g.id: g.name for g in db.scalars(select(OrgGroup).where(OrgGroup.id.in_(org_ids))).all()} if org_ids else {}
    )
    for i in org_ids:
        out[(PrincipalType.ORG_GROUP.value, i)] = PrincipalOut(
            type=PrincipalType.ORG_GROUP, id=i, label=org_names.get(i, DELETED_GROUP_LABEL),
            member_count=len(effective_org_group_member_ids(db, i)) if i in org_names else None,
            exists=i in org_names,
        )

    project_ids = {i for t, i in wanted if t == PrincipalType.PROJECT_GROUP.value}
    project_names = (
        {g.id: g.name for g in db.scalars(select(ProjectGroup).where(ProjectGroup.id.in_(project_ids))).all()}
        if project_ids else {}
    )
    for i in project_ids:
        out[(PrincipalType.PROJECT_GROUP.value, i)] = PrincipalOut(
            type=PrincipalType.PROJECT_GROUP, id=i, label=project_names.get(i, DELETED_GROUP_LABEL),
            member_count=len(effective_project_group_member_ids(db, i)) if i in project_names else None,
            exists=i in project_names,
        )
    return out


def principal_ref(type_value: str | None, principal_id: uuid.UUID | None) -> PrincipalRef | None:
    """A record's `<name>_type` / `<name>_id` columns as a `PrincipalRef`, or None for an empty field."""
    if type_value is None or principal_id is None:
        return None
    return PrincipalRef(type=PrincipalType(type_value), id=principal_id)


def principal_text(principal: PrincipalOut | None, *, empty: str = "") -> str:
    """A principal as plain text for a report or export: a user's name, a group's name with its kind
    (`Platform Team (Org group)`) so a group is never mistaken for a person.

    Args:
        principal: The resolved principal, or None for an empty field.
        empty: Returned for an empty field.
    """
    if principal is None:
        return empty
    if principal.type is PrincipalType.USER:
        return principal.label
    return f"{principal.label} ({PRINCIPAL_TYPE_LABEL[principal.type]})"


def principal_out(db: Session, type_value: str | None, principal_id: uuid.UUID | None) -> PrincipalOut | None:
    """One resolved principal for a response, or None when the field is empty."""
    if type_value is None or principal_id is None:
        return None
    return principal_labels(db, [(type_value, principal_id)])[(type_value, principal_id)]


# --- Deleting a group that still owns records -------------------------------------------------


def _columns(reference: PrincipalReference) -> tuple[Any, Any]:
    return getattr(reference.model, f"{reference.field}_type"), getattr(reference.model, f"{reference.field}_id")


def _naming_rows_clause(reference: PrincipalReference, group: PrincipalRef) -> ColumnElement[bool]:
    type_column, id_column = _columns(reference)
    clause = and_(type_column == group.type.value, id_column == group.id)
    if reference.live_filter is not None:
        clause = and_(clause, reference.live_filter())
    return clause


def compute_usage(db: Session, group: PrincipalRef) -> PrincipalUsageOut:
    """Counts the records that name `group` across every declared principal field.

    Args:
        db: An active database session (read-only use).
        group: An org group or project group (a user is not tracked).

    Returns:
        The breakdown, with `mandatory_total` the rows that need a replacement before the group can go.
    """
    items: list[PrincipalUsageItem] = []
    total = mandatory_total = 0
    for reference in all_principal_references():
        count = db.scalar(select(func.count()).select_from(reference.model).where(_naming_rows_clause(reference, group)))
        if not count:
            continue
        items.append(PrincipalUsageItem(label=reference.label, count=count, mandatory=reference.mandatory))
        total += count
        if reference.mandatory:
            mandatory_total += count
    return PrincipalUsageOut(total=total, mandatory_total=mandatory_total, items=items)


@dataclass(frozen=True)
class GroupDeletionResult:
    """What `prepare_group_deletion` changed.

    Attributes:
        reassigned: Rows moved to the replacement.
        cleared: Optional-field rows emptied.
    """

    reassigned: int = 0
    cleared: int = 0


def prepare_group_deletion(
    db: Session,
    group: PrincipalRef,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    replacement: PrincipalRef | None = None,
    clear_optional: bool = False,
) -> GroupDeletionResult:
    """Makes it safe to delete `group` by moving or emptying everything that names it, or refusing.

    Does not commit and does not delete the group; the caller does that in the same transaction.

    Args:
        db: An active database session.
        group: The org group or project group about to be deleted.
        organization_id: Its organisation.
        project_id: Its project for a project group, else None. Also the scope the replacement is
            validated in (an org group's replacement cannot be a project group).
        actor_id: The acting user, for the audit trail.
        replacement: Who takes over every row naming the group. Required while a mandatory field names it.
        clear_optional: Empty the optional fields instead of reassigning them (when no replacement is given).

    Returns:
        How many rows were reassigned and cleared.

    Raises:
        HTTPException: 409 when records still name the group and neither a replacement nor
            `clear_optional` covers them; 400 when the replacement is invalid or is the group itself.
    """
    usage = compute_usage(db, group)
    if usage.total == 0:
        return GroupDeletionResult()
    summary = ", ".join(f"{i.count} {i.label}" for i in usage.items)
    if replacement is None and usage.mandatory_total:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This group is still named on {summary}. Choose a replacement.")
    if replacement is None and not clear_optional:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This group is still named on {summary}. Choose a replacement or clear them."
        )
    if replacement is not None:
        if replacement.type is group.type and replacement.id == group.id:
            raise _bad_request("The replacement cannot be the group being deleted.")
        validate_principal(db, replacement, organization_id=organization_id, project_id=project_id, field="replacement")

    reassigned = cleared = 0
    for reference in all_principal_references():
        type_column, id_column = _columns(reference)
        ids = db.scalars(select(reference.model.id).where(_naming_rows_clause(reference, group))).all()
        if not ids:
            continue
        values = (
            {type_column.key: replacement.type.value, id_column.key: replacement.id}
            if replacement is not None else {type_column.key: None, id_column.key: None}
        )
        db.execute(update(reference.model).where(reference.model.id.in_(ids)).values(**values))
        for row_id in ids:
            log_event(
                db, entity_type=reference.audit_entity_type, entity_id=row_id,
                action="principal_reassigned" if replacement is not None else "principal_cleared", actor_id=actor_id,
                organization_id=organization_id, project_id=project_id,
                detail={
                    "field": reference.field, "from": {"type": group.type.value, "id": str(group.id)},
                    "to": {"type": replacement.type.value, "id": str(replacement.id)} if replacement else None,
                    "reason": "group_deleted",
                },
            )
        if replacement is not None:
            reassigned += len(ids)
        else:
            cleared += len(ids)
    return GroupDeletionResult(reassigned=reassigned, cleared=cleared)


# --- Bundles ---------------------------------------------------------------------------------


def principal_to_bundle(db: Session, type_value: str | None, principal_id: uuid.UUID | None) -> dict[str, str] | None:
    """A principal as portable data for an export bundle: a user by email, a group by name.

    Returns None for an empty field or a principal that no longer exists.
    """
    if type_value is None or principal_id is None:
        return None
    if type_value == PrincipalType.USER.value:
        email = db.scalar(select(User.email).where(User.id == principal_id))
        return {"type": type_value, "email": email} if email else None
    model = OrgGroup if type_value == PrincipalType.ORG_GROUP.value else ProjectGroup
    name = db.scalar(select(model.name).where(model.id == principal_id))
    return {"type": type_value, "name": name} if name else None


def principal_from_bundle(
    db: Session,
    data: dict[str, Any] | None,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    fallback_user_id: uuid.UUID,
) -> tuple[PrincipalRef | None, str | None]:
    """Resolves a bundled principal in the importing organisation.

    A user is matched by email among the organisation's members, an org group by name, a project group
    by name within `project_id`. Anything that cannot be matched falls back to `fallback_user_id`
    (the importing user) with a warning; an import never fails because of it.

    Returns:
        `(ref, warning)`: `ref` is None only when `data` is empty; `warning` is set on a fallback.
    """
    if not data:
        return None, None
    kind, name = data.get("type"), data.get("email") or data.get("name")
    found: uuid.UUID | None = None
    if kind == PrincipalType.USER.value and data.get("email"):
        candidate = db.scalar(select(User.id).where(func.lower(User.email) == str(data["email"]).lower()))
        if candidate is not None and get_effective_org_roles(db, candidate, organization_id):
            found = candidate
    elif kind == PrincipalType.ORG_GROUP.value and data.get("name"):
        matches = db.scalars(
            select(OrgGroup.id).where(OrgGroup.organization_id == organization_id, OrgGroup.name == data["name"])
        ).all()
        found = matches[0] if len(matches) == 1 else None
    elif kind == PrincipalType.PROJECT_GROUP.value and data.get("name") and project_id is not None:
        found = db.scalar(
            select(ProjectGroup.id).where(ProjectGroup.project_id == project_id, ProjectGroup.name == data["name"])
        )
    if found is not None:
        return PrincipalRef(type=PrincipalType(kind), id=found), None
    return (
        PrincipalRef(type=PrincipalType.USER, id=fallback_user_id),
        f"{kind or 'principal'} '{name}' was not found in this organisation; assigned to the importing user.",
    )
