"""
Module: services.health_core

How the core record types report their progress to the governance health view (`modules.seams.HealthProvider`), and the
two counting helpers a module's own providers share.

Responsibilities:
- Register the Requirement (share approved) and the Change Request (decisions outstanding) as health providers, merged
  by `modules.registry.get_health_providers` with module key `""`, so they are measured whether or not Governance is on.
- `status_counts` and `versioned_status_counts`: one grouped query per type that returns the records by status value, for a
  type whose status sits on the record or on its current version row.

Design decisions:
- A figure counts the project's own live records only: archived records and records set aside for good (a rejected or
  withdrawn proposal) are left out of the total, so a share complete is not dragged down by what nobody will finish.
- One grouped statement per type, never a query per record, so the view stays flat as a project grows.

Dependencies: `models.requirement`, `models.change_request`, `modules.seams`.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.enums import ChangeRequestStatus, RequirementStatus
from app.models.requirement import Requirement, RequirementVersion
from app.modules.seams import HealthMeasure, HealthProvider

REQUIREMENT_TYPE = "requirement"
CHANGE_REQUEST_TYPE = "change_request"


def _value(status: Any) -> str:
    """The plain string of a status column value (an enum member or already a string)."""
    return status.value if isinstance(status, enum.Enum) else str(status)


def status_counts(db: Session, status_column: Any, *where: Any) -> dict[str, int]:
    """The records matching `where` grouped by the status held on the record itself.

    Args:
        db: An active database session (read only).
        status_column: The model's status column (`Decision.status`).
        *where: Filters (the project, not archived).

    Returns:
        `{status value: count}`, only for statuses that have records.
    """
    rows = db.execute(select(status_column, func.count()).where(*where).group_by(status_column)).tuples().all()
    return {_value(status): count for status, count in rows}


def versioned_status_counts(
    db: Session, record_model: Any, version_model: Any, fk: str, status_column: Any, *where: Any,
) -> dict[str, int]:
    """The records matching `where` grouped by the status of their current version row.

    Args:
        db: An active database session (read only).
        record_model: The identity model (`Strategy`).
        version_model: Its version model (`StrategyVersion`), whose `valid_to` is null for the current row.
        fk: The version model's column naming the record (`"strategy_id"`).
        status_column: The version model's status column.
        *where: Filters on the identity model (the project, not archived).

    Returns:
        `{status value: count}`, only for statuses that have records.
    """
    rows = db.execute(
        select(status_column, func.count())
        .select_from(record_model)
        .join(version_model, getattr(version_model, fk) == record_model.id)
        .where(version_model.valid_to.is_(None), *where)
        .group_by(status_column)
    ).tuples().all()
    return {_value(status): count for status, count in rows}


def measure_from_counts(counts: dict[str, int], counted: Collection[str], done: Collection[str]) -> HealthMeasure:
    """A measure from status counts: records in any of `counted` make the total, those in `done` the settled ones.

    Args:
        counts: `{status value: count}`.
        counted: Status values that count towards the total.
        done: Status values that are settled; every one must also be in `counted`.

    Returns:
        The `HealthMeasure`.
    """
    return HealthMeasure(
        total=sum(n for s, n in counts.items() if s in counted), done=sum(n for s, n in counts.items() if s in done),
    )


def _requirements(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """Live requirements, of which the approved ones are done."""
    counts = versioned_status_counts(
        db, Requirement, RequirementVersion, "requirement_id", RequirementVersion.status,
        Requirement.project_id == project_id, Requirement.is_archived.is_(False),
    )
    live = {RequirementStatus.DRAFT.value, RequirementStatus.REVIEWED.value, RequirementStatus.APPROVED.value}
    return measure_from_counts(counts, live, {RequirementStatus.APPROVED.value})


def _change_requests(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """Change requests put to a decision, of which the decided ones are done; drafts and withdrawn requests are not counted."""
    counts = status_counts(db, ChangeRequest.status, ChangeRequest.project_id == project_id)
    decided = {ChangeRequestStatus.APPROVED.value, ChangeRequestStatus.REJECTED.value}
    asked = decided | {ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.IN_REVIEW.value}
    return measure_from_counts(counts, asked, decided)


CORE_HEALTH_PROVIDERS: tuple[HealthProvider, ...] = (
    HealthProvider(
        key="requirement", label="Requirements", artefact_type=REQUIREMENT_TYPE, kind="completion", measure=_requirements,
    ),
    HealthProvider(
        key="change_request", label="Change requests", artefact_type=CHANGE_REQUEST_TYPE, kind="outstanding",
        measure=_change_requests,
    ),
)
