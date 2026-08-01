"""
Module: services.custom_fields

Validates submitted custom attribute values against a project's
`CustomFieldDefinition` rows (C-C-01, C-C-02) before they're stored in a
requirement/change-request version's `custom_fields` JSONB column.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_field import CustomFieldDefinition, CustomFieldEntityKind, CustomFieldType


def validate_custom_field_values(
    db: Session, project_id: UUID, entity_kind: CustomFieldEntityKind, values: dict[str, Any]
) -> dict[str, Any]:
    """Validates and normalises submitted custom field values.

    Args:
        db: An active database session.
        project_id: The project the entity belongs to.
        entity_kind: Whether these values are for a requirement or a change request.
        values: Submitted values, keyed by `CustomFieldDefinition` id (as a string).

    Returns:
        The validated values, limited to known field ids for this project/entity_kind.

    Raises:
        HTTPException: 400 if a required field is missing or a value doesn't
            match its field's type/options.
    """
    definitions = db.scalars(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.project_id == project_id, CustomFieldDefinition.entity_kind == entity_kind
        )
    ).all()

    cleaned: dict[str, Any] = {}
    for definition in definitions:
        field_id = str(definition.id)
        value = values.get(field_id)

        if value is None:
            if definition.required:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{definition.name}' is required.")
            continue

        if definition.field_type in (CustomFieldType.SHORT_TEXT, CustomFieldType.LONG_TEXT):
            if not isinstance(value, str):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{definition.name}' must be text.")
        elif definition.field_type == CustomFieldType.CHECKBOX:
            if not isinstance(value, bool):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{definition.name}' must be true/false.")
        elif definition.field_type == CustomFieldType.LIST:
            options = definition.options or []
            if value not in options:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{definition.name}' must be one of {options}.")

        cleaned[field_id] = value

    return cleaned
