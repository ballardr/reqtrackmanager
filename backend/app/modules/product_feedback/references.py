"""
Module: modules.product_feedback.references

A request's external references: pointers to the same work in outside tools (a Jira epic, a ServiceNow ticket), each
with the system it lives in and a role (`origin`: where the request came from; `delivery`: where it is built).

The data is the shared `models.external_reference.ExternalReference` (type `enhancement_request`) and the rules are
`services.external_references`; this module only adapts a request to them.

Responsibilities:
- `references_by_request`: many requests' references with their system names in a fixed number of statements.
- `add_reference` / `update_reference` / `remove_reference`: the gated bodies' data changes (no commit, no audit).
- `convert_to_project`: re-points an inbox request's references at the target project's systems when it is triaged.
- `apply_legacy_link`: the single `external_ref_url` / `external_ref_key` pair older clients still send, kept as a
  delivery reference on the "Other" system.

Design decisions:
- References are not versioned with the request: each is added, changed and removed on its own with its own audit
  event, so a change here does not create a content version.
- A reference needs a key or a URL (or both); the URL is an absolute http(s) link.
- At most `MAX_REFERENCES` per request, so a list stays bounded.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.external_reference import ExternalReference
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback.enums import ExternalRefRole
from app.modules.product_feedback.models import EnhancementRequest
from app.modules.product_feedback.schemas import ExternalRefOut
from app.modules.product_feedback.service import REQUEST_ARTEFACT_TYPE
from app.services import external_references as core
from app.services.external_references import MAX_REFERENCES, OTHER_NAME

__all__ = [
    "MAX_REFERENCES", "add_reference", "apply_legacy_link", "convert_to_project", "get_reference",
    "references_by_request", "remove_reference", "update_reference",
]


def references_by_request(db: Session, request_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ExternalRefOut]]:
    """The references of many requests, oldest first, in a fixed number of statements. A request with none is
    present with an empty list."""
    found = core.references_for_records(db, REQUEST_ARTEFACT_TYPE, request_ids)
    return {request_id: [_request_out(r) for r in refs] for request_id, refs in found.items()}


def _request_out(ref: core.ExternalReferenceOut) -> ExternalRefOut:
    """The request API shape of a shared reference (an unset role reads as `delivery`, the module's default)."""
    return ExternalRefOut(
        id=ref.id, request_id=ref.artefact_id, system_id=ref.system_id, system_name=ref.system_name, key=ref.key,
        url=ref.url, link=ref.link, role=ref.role or ExternalRefRole.DELIVERY, created_by=ref.created_by,
        created_at=ref.created_at,
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
) -> ExternalReference:
    """Adds a reference to `request` (flushed, not committed).

    Raises:
        ValueError: If the request already has `MAX_REFERENCES`, neither a key nor a URL is given, or the system is
            not an enabled one of the request's tier.
    """
    return core.add_reference(
        db, artefact_type=REQUEST_ARTEFACT_TYPE, artefact_id=request.id, organization_id=_organization_id(db, request),
        project=_project_of(db, request), system_id=system_id, key=key, url=url, role=role, actor_id=actor.id,
    )


def get_reference(db: Session, request: EnhancementRequest, reference_id: uuid.UUID) -> ExternalReference | None:
    """A reference of `request`, or `None` (also for another request's reference id)."""
    return core.get_reference(db, REQUEST_ARTEFACT_TYPE, request.id, reference_id)


def update_reference(
    db: Session, request: EnhancementRequest, row: ExternalReference, changes: dict,
) -> ExternalReference:
    """Applies the keys present in `changes` (`system_id`, `key`, `url`, `role`) to a reference. A `role` of `None`
    keeps the current one (a request's reference always has a role).

    Raises:
        ValueError: If the result has neither a key nor a URL, or `system_id` is not usable.
    """
    changes = {k: v for k, v in changes.items() if not (k == "role" and v is None)}
    return core.update_reference(db, row, _project_of(db, request), changes)


def remove_reference(db: Session, row: ExternalReference) -> None:
    """Deletes a reference (flushed, not committed)."""
    core.remove_reference(db, row)


def convert_to_project(db: Session, request: EnhancementRequest, project: Project) -> int:
    """Re-points an inbox request's references at `project`'s systems (the caller has already re-owned the
    request). A system the project hides, or has disabled, is kept as a project-local system of the same name so the
    reference still reads the same.

    Returns:
        How many references were converted.
    """
    return core.convert_record_to_project(db, REQUEST_ARTEFACT_TYPE, request.id, project)


def apply_legacy_link(db: Session, request: EnhancementRequest, *, changes: dict, actor: User) -> None:
    """Applies the older single delivery link pair as a delivery reference on the "Other" system (flushed, not
    committed): updates the request's existing one, adds one, or removes it when both end up empty. Only the keys
    present in `changes` (`external_ref_url`, `external_ref_key`) are applied; an absent one keeps its value.

    Raises:
        ValueError: If the organisation has no usable "Other" system (it was removed or disabled).
    """
    project = _project_of(db, request)
    organization_id = _organization_id(db, request)
    other_id = core.other_system_id(db, organization_id)
    if other_id is None:
        raise ValueError(f"The organisation has no '{OTHER_NAME}' external system; add a reference with a system instead.")
    org_system_id, project_system_id = core.resolve_system(db, organization_id, project, other_id)
    system_match = (
        ExternalReference.org_system_id == org_system_id if org_system_id
        else ExternalReference.project_system_id == project_system_id
    )
    existing = db.scalar(select(ExternalReference).where(
        ExternalReference.artefact_type == REQUEST_ARTEFACT_TYPE, ExternalReference.artefact_id == request.id,
        ExternalReference.role == ExternalRefRole.DELIVERY, system_match,
    ).order_by(ExternalReference.created_at))
    url = changes["external_ref_url"] if "external_ref_url" in changes else (existing.url if existing else None)
    key = changes["external_ref_key"] if "external_ref_key" in changes else (existing.key if existing else "")
    key = (key or "").strip()
    if not key and not url:
        if existing is not None:
            db.delete(existing)
    elif existing is not None:
        existing.key, existing.url = key, url or None
    else:
        add_reference(db, request, system_id=other_id, key=key, url=url, role=ExternalRefRole.DELIVERY, actor=actor)
    db.flush()
