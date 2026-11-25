"""
Module: modules.traceability.approval_policy

The approval policy of governance: which roles may also approve a record type, set by a governance profile or by a
project. Registered as the `approval_policies` part's policy resolver, profile contributor and project bundle entry.

Responsibilities:
- Write a profile's or a project's roles for a record type (`set_profile_roles`, `set_project_roles`), validating the type
  and the roles and recording one audit event each (type and role keys only).
- Answer the core `GovernanceSeam.APPROVAL` for one type in one project (`resolve_policy`): the union of the roles of the
  profiles that apply, the project's own row, or, when it has none, the nearest ancestor project's.
- Describe a profile's policy and a project's effective policy with where each role came from (`profile_policy`,
  `project_policy`), for the screens.
- Count, export and import a profile's rows (`count_rows`, `export_rows`, `import_rows`) and a project's own rows
  (`export_project_rows`, `import_project_rows`).

Design decisions:
- A policy only adds approvers (`services.approval_policy`): merging by union means a profile, a project and an ancestor
  can each add roles and none can take away what another gave. The default approvers are never removed.
- Which profiles apply is `profile_resolution`'s decision (Enforced, Default not opted out, opted-in); this file reads
  their rows. An exempt or opted-out project therefore does not get a profile's roles.
- A project row beats the nearest ancestor's for the same type, so a child project can follow its parent's roles (no row)
  or set its own. A row with no roles is a deliberate "no extra approvers here" and stops the ancestor's applying.
- A role is stored by kind and key. A custom role travels in bundles by name, since its id belongs to one organisation.
- A role that is no longer offered (a module switched off for the organisation) is kept in the row and admits nobody
  while it is unavailable (`services.approval_policy.holds_role`).
- Import writes a project's rows without per-row audit events: the import itself is the recorded act.

Dependencies: `services.approval_policy` (role vocabulary), `services.approval_separation` (the types with an approval
gate), `profile_resolution`, `services.project_hierarchy`, `models`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.custom_role import CustomRoleDefinition
from app.models.project import Project
from app.modules.seams import ApprovalPolicy, ApproverRole
from app.modules.traceability.models import (
    GovernanceApprovalPolicy,
    GovernanceApprovalPolicyRole,
    GovernanceProfile,
)
from app.modules.traceability.profile_resolution import applicable_profiles
from app.services import approval_policy as core
from app.services import approval_separation, lifecycles
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

PROFILE_AUDIT_ENTITY_TYPE = "governance_profile"
PROJECT_AUDIT_ENTITY_TYPE = "governance_approval_policy"
KIND_APPROVAL = "approval"
PROJECT_ROWS_KEY = "governance_approval_policies"

RoleKey = tuple[str, str]


@dataclass(frozen=True)
class RoleSource:
    """One role of an effective policy with where it came from.

    Attributes:
        role: The role.
        sources: Names of the profiles that give it, in precedence order, then `"project"` when the project's own row does
            or `"parent_project"` when the nearest ancestor's row does.
    """

    role: ApproverRole
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ProjectTypePolicy:
    """A project's approval policy for one record type.

    Attributes:
        gate: The type.
        own: The project's own roles, `None` when it has no row (it follows the nearest ancestor's).
        inherited_from: Name of the ancestor project whose row applies, `None` when the project has its own row or no
            ancestor has one.
        effective: Every role that applies, with its sources.
    """

    gate: approval_separation.ApprovalGate
    own: list[ApproverRole] | None
    inherited_from: str | None
    effective: list[RoleSource]


def _key(role: ApproverRole) -> RoleKey:
    return (role.kind, role.key)


def make_role(kind: str, key: str) -> ApproverRole | None:
    """The role of a stored or bundled kind and key, or `None` when the kind is not one of the three."""
    if kind == core.KIND_PROJECT:
        return ApproverRole("project", key)
    if kind == core.KIND_MODULE:
        return ApproverRole("module", key)
    if kind == core.KIND_CUSTOM:
        return ApproverRole("custom", key)
    return None


def _role(row: GovernanceApprovalPolicyRole) -> ApproverRole | None:
    return make_role(row.role_kind, row.role_key)


def _roles_by_policy(db: Session, policy_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ApproverRole]]:
    """The roles of each policy row, ordered by kind and key, in one read."""
    out: dict[uuid.UUID, list[ApproverRole]] = defaultdict(list)
    if not policy_ids:
        return out
    for row in db.scalars(
        select(GovernanceApprovalPolicyRole)
        .where(GovernanceApprovalPolicyRole.policy_id.in_(policy_ids))
        .order_by(GovernanceApprovalPolicyRole.role_kind, GovernanceApprovalPolicyRole.role_key)
    ):
        if (role := _role(row)) is not None:
            out[row.policy_id].append(role)
    return out


def approval_types(db: Session, organization_id: uuid.UUID) -> list[approval_separation.ApprovalGate]:
    """The record types with an approval gate whose module is in effect for the organisation, in type-name order."""
    return [
        gate for _, gate in sorted(approval_separation.approval_gates().items())
        if lifecycles.enabled_for_organization(db, organization_id, gate.artefact_type, gate.module_key)
    ]


def _gate(artefact_type: str) -> approval_separation.ApprovalGate:
    """The gate of `artefact_type`.

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    gate = approval_separation.approval_gates().get(artefact_type)
    if gate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That record type has no approval gate.")
    return gate


def _write(
    db: Session, *, profile_id: uuid.UUID | None, project_id: uuid.UUID | None, artefact_type: str,
    roles: Sequence[ApproverRole] | None,
) -> bool:
    """Makes the owner's policy row for a type hold exactly `roles` (`None` removes the row; flushed, not audited).

    Returns:
        Whether the stored policy changed.
    """
    query = select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.artefact_type == artefact_type)
    query = query.where(
        GovernanceApprovalPolicy.profile_id == profile_id if profile_id is not None
        else GovernanceApprovalPolicy.project_id == project_id
    )
    policy = db.scalar(query)
    if roles is None:
        if policy is None:
            return False
        db.delete(policy)
        db.flush()
        return True
    created = policy is None
    if policy is None:
        policy = GovernanceApprovalPolicy(profile_id=profile_id, project_id=project_id, artefact_type=artefact_type)
        db.add(policy)
        db.flush()
    existing = {
        (r.role_kind, r.role_key): r
        for r in db.scalars(select(GovernanceApprovalPolicyRole).where(GovernanceApprovalPolicyRole.policy_id == policy.id))
    }
    wanted = {_key(r): r for r in roles}
    for key, row in existing.items():
        if key not in wanted:
            db.delete(row)
    for key, role in wanted.items():
        if key not in existing:
            db.add(GovernanceApprovalPolicyRole(
                policy_id=policy.id, role_kind=role.kind, role_key=role.key,
                custom_role_id=uuid.UUID(role.key) if role.kind == core.KIND_CUSTOM else None,
            ))
    db.flush()
    return created or set(existing) != set(wanted)


def _detail(artefact_type: str, roles: Sequence[ApproverRole] | None) -> dict[str, Any]:
    """Audit detail: the type and the role keys (never names or people)."""
    return {"artefact_type": artefact_type, "roles": None if roles is None else [f"{r.kind}:{r.key}" for r in roles]}


def set_profile_roles(
    db: Session, *, profile: GovernanceProfile, artefact_type: str, roles: Sequence[ApproverRole], actor_id: uuid.UUID,
) -> None:
    """Sets the roles a profile adds as approvers of one record type.

    Args:
        db: Active session (not committed).
        profile: The profile.
        artefact_type: A registered type with an approval gate.
        roles: The roles; an empty list removes the profile's policy for the type.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 for a type without an approval gate; 422 for a role the organisation cannot use.
    """
    _gate(artefact_type)
    valid = core.validate_roles(db, profile.organization_id, roles)
    _write(db, profile_id=profile.id, project_id=None, artefact_type=artefact_type, roles=valid or None)
    log_event(
        db, entity_type=PROFILE_AUDIT_ENTITY_TYPE, entity_id=profile.id, action="approval_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail=_detail(artefact_type, valid),
    )


def set_project_roles(
    db: Session, *, project: Project, artefact_type: str, roles: Sequence[ApproverRole] | None, actor_id: uuid.UUID,
) -> None:
    """Sets the roles a project adds as approvers of one record type.

    Args:
        db: Active session (not committed).
        project: The project.
        artefact_type: A registered type with an approval gate.
        roles: The roles; an empty list is a choice of no extra approvers that stops the nearest ancestor's roles applying;
            `None` removes the row so the project follows the nearest ancestor's.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 for a type without an approval gate; 422 for a role the organisation cannot use.
    """
    _gate(artefact_type)
    valid = None if roles is None else core.validate_roles(db, project.organization_id, roles)
    _write(db, profile_id=None, project_id=project.id, artefact_type=artefact_type, roles=valid)
    log_event(
        db, entity_type=PROJECT_AUDIT_ENTITY_TYPE, entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=_detail(artefact_type, valid),
    )


# --- reading -------------------------------------------------------------------------------------


def profile_policy(db: Session, profile: GovernanceProfile) -> list[tuple[approval_separation.ApprovalGate, list[ApproverRole]]]:
    """The profile's roles for every type with an approval gate that is in effect for its organisation.

    Returns:
        `(gate, roles)` in type-name order; a type the profile sets nothing for has no roles.
    """
    policy_by_type = {
        row.artefact_type: row.id
        for row in db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.profile_id == profile.id))
    }
    roles = _roles_by_policy(db, list(policy_by_type.values()))
    return [
        (gate, roles.get(policy_by_type[gate.artefact_type], []) if gate.artefact_type in policy_by_type else [])
        for gate in approval_types(db, profile.organization_id)
    ]


def _project_rows(
    db: Session, profile_ids: Sequence[uuid.UUID], chain: Sequence[uuid.UUID], artefact_type: str | None,
) -> tuple[dict[tuple[uuid.UUID, str], list[ApproverRole]], dict[tuple[uuid.UUID, str], list[ApproverRole]]]:
    """The policy rows of the applicable profiles and of the project chain, as `(owner id, type) -> roles` (profiles
    first, projects second), read in two statements."""
    owner_filters = []
    if profile_ids:
        owner_filters.append(GovernanceApprovalPolicy.profile_id.in_(profile_ids))
    if chain:
        owner_filters.append(GovernanceApprovalPolicy.project_id.in_(chain))
    if not owner_filters:
        return {}, {}
    query = select(GovernanceApprovalPolicy).where(or_(*owner_filters))
    if artefact_type is not None:
        query = query.where(GovernanceApprovalPolicy.artefact_type == artefact_type)
    policies = list(db.scalars(query))
    roles = _roles_by_policy(db, [p.id for p in policies])
    by_profile = {(p.profile_id, p.artefact_type): roles.get(p.id, []) for p in policies if p.profile_id is not None}
    by_project = {(p.project_id, p.artefact_type): roles.get(p.id, []) for p in policies if p.project_id is not None}
    return by_profile, by_project


def _merge(
    db: Session, project_id: uuid.UUID, chain: Sequence[uuid.UUID], artefact_type: str | None,
) -> tuple[
    dict[str, dict[RoleKey, tuple[ApproverRole, list[str]]]], dict[str, list[ApproverRole] | None], dict[str, uuid.UUID | None],
]:
    """What applies to the project per type: roles with their sources, the project's own roles, and the ancestor whose row
    applies. `chain` is the project's chain, nearest first, starting with the project itself."""
    applied = applicable_profiles(db, project_id)
    by_profile, by_project = _project_rows(db, [a.profile_id for a in applied], chain, artefact_type)
    merged: dict[str, dict[RoleKey, tuple[ApproverRole, list[str]]]] = defaultdict(dict)
    own: dict[str, list[ApproverRole] | None] = {}
    ancestor: dict[str, uuid.UUID | None] = {}
    for profile in applied:
        for (profile_id, type_key), roles in by_profile.items():
            if profile_id == profile.profile_id:
                for role in roles:
                    merged[type_key].setdefault(_key(role), (role, []))[1].append(profile.name)
    for type_key in sorted({t for _, t in by_project}):
        for depth, owner in enumerate(chain):
            if (owner, type_key) in by_project:
                roles = by_project[(owner, type_key)]
                source = "project" if depth == 0 else "parent_project"
                if depth == 0:
                    own[type_key] = roles
                    ancestor[type_key] = None
                else:
                    ancestor[type_key] = owner
                for role in roles:
                    merged[type_key].setdefault(_key(role), (role, []))[1].append(source)
                break
    return merged, own, ancestor


def resolve_policy(db: Session, project_id: uuid.UUID, artefact_type: str) -> ApprovalPolicy | None:
    """`PolicyResolver.resolve` for `GovernanceSeam.APPROVAL`: the roles the project's approval policy adds for a type.

    Args:
        db: Active session (read only).
        project_id: The project.
        artefact_type: The registered record type.

    Returns:
        The union of the roles of the profiles that apply and of the project's own row (else the nearest ancestor's); `None`
        when there are none, so the type's default approvers stand alone.
    """
    merged, _, _ = _merge(db, project_id, get_project_chain_ids(db, project_id), artefact_type)
    roles = merged.get(artefact_type)
    if not roles:
        return None
    return ApprovalPolicy(roles=tuple(role for role, _ in roles.values()))


def project_policy(db: Session, project: Project) -> list[ProjectTypePolicy]:
    """A project's approval policy for every type with an approval gate that is in effect for its organisation.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        One entry per type in type-name order, with the project's own roles, the ancestor whose row applies and every
        effective role with its sources.
    """
    chain = get_project_chain_ids(db, project.id)
    merged, own, ancestor = _merge(db, project.id, chain, None)
    ancestor_names = project_names(db, [a for a in ancestor.values() if a is not None])
    return [
        ProjectTypePolicy(
            gate=gate, own=own.get(gate.artefact_type),
            inherited_from=None if (owner := ancestor.get(gate.artefact_type)) is None else ancestor_names.get(owner),
            effective=[RoleSource(role=r, sources=tuple(s)) for r, s in merged.get(gate.artefact_type, {}).values()],
        )
        for gate in approval_types(db, project.organization_id)
    ]


def project_names(db: Session, project_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, str]:
    """The names of the given projects in one read."""
    if not project_ids:
        return {}
    return dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).tuples().all())


# --- the profile contributor ---------------------------------------------------------------------


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: per profile, the record types it names approver roles for."""
    return {
        profile_id: count
        for profile_id, count in db.execute(
            select(GovernanceApprovalPolicy.profile_id, func.count())
            .where(GovernanceApprovalPolicy.profile_id.in_(profile_ids))
            .group_by(GovernanceApprovalPolicy.profile_id)
        ).tuples()
        if profile_id is not None
    }


def _export_role(role: ApproverRole, custom_names: Mapping[str, str]) -> dict[str, str] | None:
    """A role as a bundle entry: a custom role by name, any other by key; `None` for a custom role that is gone."""
    if role.kind != core.KIND_CUSTOM:
        return {"kind": role.kind, "key": role.key}
    name = custom_names.get(role.key)
    return None if name is None else {"kind": role.kind, "name": name}


def _custom_names(db: Session, organization_id: uuid.UUID) -> dict[str, str]:
    return {
        str(role_id): name
        for role_id, name in db.execute(
            select(CustomRoleDefinition.id, CustomRoleDefinition.name).where(CustomRoleDefinition.organization_id == organization_id)
        ).tuples()
    }


def _export(
    db: Session, organization_id: uuid.UUID, policies: Sequence[GovernanceApprovalPolicy],
) -> list[dict[str, Any]]:
    roles = _roles_by_policy(db, [p.id for p in policies])
    names = _custom_names(db, organization_id)
    entries = []
    for policy in sorted(policies, key=lambda p: p.artefact_type):
        exported = [e for r in roles.get(policy.id, []) if (e := _export_role(r, names)) is not None]
        entries.append({"artefact_type": policy.artefact_type, "roles": exported})
    return entries


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one `approval` entry per type the profile names roles for, ordered by type, each
    role by kind and key (a custom role by name)."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return []
    policies = list(db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.profile_id == profile_id)))
    return [{"kind": KIND_APPROVAL, **entry} for entry in _export(db, profile.organization_id, policies)]


def _import_roles(
    db: Session, organization_id: uuid.UUID, entries: Sequence[Mapping[str, Any]], warn: Callable[[str], None], what: str,
) -> list[ApproverRole]:
    """The bundle's roles resolved in the organisation (a custom role by name). A role the organisation cannot use is
    reported through `warn` and left out."""
    by_name = {name: role_id for role_id, name in _custom_names(db, organization_id).items()}
    offered = {(o.role.kind, o.role.key) for o in core.role_options(db, organization_id)}
    roles: list[ApproverRole] = []
    for entry in entries:
        kind = str(entry.get("kind", ""))
        key = by_name.get(str(entry.get("name", ""))) if kind == core.KIND_CUSTOM else str(entry.get("key", ""))
        role = None if key is None else make_role(kind, key)
        if role is None or _key(role) not in offered:
            warn(f"A role named in the approval policy for {what} is not available in this organisation and was left out.")
        elif role not in roles:
            roles.append(role)
    return roles


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes the bundle's `approval` entries into the profile. A type that is not
    registered, a role the organisation cannot use and an unknown entry are reported through `warn` and skipped."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return
    gates = approval_separation.approval_gates()
    for entry in rows:
        if entry.get("kind") != KIND_APPROVAL:
            warn("An approval policy entry of an unknown kind was not imported.")
            continue
        artefact_type = str(entry.get("artefact_type", ""))
        if artefact_type not in gates:
            warn(f"The approval policy for {artefact_type or 'an unnamed type'} was not imported: the type has no approval gate here.")
            continue
        roles = _import_roles(db, profile.organization_id, entry.get("roles") or [], warn, gates[artefact_type].label)
        if roles:
            _write(db, profile_id=profile_id, project_id=None, artefact_type=artefact_type, roles=roles)


# --- a project's own rows in its bundle ----------------------------------------------------------


def export_project_rows(db: Session, project: Project) -> list[dict[str, Any]]:
    """The project's own policy rows as bundle entries, ordered by type (an entry with no roles is a kept choice)."""
    policies = list(db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.project_id == project.id)))
    return _export(db, project.organization_id, policies)


def import_project_rows(db: Session, project: Project, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """Writes the bundle's entries as the project's own rows. A type with no approval gate here and a role the
    organisation cannot use are reported through `warn` and left out."""
    gates = approval_separation.approval_gates()
    for entry in rows:
        artefact_type = str(entry.get("artefact_type", ""))
        if artefact_type not in gates:
            warn(f"The approval policy for {artefact_type or 'an unnamed type'} was not imported: the type has no approval gate here.")
            continue
        named = entry.get("roles") or []
        roles = _import_roles(db, project.organization_id, named, warn, gates[artefact_type].label)
        if named and not roles:
            continue
        _write(db, profile_id=None, project_id=project.id, artefact_type=artefact_type, roles=roles)
