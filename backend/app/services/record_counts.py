"""
Module: services.record_counts

The project overview's "total records" figure: how many records of each registered artefact type a
project holds, for the types the caller may read.

Responsibilities:
- Count each type through its `RecordTableProvider` (`count`, else the rows of its default list), so a
  new type appears in the overview without an edit to the router.
- Apply the overview's project scope (`ProjectScope.total`), the module gate and the type's `view`
  permission, so a count never includes a type or a project the list itself would not show.

Design decisions:
- A type the caller cannot read, or whose module is off for the project, is omitted, never shown as 0:
  a count of something the caller cannot open would reveal that it exists.
- Only records a person authored in the project count (`RecordTableProvider.in_overview`) and only the
  project's own: an organisation-owned record belongs to no project, and rows derived from an assigned
  standard describe the standard, not the work.
- Types with no records are left out; the total is the sum of the types returned.

Dependencies: `modules.registry`, `services.project_scope`, `services.rbac`, `services.permissions`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    RecordFilters,
    RecordTableProvider,
    artefact_type_enabled_for_project,
    get_record_table_providers,
)
from app.services.permissions import encode_permission
from app.services.project_scope import ProjectScope, gate_open
from app.services.rbac import get_effective_permissions, permission_satisfied


@dataclass(frozen=True)
class RecordTypeCount:
    """One record type's count in the overview.

    Attributes:
        type: The registered artefact type string.
        label: The plural display name (`"Risks"`).
        count: How many records of the type the scope holds (always above zero).
    """

    type: str
    label: str
    count: int


def _own_count(db: Session, user: User, provider: RecordTableProvider, project_id: uuid.UUID) -> int:
    """How many records of the provider's type project `project_id` holds itself (organisation-owned rows excluded).

    Uses the provider's `count` when it has one, else the rows of its default (unfiltered) list.
    """
    if provider.count is not None:
        return provider.count(db, user, project_id)
    rows = provider.list_records(db, user, project_id, RecordFilters())
    owned = provider.organization_owned
    return sum(1 for row in rows if owned is None or not owned(row))


def count_records_by_type(db: Session, user: User, project: Project, project_scope: ProjectScope) -> list[RecordTypeCount]:
    """The records each readable type holds in `project` (and the related projects `project_scope` adds).

    Args:
        db: Active session (read only).
        user: The caller (already allowed to open `project`).
        project: The request project.
        project_scope: The overview's `?project_scope=`.

    Returns:
        The types with at least one record, largest first (ties by label).
    """
    held = get_effective_permissions(db, user.id, project_id=project.id)
    counts: list[RecordTypeCount] = []
    for artefact_type, provider in get_record_table_providers().items():
        if not provider.in_overview or not artefact_type_enabled_for_project(db, artefact_type, project.id):
            continue
        if provider.gate is not None and not gate_open(db, project.id, provider.gate):
            continue
        if not permission_satisfied(held, encode_permission(artefact_type, "view")):
            continue
        total = project_scope.total(
            db, project, user.id, artefact_type, lambda pid, p=provider: _own_count(db, user, p, pid), gate=provider.gate,
        )
        if total > 0:
            counts.append(RecordTypeCount(type=artefact_type, label=provider.label, count=total))
    return sorted(counts, key=lambda c: (-c.count, c.label))
