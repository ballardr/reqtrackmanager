"""
Module: services.custom_role_presets

Ready-made custom roles an organisation can use as they are or copy.

Responsibilities:
- Define the presets once (`PRESETS`), for both the seeding of a new organisation
  and the Role Management form's "start from a preset" list, so the two cannot drift.
- Seed them into a newly created organisation (`seed_custom_role_presets`).

Design decisions:
- Presets use the "every record type" atom (`ALL_ARTEFACT_TYPES`), so a preset keeps
  covering artefact types a module registers later.
- Existing organisations are never changed; an admin creates the role from the form's
  preset list. A seeded preset is an ordinary `CustomRoleDefinition`: editable, deletable.

Depends on: `models.custom_role`, `services.permissions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.custom_role import CustomRoleDefinition, CustomRolePermission
from app.models.enums import PermissionLevel
from app.services.permissions import ALL_ARTEFACT_TYPES, encode_permission


@dataclass(frozen=True)
class CustomRolePreset:
    """A ready-made custom role definition.

    Attributes:
        key: Stable identifier for the preset.
        name: The role's name when created.
        description: The role's description when created.
        scope: `"org"` or `"project"`, as `CustomRoleDefinition.scope`.
        permissions: Permission atom keys (valid for every organisation).
    """

    key: str
    name: str
    description: str
    scope: str
    permissions: tuple[str, ...]


PRESETS: tuple[CustomRolePreset, ...] = (
    CustomRolePreset(
        key="link_editor",
        name="Link editor",
        description=(
            "Set and remove links on any record of a project, and nothing else. "
            "Grant it alongside a project role such as Member, which is what opens the project."
        ),
        scope="project",
        permissions=(
            encode_permission(ALL_ARTEFACT_TYPES, PermissionLevel.VIEW.value),
            encode_permission(ALL_ARTEFACT_TYPES, PermissionLevel.LINK.value),
        ),
    ),
)


def seed_custom_role_presets(db: Session, organization_id: UUID) -> None:
    """Adds every preset as a custom role of a newly created organisation (not committed or
    flushed beyond what the insert needs; the caller owns the transaction).

    Args:
        db: Active session.
        organization_id: The new organisation.
    """
    for preset in PRESETS:
        role = CustomRoleDefinition(
            organization_id=organization_id, name=preset.name, description=preset.description, scope=preset.scope
        )
        db.add(role)
        db.flush()
        for permission in preset.permissions:
            db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
