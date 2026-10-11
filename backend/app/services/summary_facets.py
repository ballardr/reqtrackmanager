"""
Module: services.summary_facets

Helpers modules use to give their `ArtefactSummary`s the `facets` the link finder's
browse levels read (Platform Enhancements Phase 6c).

Responsibilities:
- Build a status facet with a human label.
- Resolve the effective name of a two-tier type (an organisation type, optionally
  renamed or replaced by a project row) for a batch of records in one query.

Design decisions:
- A facet is `(option id, label)`; a status's id is its wire value and its label comes
  from the owning module's label map where it has one, else the value humanised, so the
  finder never shows a raw enum string.
- A two-tier type is identified by its organisation type when it has one, so a project's
  rename of an organisation type still groups with it.

Dependencies: SQLAlchemy only; the caller passes the module's own type models.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

Facet = tuple[str, str]


def humanise(value: str) -> str:
    """`ready_for_decision` -> `Ready for decision`."""
    return value.replace("_", " ").capitalize()


def status_facet(value: str, labels: Mapping[str, str] | None = None) -> Facet:
    """The `status` facet for a wire value, labelled from `labels` or humanised."""
    return value, (labels or {}).get(value, humanise(value))


def two_tier_type_facets(
    db: Session, org_type_model: Any, project_type_model: Any, *,
    org_type_ids: Iterable[uuid.UUID | None] = (), project_type_ids: Iterable[uuid.UUID | None] = (),
) -> dict[tuple[str, uuid.UUID], Facet]:
    """Facets for records typed by an organisation type or a project type row.

    Args:
        db: Active session (read only).
        org_type_model: The organisation-level definition model (`id`, `name`).
        project_type_model: The project-level model (`id`, `org_type_id`, `name_override`).
        org_type_ids / project_type_ids: The ids the records carry (`None` entries ignored).

    Returns:
        `{("org", org type id) or ("project", project type row id): (facet id, label)}`;
        the facet id is the organisation type's id when the type has one.
    """
    result: dict[tuple[str, uuid.UUID], Facet] = {}
    org_ids = {i for i in org_type_ids if i is not None}
    project_ids = {i for i in project_type_ids if i is not None}
    if project_ids:
        rows = db.execute(
            select(project_type_model.id, project_type_model.org_type_id, project_type_model.name_override, org_type_model.name)
            .outerjoin(org_type_model, org_type_model.id == project_type_model.org_type_id)
            .where(project_type_model.id.in_(project_ids))
        ).all()
        for row_id, org_id, override, org_name in rows:
            result[("project", row_id)] = (str(org_id or row_id), override or org_name or "")
    if org_ids:
        for row_id, name in db.execute(select(org_type_model.id, org_type_model.name).where(org_type_model.id.in_(org_ids))).all():
            result[("org", row_id)] = (str(row_id), name)
    return result
