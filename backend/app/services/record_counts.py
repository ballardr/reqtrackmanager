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
from collections.abc import Callable
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
from app.services.tags import TagFilter


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


def _counter(db: Session, user: User, provider: RecordTableProvider) -> Callable[[uuid.UUID], int]:
    """The per-project count function for one record type, bound to its provider."""
    return lambda project_id: _own_count(db, user, provider, project_id)


def _own_count(db: Session, user: User, provider: RecordTableProvider, project_id: uuid.UUID) -> int:
    """How many records of the provider's type project `project_id` holds itself (organisation-owned rows excluded).

    Uses the provider's `count` when it has one, else the rows of its default (unfiltered) list.
    """
    if provider.count is not None:
        return provider.count(db, user, project_id)
    rows = provider.list_records(db, user, project_id, RecordFilters())
    owned = provider.organization_owned
    return sum(1 for row in rows if owned is None or not owned(row))


def count_in_project(
    db: Session, user: User, project: Project, artefact_type: str, *,
    filters: RecordFilters | None = None, tag_filter_for: Callable[[uuid.UUID], TagFilter | None] | None = None,
) -> int | None:
    """How many records of one type `project` holds itself (no related projects), optionally narrowed by the list filters.

    Args:
        db: Active session (read only).
        user: The caller.
        project: The project.
        artefact_type: The registered type string.
        filters: The provider's own list filters; none counts every record.
        tag_filter_for: `project id -> TagFilter` for the shared tag and component/category filter; `None` for none.

    Returns:
        The count, or `None` when the caller may not read the type in that project (`readable_provider`).
    """
    provider = readable_provider(db, user, project, artefact_type)
    if provider is None:
        return None
    if not ((filters is not None and filters.values) or tag_filter_for is not None):
        return _own_count(db, user, provider, project.id)
    rows = provider.list_records(db, user, project.id, filters or RecordFilters())
    tag_filter = tag_filter_for(project.id) if tag_filter_for is not None else None
    if tag_filter is not None:
        rows = tag_filter.keep(db, project.id, artefact_type, rows, id_of=provider.id_of)
    owned = provider.organization_owned
    return sum(1 for row in rows if owned is None or not owned(row))


def readable_provider(
    db: Session, user: User, project: Project, artefact_type: str, held: set[str] | None = None,
) -> RecordTableProvider | None:
    """The type's provider when the caller may read its records in `project`, else `None`.

    A type is readable when it has a provider that counts in the overview, its module (and sub-component) is on
    for the project, its gate is open and the caller holds its `view` permission. `None` is returned, never a zero
    count, so a figure never reveals that records the caller cannot open exist.

    Args:
        db: Active session (read only).
        user: The caller.
        project: The request project.
        artefact_type: The registered type string.
        held: The caller's effective permissions in the project; read when omitted.
    """
    provider = get_record_table_providers().get(artefact_type)
    if provider is None or not provider.in_overview or not artefact_type_enabled_for_project(db, artefact_type, project.id):
        return None
    if provider.gate is not None and not gate_open(db, project.id, provider.gate):
        return None
    permissions = held if held is not None else get_effective_permissions(db, user.id, project_id=project.id)
    if not permission_satisfied(permissions, encode_permission(artefact_type, "view")):
        return None
    return provider


def count_record_type(
    db: Session, user: User, project: Project, project_scope: ProjectScope, artefact_type: str, *,
    filters: RecordFilters | None = None, tag_filter_for: Callable[[uuid.UUID], TagFilter | None] | None = None,
) -> int | None:
    """How many records of one type match the list filters, across the project scope.

    Args:
        db: Active session (read only).
        user: The caller (already allowed to open `project`).
        project: The request project.
        project_scope: The overview's `?project_scope=`.
        artefact_type: The registered type string.
        filters: The provider's own list filters (`RecordTableProvider.filter_params`); none counts every record.
        tag_filter_for: `project id -> TagFilter` for the shared tag and component/category filter, built per project
            because a component or tag belongs to one project; `None` means no such filter.

    Returns:
        The count, or `None` when the caller may not read the type here (`readable_provider`).
    """
    provider = readable_provider(db, user, project, artefact_type)
    if provider is None:
        return None
    narrowed = (filters is not None and bool(filters.values)) or tag_filter_for is not None
    if not narrowed:
        return project_scope.total(db, project, user.id, artefact_type, _counter(db, user, provider), gate=provider.gate)

    def count_for(project_id: uuid.UUID) -> int:
        rows = provider.list_records(db, user, project_id, filters or RecordFilters())
        tag_filter = tag_filter_for(project_id) if tag_filter_for is not None else None
        if tag_filter is not None:
            rows = tag_filter.keep(db, project_id, artefact_type, rows, id_of=provider.id_of)
        owned = provider.organization_owned
        return sum(1 for row in rows if owned is None or not owned(row))

    return project_scope.total(db, project, user.id, artefact_type, count_for, gate=provider.gate)


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
    for artefact_type in get_record_table_providers():
        provider = readable_provider(db, user, project, artefact_type, held)
        if provider is None:
            continue
        total = project_scope.total(
            db, project, user.id, artefact_type, _counter(db, user, provider), gate=provider.gate,
        )
        if total > 0:
            counts.append(RecordTypeCount(type=artefact_type, label=provider.label, count=total))
    return sorted(counts, key=lambda c: (-c.count, c.label))
