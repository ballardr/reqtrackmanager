"""
Module: services.approval_policy

The one check every approval path calls to decide whether a person may approve a record of a governed type, and the
vocabulary of roles an approval policy can name.

Responsibilities:
- Answer "may this person approve this record type here" (`may_approve`, `require_approver`): the type's own default
  check (computed by the caller from what it did before the seam existed), then the `approve_baseline` permission atom of
  the type, then the roles an approval policy adds (`policy_allows`).
- Decide whether a person holds a role a policy names (`holds_role`): a fixed project role, a module role or an
  organisation's custom role, each by effective membership (a group counts).
- Describe and validate the roles a policy may name (`role_options`, `validate_roles`).

Design decisions:
- The seam lives in core and the type's current behaviour is its default: with no policy and no atom the answer is the
  default the caller passed, so a project with Governance off, or with nothing configured, behaves as before. The policy
  arrives through the registered `GovernanceSeam.APPROVAL` resolver, so no core file imports a module.
- A policy only adds approvers. It never removes a default approver and never skips the approval separation rule, the
  AI-approval gate for the MCP channel or the record lock, which stay at their call sites.
- A role is held, not composed: naming a module role admits the people who were given it, not every server, organisation
  or project administrator that composes with it elsewhere (`rbac.user_holds_module_role`). A policy therefore cannot hand
  a server administrator an approval right that the type withholds from them.
- The `approve_baseline` atom of a type is consulted for every governed type. Requirements and change requests did not
  consult it before, so a custom role holding it could not approve; the atom is held by project managers only among the
  fixed roles, so no fixed role gains approval.
- A role of a module that is off for the project, or no longer registered, admits nobody; the policy row is kept.
- A record owned by an organisation (no project) has no project policy; only the default and the atom apply.

Dependencies: `services.governance_seams` (the registered resolver), `services.rbac` (roles and permissions),
`services.permissions` (atom encoding), `modules.registry` (module roles and availability).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_role import CustomRoleDefinition
from app.models.enums import PermissionLevel, ProjectRole
from app.models.user import User
from app.modules import registry
from app.modules.seams import ApprovalPolicy, ApproverRole, GovernanceSeam
from app.services import governance_seams, rbac
from app.services.permissions import encode_permission

KIND_PROJECT: Final = "project"
KIND_MODULE: Final = "module"
KIND_CUSTOM: Final = "custom"

PROJECT_ROLE_LABELS: dict[ProjectRole, str] = {
    ProjectRole.PROJECT_MANAGER: "Project Manager",
    ProjectRole.PROJECT_ADMINISTRATOR: "Project Administrator",
    ProjectRole.STAKEHOLDER: "Stakeholder",
    ProjectRole.MEMBER: "Member",
}

_ROLE_SCOPES = ("org", "project")


@dataclass(frozen=True)
class RoleOption:
    """A role a policy may name, for a role picker.

    Attributes:
        role: The role reference to store.
        label: Formal display name (a module role is prefixed with its module's name).
        scope: `project` when the role is granted within a project, `org` when it is granted for the organisation.
    """

    role: ApproverRole
    label: str
    scope: Literal["org", "project"]


def scope_of(value: str) -> Literal["org", "project"] | None:
    """`value` as a role scope a policy can use (`org` or `project`), or `None` for a module-owned entity scope."""
    if value == "org":
        return "org"
    if value == "project":
        return "project"
    return None


def module_role_key(module_key: str, role_key: str) -> str:
    """The `key` of an `ApproverRole` of kind `module`: `<module key>:<role key>`."""
    return f"{module_key}:{role_key}"


def holds_role(
    db: Session, user: User, role: ApproverRole, *, organization_id: uuid.UUID, project_id: uuid.UUID,
) -> bool:
    """Whether `user` holds `role` in the project, directly or through a group.

    Args:
        db: Active session (read only).
        user: The person.
        role: The role a policy names.
        organization_id: The project's organisation.
        project_id: The project.

    Returns:
        `True` when the person holds the role; `False` for a role that is unknown, belongs to a module that is off for
        the project, or belongs to another organisation.
    """
    if role.kind == KIND_PROJECT:
        try:
            wanted = ProjectRole(role.key)
        except ValueError:
            return False
        return wanted in rbac.get_effective_project_roles(db, user.id, project_id)
    if role.kind == KIND_MODULE:
        module_key, _, role_key = role.key.partition(":")
        return registry.is_module_enabled_for_project(db, project_id, module_key) and rbac.user_holds_module_role(
            db, user.id, module_key, role_key, organization_id=organization_id, project_id=project_id,
        )
    if role.kind == KIND_CUSTOM:
        try:
            role_id = uuid.UUID(role.key)
        except ValueError:
            return False
        return role_id in rbac.held_custom_role_ids(db, user.id, organization_id=organization_id, project_id=project_id)
    return False


def policy_roles(db: Session, project_id: uuid.UUID, artefact_type: str) -> Sequence[ApproverRole]:
    """The roles the project's approval policy adds for a record type (empty when Governance is off or none is set)."""
    policy = governance_seams.resolve_policy(db, project_id, GovernanceSeam.APPROVAL, artefact_type)
    return policy.roles if isinstance(policy, ApprovalPolicy) else ()


def policy_allows(
    db: Session, user: User, *, artefact_type: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> bool:
    """Whether the project's approval policy admits `user` as an approver of the record type.

    Args:
        db: Active session (read only).
        user: The person.
        artefact_type: The registered record type.
        organization_id: The project's organisation.
        project_id: The project, `None` for a record the organisation owns (it has no project policy).

    Returns:
        `True` when the user holds any role the policy names.
    """
    if project_id is None:
        return False
    return any(
        holds_role(db, user, role, organization_id=organization_id, project_id=project_id)
        for role in policy_roles(db, project_id, artefact_type)
    )


def may_approve(
    db: Session, user: User, *, artefact_type: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    default: bool = False, subtype: str | None = None,
) -> bool:
    """Whether `user` may approve a record of `artefact_type`.

    Args:
        db: Active session (read only).
        user: The person.
        artefact_type: The registered record type.
        organization_id: The record's organisation.
        project_id: The record's project, `None` for a record the organisation owns.
        default: Whether the type's own check already admits the person (computed by the caller, so each type keeps its
            current rule).
        subtype: The record's sub-type (a Decision Type name) when its approval permission is scoped to one.

    Returns:
        `True` when the default admits the person, they hold the type's `approve_baseline` permission atom (for the
        sub-type, or the sub-type wildcard) or an approval policy names a role they hold.
    """
    if default:
        return True
    held = rbac.get_effective_permissions(db, user.id, organization_id=organization_id, project_id=project_id)
    if rbac.permission_satisfied(held, encode_permission(artefact_type, PermissionLevel.APPROVE_BASELINE.value, subtype)):
        return True
    return policy_allows(db, user, artefact_type=artefact_type, organization_id=organization_id, project_id=project_id)


def require_approver(
    db: Session, user: User, *, artefact_type: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    denied: str, default: bool = False, subtype: str | None = None,
) -> None:
    """`may_approve` that refuses.

    Args:
        denied: The 403 message, unchanged from the type's own check before the seam.
        (others as `may_approve`)

    Raises:
        HTTPException: 403 with `denied` when the person may not approve.
    """
    if not may_approve(
        db, user, artefact_type=artefact_type, organization_id=organization_id, project_id=project_id,
        default=default, subtype=subtype,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, denied)


# --- the role vocabulary -------------------------------------------------------------------------------------


def role_options(db: Session, organization_id: uuid.UUID) -> list[RoleOption]:
    """The roles a policy of the organisation may name: the fixed project roles, the organisation- and project-scoped
    roles of every module that is on for the organisation, and the organisation's custom roles of those scopes.

    Args:
        db: Active session (read only).
        organization_id: The organisation.

    Returns:
        The options, fixed project roles first, then module roles and custom roles by label.
    """
    options = [RoleOption(ApproverRole(KIND_PROJECT, r.value), PROJECT_ROLE_LABELS[r], "project") for r in ProjectRole]
    modules = sorted(registry.get_module_registry().values(), key=lambda m: m.name.casefold())
    module_options = [
        RoleOption(
            ApproverRole(KIND_MODULE, module_role_key(module.key, role.role_key)), f"{module.name}: {role.name}", scope,
        )
        for module in modules
        if registry.is_module_enabled(db, organization_id, module.key)
        for role in module.roles
        if (scope := scope_of(role.scope)) is not None
    ]
    custom_options = [
        RoleOption(ApproverRole(KIND_CUSTOM, str(role.id)), role.name, scope)
        for role in db.scalars(
            select(CustomRoleDefinition).where(
                CustomRoleDefinition.organization_id == organization_id, CustomRoleDefinition.scope.in_(_ROLE_SCOPES),
            )
        )
        if (scope := scope_of(role.scope)) is not None
    ]
    return options + sorted(module_options, key=lambda o: o.label.casefold()) + sorted(custom_options, key=lambda o: o.label.casefold())


def validate_roles(db: Session, organization_id: uuid.UUID, roles: Iterable[ApproverRole]) -> list[ApproverRole]:
    """The distinct roles of `roles`, each checked against the organisation's role vocabulary.

    Args:
        db: Active session (read only).
        organization_id: The organisation the policy belongs to; a custom role of another organisation is refused.
        roles: The roles to store.

    Returns:
        The roles without duplicates, in the order given.

    Raises:
        HTTPException: 422 for a role that is not one of `role_options`.
    """
    allowed = {(o.role.kind, o.role.key) for o in role_options(db, organization_id)}
    out: list[ApproverRole] = []
    for role in roles:
        if (role.kind, role.key) not in allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A role in the policy is not available to this organisation.")
        if role not in out:
            out.append(role)
    return out
