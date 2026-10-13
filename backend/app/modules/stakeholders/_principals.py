"""
Module: modules.stakeholders._principals

The owner / champion fields of Personas, Stakeholders and Needs (and an Engagement's facilitator) are principals
(a user, an organisation group or a project group — `services.principals`).
This module is the one place the stakeholders code turns between the three
shapes of such a field, so no router or exporter repeats it:

- request payload (`owner: PrincipalRef`) <-> version columns (`owner_type` / `owner_id`)
- version columns -> `PrincipalOut` (batch-resolved) for responses
- version columns <-> bundle data (a user by email, a group by name)

Design decisions:
- A project group is valid only on a project-scoped record (`validate_principal`
  receives the record's `project_id`, None for an organisation-scoped one).
- Bundles written before groups existed carry `owner_email`; the importer still
  reads it, so an older backup restores.

Dependencies: `services.principals`, `services.bundle_common`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.principals import (
    principal_columns,
    principal_columns_from_bundle,
    principal_labels,
    principal_ref,
    principal_to_bundle,
    validate_principal,
)

Labels = dict[tuple[str, uuid.UUID], PrincipalOut]
OutT = TypeVar("OutT", bound=BaseModel)

PERSONA_PRINCIPAL_FIELDS = ("owner", "champion")
STAKEHOLDER_PRINCIPAL_FIELDS = ("owner",)
NEED_PRINCIPAL_FIELDS = ("owner",)
ENGAGEMENT_PRINCIPAL_FIELDS = ("facilitator",)


def validate_principals(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, **refs: PrincipalRef | None
) -> None:
    """Rejects a principal that may not be named on the record.

    Args:
        db: An active database session.
        organization_id: The record's organisation.
        project_id: The record's project, or None for an organisation-scoped record (no project groups).
        **refs: Field name -> the principal sent for it (None is valid: the field is optional).

    Raises:
        HTTPException: 400 from `validate_principal`.
    """
    for field, ref in refs.items():
        validate_principal(db, ref, organization_id=organization_id, project_id=project_id, field=field)


def columns_for_create(payload: BaseModel, fields: Sequence[str]) -> dict[str, Any]:
    """The version columns for each principal field of a create payload."""
    columns: dict[str, Any] = {}
    for field in fields:
        columns.update(principal_columns(field, getattr(payload, field)))
    return columns


def expand_sent(payload: BaseModel, sent: dict[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Replaces each principal field present in `sent` (a partial update's `model_dump(exclude_unset=True)`)
    with its `<field>_type` / `<field>_id` columns; an explicit null clears the field and an absent one is untouched."""
    for field in fields:
        if field in sent:
            del sent[field]
            sent.update(principal_columns(field, getattr(payload, field)))
    return sent


def resolve_labels(db: Session, versions: Sequence[Any], fields: Sequence[str]) -> Labels:
    """Display data for every principal named by `versions`, in one batch."""
    return principal_labels(
        db, [principal_ref(getattr(v, f"{f}_type"), getattr(v, f"{f}_id")) for v in versions for f in fields]
    )


def principal_of(labels: Labels, version: Any, field: str) -> PrincipalOut | None:
    """The resolved principal of `version.<field>`, or None for an empty field."""
    principal_id = getattr(version, f"{field}_id")
    return None if principal_id is None else labels[(getattr(version, f"{field}_type"), principal_id)]


def principals_of(labels: Labels, version: Any, fields: Sequence[str]) -> dict[str, PrincipalOut | None]:
    """`principal_of` for each field, as keyword arguments for a response model."""
    return {field: principal_of(labels, version, field) for field in fields}


def version_out(
    model: type[OutT], version: Any, labels: Labels, fields: Sequence[str]
) -> OutT:
    """Builds a `*VersionOut` from a version row: the plain columns by name, the principals resolved."""
    data = {name: getattr(version, name) for name in model.model_fields if name not in fields}
    return model(**data, **principals_of(labels, version, fields))


def versions_out(
    db: Session, model: type[OutT], versions: Sequence[Any], fields: Sequence[str]
) -> list[OutT]:
    """Builds the `*VersionOut` history list for a record's version rows."""
    labels = resolve_labels(db, versions, fields)
    return [version_out(model, v, labels, fields) for v in versions]


def principals_to_bundle(db: Session, version: Any, fields: Sequence[str]) -> dict[str, Any]:
    """Bundle entries (`{"owner": {"type": ..., "email"|"name": ...} | None}`) for a version's principal fields."""
    return {
        field: principal_to_bundle(db, getattr(version, f"{field}_type"), getattr(version, f"{field}_id"))
        for field in fields
    }


def principals_from_bundle(
    db: Session, data: dict[str, Any], fields: Sequence[str], *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None, users: UserResolver, warnings: BundleImportWarnings, context: str,
) -> dict[str, Any]:
    """The version columns for a bundled record's principal fields.

    A group or user that cannot be matched in the importing organisation leaves the (optional) field
    empty with a warning. Older bundles carry `<field>_email` instead of `<field>`.
    """
    columns: dict[str, Any] = {}
    for field in fields:
        columns.update(principal_columns_from_bundle(
            db, data, field, organization_id=organization_id, project_id=project_id, users=users, warnings=warnings,
            context=f"{context} {field}", required=False,
        ))
    return columns
