"""
Module: modules.product_feedback.references

A request's external references: pointers to the same work in outside tools (a Jira epic, a ServiceNow ticket),
each with the system it lives in and a role (`origin`: where the request came from; `delivery`: where it is built).

Responsibilities:
- `references_by_request`: many requests' references with their system names in a fixed number of statements.
- `add_reference` / `update_reference` / `remove_reference`: the gated bodies' data changes (no commit, no audit).
- `convert_to_project`: re-points an inbox request's references at the target project's systems when it is triaged.
- `apply_legacy_link`: the single `external_ref_url` / `external_ref_key` pair older clients still send, kept as a
  delivery reference on the "Other" system.

Design decisions:
- References are not versioned with the request: each is added, changed and removed on its own with its own audit
  event, so a change here does not create a content version.
- A reference needs a key or a URL (or both); the URL is an absolute http(s) link (`schemas.check_web_url`).
- At most `MAX_REFERENCES` per request, so a list stays bounded.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback.enums import ExternalRefRole
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestExternalRef,
    ExternalSystemDefinition,
    ProjectExternalSystem,
)
from app.modules.product_feedback.schemas import ExternalRefOut
from app.modules.product_feedback.vocabularies import EXTERNAL_SYSTEMS, OTHER_NAME, resolve_system

MAX_REFERENCES = 50


def references_by_request(db: Session, request_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ExternalRefOut]]:
    """The references of many requests, oldest first, in a fixed number of statements. A request with none is
    present with an empty list."""
    out: dict[uuid.UUID, list[ExternalRefOut]] = {i: [] for i in request_ids}
    if not out:
        return out
    rows = list(db.scalars(
        select(EnhancementRequestExternalRef).where(EnhancementRequestExternalRef.request_id.in_(list(out)))
        .order_by(EnhancementRequestExternalRef.created_at, EnhancementRequestExternalRef.id)
    ))
    names = EXTERNAL_SYSTEMS.display_names(db, {(r.org_system_id, r.project_system_id) for r in rows})
    for row in rows:
        out[row.request_id].append(reference_out(row, names.get((row.org_system_id, row.project_system_id))))
    return out


def reference_out(row: EnhancementRequestExternalRef, system_name: str | None) -> ExternalRefOut:
    """The API shape of one reference; `system_id` is the id the system picker of the request's tier uses."""
    system_id = row.project_system_id or row.org_system_id
    assert system_id is not None  # the CHECK constraint guarantees one
    return ExternalRefOut(
        id=row.id, request_id=row.request_id, system_id=system_id, system_name=system_name or "", key=row.key,
        url=row.url, role=row.role, created_by=row.created_by, created_at=row.created_at,
    )


def _project_of(db: Session, request: EnhancementRequest) -> Project | None:
    """The request's project (`None` for an inbox request)."""
    return db.get(Project, request.project_id) if request.project_id is not None else None


def _organization_id(db: Session, request: EnhancementRequest) -> uuid.UUID:
    project = _project_of(db, request)
    if project is not None:
        return project.organization_id
    assert request.organization_id is not None  # the scope CHECK guarantees one owner
    return request.organization_id


def add_reference(
    db: Session, request: EnhancementRequest, *, system_id: uuid.UUID, key: str, url: str | None,
    role: ExternalRefRole, actor: User,
) -> EnhancementRequestExternalRef:
    """Adds a reference to `request` (flushed, not committed).

    Raises:
        ValueError: If the request already has `MAX_REFERENCES`, neither a key nor a URL is given, or the system is
            not an enabled one of the request's tier.
    """
    if not key.strip() and not url:
        raise ValueError("A reference needs a key or a link.")
    count = len(db.scalars(select(EnhancementRequestExternalRef.id).where(EnhancementRequestExternalRef.request_id == request.id)).all())
    if count >= MAX_REFERENCES:
        raise ValueError(f"A request can have at most {MAX_REFERENCES} references.")
    org_system_id, project_system_id = resolve_system(db, _organization_id(db, request), _project_of(db, request), system_id)
    row = EnhancementRequestExternalRef(
        request_id=request.id, org_system_id=org_system_id, project_system_id=project_system_id, key=key.strip(),
        url=url or None, role=role, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    return row


def get_reference(db: Session, request: EnhancementRequest, reference_id: uuid.UUID) -> EnhancementRequestExternalRef | None:
    """A reference of `request`, or `None` (also for another request's reference id)."""
    row = db.get(EnhancementRequestExternalRef, reference_id)
    return row if row is not None and row.request_id == request.id else None


def update_reference(
    db: Session, request: EnhancementRequest, row: EnhancementRequestExternalRef, changes: dict,
) -> EnhancementRequestExternalRef:
    """Applies the keys present in `changes` (`system_id`, `key`, `url`, `role`) to a reference.

    Raises:
        ValueError: If the result has neither a key nor a URL, or `system_id` is not usable.
    """
    if "system_id" in changes and changes["system_id"] is not None:
        row.org_system_id, row.project_system_id = resolve_system(
            db, _organization_id(db, request), _project_of(db, request), changes["system_id"],
        )
    if "key" in changes and changes["key"] is not None:
        row.key = changes["key"].strip()
    if "url" in changes:
        row.url = changes["url"] or None
    if "role" in changes and changes["role"] is not None:
        row.role = changes["role"]
    if not row.key and not row.url:
        raise ValueError("A reference needs a key or a link.")
    db.flush()
    return row


def remove_reference(db: Session, row: EnhancementRequestExternalRef) -> None:
    """Deletes a reference (flushed, not committed)."""
    db.delete(row)
    db.flush()


def convert_to_project(db: Session, request: EnhancementRequest, project: Project) -> int:
    """Re-points an inbox request's references at `project`'s systems (the caller has already re-owned the
    request). A system the project hides, or has disabled, is kept as a project-local system of the same name so the
    reference still reads the same.

    Returns:
        How many references were converted.
    """
    rows = list(db.scalars(select(EnhancementRequestExternalRef).where(
        EnhancementRequestExternalRef.request_id == request.id, EnhancementRequestExternalRef.org_system_id.is_not(None),
    )))
    for row in rows:
        org_system = db.get(ExternalSystemDefinition, row.org_system_id)
        assert org_system is not None  # the FK guarantees it
        try:
            _org_id, project_id = resolve_system(db, project.organization_id, project, org_system.id)
        except ValueError:
            project_id = _local_system(db, project, org_system.name).id
        row.org_system_id = None
        row.project_system_id = project_id
    db.flush()
    return len(rows)


def _local_system(db: Session, project: Project, name: str) -> ProjectExternalSystem:
    """The project's own system called `name`, created if it has none."""
    existing = db.scalar(select(ProjectExternalSystem).where(
        ProjectExternalSystem.project_id == project.id, ProjectExternalSystem.org_type_id.is_(None),
        ProjectExternalSystem.name_override == name,
    ))
    return existing if existing is not None else EXTERNAL_SYSTEMS.create_project_local(db, project.id, name)


def apply_legacy_link(db: Session, request: EnhancementRequest, *, changes: dict, actor: User) -> None:
    """Applies the older single delivery link pair as a delivery reference on the "Other" system (flushed, not
    committed): updates the request's existing one, adds one, or removes it when both end up empty. Only the keys
    present in `changes` (`external_ref_url`, `external_ref_key`) are applied; an absent one keeps its value.

    Raises:
        ValueError: If the organisation has no usable "Other" system (it was removed or disabled).
    """
    project = _project_of(db, request)
    organization_id = _organization_id(db, request)
    other = db.scalar(select(ExternalSystemDefinition).where(
        ExternalSystemDefinition.organization_id == organization_id, ExternalSystemDefinition.name == OTHER_NAME,
        ExternalSystemDefinition.is_active.is_(True),
    ))
    if other is None:
        raise ValueError(f"The organisation has no '{OTHER_NAME}' external system; add a reference with a system instead.")
    org_system_id, project_system_id = resolve_system(db, organization_id, project, other.id)
    system_match = (
        EnhancementRequestExternalRef.org_system_id == org_system_id if org_system_id
        else EnhancementRequestExternalRef.project_system_id == project_system_id
    )
    existing = db.scalar(select(EnhancementRequestExternalRef).where(
        EnhancementRequestExternalRef.request_id == request.id, EnhancementRequestExternalRef.role == ExternalRefRole.DELIVERY,
        system_match,
    ).order_by(EnhancementRequestExternalRef.created_at))
    url = changes["external_ref_url"] if "external_ref_url" in changes else (existing.url if existing else None)
    key = changes["external_ref_key"] if "external_ref_key" in changes else (existing.key if existing else "")
    key = (key or "").strip()
    if not key and not url:
        if existing is not None:
            db.delete(existing)
    elif existing is not None:
        existing.key, existing.url = key, url or None
    else:
        add_reference(db, request, system_id=other.id, key=key, url=url, role=ExternalRefRole.DELIVERY, actor=actor)
    db.flush()
