"""
Module: models.principal

Column helpers for a "principal" field — an owner, assignee, reviewer or
similar that names a user, an organisation group or a project group
(`models.enums.PrincipalType`, `services.principals`).

A principal field is a pair of columns, `<name>_type` and `<name>_id`. The id
has no foreign key (it points at one of three tables, the same trade-off
`ArtefactLink` accepts for its polymorphic ids), so integrity is enforced by
`services.principals.validate_principal` on write and by
`ModuleDefinition.principal_references` when a group is deleted. A model uses
these helpers rather than hand-writing the pair, so every principal field has
the same column shape and the same check constraint:

    owner_type: Mapped[str] = principal_type_column()
    owner_id: Mapped[uuid.UUID] = principal_id_column()
    __table_args__ = (principal_check_constraint("owner"),)

Pass `nullable=True` to all three for an optional field.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import MappedColumn, mapped_column

from app.models.enums import PrincipalType

_VALUES = ", ".join(f"'{t.value}'" for t in PrincipalType)


def principal_type_column(*, nullable: bool = False) -> MappedColumn[str]:
    """The `<name>_type` column of a principal field.

    Args:
        nullable: True for an optional field.
    """
    return mapped_column(String(20), nullable=nullable, default=None if nullable else PrincipalType.USER.value)


def principal_id_column(*, nullable: bool = False) -> MappedColumn[uuid.UUID]:
    """The `<name>_id` column of a principal field (no foreign key; see module docstring).

    Args:
        nullable: True for an optional field.
    """
    return mapped_column(UUID(as_uuid=True), nullable=nullable)


def principal_check_constraint(name: str, *, nullable: bool = False) -> CheckConstraint:
    """The check constraint for the principal field `name`: the type is one
    of `PrincipalType`, and an optional field has both columns set or neither.

    Args:
        name: The field's base name (`owner` for `owner_type`/`owner_id`).
        nullable: True for an optional field.

    Returns:
        A constraint to place in the model's `__table_args__`.
    """
    type_ok = f"{name}_type IN ({_VALUES})"
    if nullable:
        both = f"({name}_type IS NULL) = ({name}_id IS NULL)"
        return CheckConstraint(f"({name}_type IS NULL OR {type_ok}) AND {both}", name=f"ck_{name}_principal")
    return CheckConstraint(type_ok, name=f"ck_{name}_principal")
