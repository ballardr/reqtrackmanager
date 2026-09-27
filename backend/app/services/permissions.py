"""
Module: services.permissions

Fine-Grained Access Control (`docs/plans/core-fine-grained-access-control-
plan.md` Phase 1): the permission-atom vocabulary — what a permission
*is* and how it's encoded/validated — derived from the existing artefact-
type registry (`app.modules.registry.get_all_registered_artefact_types`)
and the new sub-type-provider registry (`get_subtypes`), the same way
Phase 0 Q1/Q3 resolved: `(artefact_type, level, subtype)` triples crossed
across every registered artefact type and `PermissionLevel`, plus a short,
explicit list of non-artefact administrative permissions.

This module is deliberately inert with respect to any actual authorization
decision — it defines and validates the vocabulary, nothing more.
`app.services.rbac.get_effective_permissions`/`require_permission` (Phase
2) is where a caller's held permissions actually get resolved and checked
against it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel

ADMINISTRATIVE_PERMISSIONS: tuple[str, ...] = (
    "manage_members",
    "manage_settings",
    "manage_integrations",
    "grant_roles",
)
"""Short, explicit list of non-artefact administrative permissions (Phase 0
Q1) — hand-maintained here rather than derived from any registry, since
these describe fixed organisational admin actions, not a per-artefact-type
CRUD tier. Deliberately excludes a "manage custom roles" atom (Phase 0 Q5):
creating/editing/deleting a `CustomRoleDefinition` stays `ORG_ADMIN`-only
and is never delegable through any permission atom, closing off the "mint a
new, arbitrarily powerful role" escalation path entirely. `grant_roles`
(Phase 0 Q6) is the one atom here whose holder can affect role assignment
at all, and even it cannot grant `ORG_ADMIN`/`MODULE_ADMINISTRATOR` — see
`docs/plans/core-fine-grained-access-control-plan.md`'s own residual-risk
note for that atom's full, deliberately documented scope.
"""


def encode_permission(artefact_type: str, level: str, subtype: str | None = None) -> str:
    """Encodes an artefact-type permission atom as the flat string
    `CustomRolePermission.permission`/`ModuleRoleDefinition.permissions`
    entries store — e.g. `encode_permission("decision", "approve_baseline",
    "Architecture")` -> `"decision:approve_baseline:Architecture"`, or with
    `subtype=None` (the wildcard, matching every sub-type — Phase 0 Q3) ->
    `"decision:approve_baseline:"`.

    Pure encoding only — neither `artefact_type` nor `subtype` is validated
    here; see `validate_permission_key` for the write-time check against
    the live, per-organisation registries.
    """
    return f"{artefact_type}:{level}:{subtype or ''}"


@dataclass(frozen=True)
class Permission:
    """One permission atom in an organisation's currently-valid vocabulary
    (`get_all_permissions`) — either an artefact-type/level/sub-type atom,
    or a bare administrative permission.

    Attributes:
        key: The canonical string form — `encode_permission(...)`'s output
            for an artefact-type atom, or the bare key itself (e.g.
            `"grant_roles"`) for an administrative one. This is what a
            `CustomRolePermission.permission`/`ModuleRoleDefinition.
            permissions` entry actually stores.
        label: Human-readable label for the Role Management UI's
            permission-atom picker (Phase 3), e.g. `"decision — approve_
            baseline (Architecture)"` or `"Grant Roles"`.
        artefact_type: The artefact type this atom applies to, or `None`
            for an administrative permission.
        level: The `PermissionLevel` value, or `None` for an administrative
            permission.
        subtype: The sub-type this atom is scoped to, or `None` for either
            the sub-type wildcard or an administrative permission.
    """

    key: str
    label: str
    artefact_type: str | None
    level: str | None
    subtype: str | None


def get_all_permissions(db: Session, organization_id: uuid.UUID) -> list[Permission]:
    """The full, currently-valid permission-atom vocabulary for
    `organization_id`: every registered artefact type x every
    `PermissionLevel` x (the sub-type wildcard, plus every current
    sub-type value that artefact type's registered provider returns for
    this organisation, if any), followed by `ADMINISTRATIVE_PERMISSIONS`.

    Org-scoped, unlike `app.modules.registry.get_all_registered_artefact_
    types` (a process-wide set): the sub-type dimension is per-organisation
    *data* (e.g. Decision Management's own `DecisionTypeDefinition` rows),
    so two organisations can see a different vocabulary for the same
    artefact type. Backs `GET .../permissions` (Phase 3) and the write-time
    validation `validate_permission_key` (below) performs.

    Returns:
        Every currently-valid `Permission` — artefact-type atoms first (by
        `get_all_registered_artefact_types()` in sorted order, then by
        `PermissionLevel`'s own declaration order, wildcard before any
        specific sub-type), followed by the administrative permissions.
    """
    from app.modules.registry import get_all_registered_artefact_types, get_subtypes

    permissions: list[Permission] = []
    for artefact_type in sorted(get_all_registered_artefact_types()):
        for level in PermissionLevel:
            permissions.append(
                Permission(
                    key=encode_permission(artefact_type, level.value),
                    label=f"{artefact_type} — {level.value}",
                    artefact_type=artefact_type,
                    level=level.value,
                    subtype=None,
                )
            )
            for subtype in get_subtypes(db, organization_id, artefact_type):
                permissions.append(
                    Permission(
                        key=encode_permission(artefact_type, level.value, subtype),
                        label=f"{artefact_type} — {level.value} ({subtype})",
                        artefact_type=artefact_type,
                        level=level.value,
                        subtype=subtype,
                    )
                )
    for key in ADMINISTRATIVE_PERMISSIONS:
        permissions.append(
            Permission(key=key, label=key.replace("_", " ").title(), artefact_type=None, level=None, subtype=None)
        )
    return permissions


def validate_permission_key(db: Session, organization_id: uuid.UUID, permission: str) -> None:
    """Raises `ValueError` if `permission` is not currently valid for
    `organization_id` (not present in `get_all_permissions`'s own result)
    — called at `CustomRolePermission`/`ModuleRoleDefinition.permissions`
    write time (Phase 3), mirroring `app.services.relationships.create_
    link`'s identical "validate against the live registry, fail fast"
    treatment of `ArtefactLink.source_type`.

    Raises:
        ValueError: if `permission` isn't a currently-valid atom for this
            organisation — a caller-side typo, a stale sub-type value that
            no longer exists, or an artefact type with no registered
            sub-type provider being given one anyway.
    """
    valid_keys = {p.key for p in get_all_permissions(db, organization_id)}
    if permission not in valid_keys:
        raise ValueError(f"{permission!r} is not a currently valid permission for this organisation.")
