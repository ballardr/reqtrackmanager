"""
Module: services.sequences

The generic unique-code generator for every artefact type: per project, or per organisation for an organisation-owned
record, per artefact type.

Design decisions:
- `artefact_type` is a plain string validated against `app.modules.registry.get_all_registered_artefact_types()` (the
  set `services.relationships.create_link` uses), so a new module needs no core enum edit
  (see `models.sequence.ProjectSequenceCounter`).
- A project-owned record uses the project's counter; an organisation-owned record (a shared Persona) uses
  `OrganizationSequenceCounter`. A type at both scopes has independent sequences and a code is unique per owner.
- Concurrency: `_next_sequence` locks the owning row (`services.rbac.lock_project_for_update` /
  `lock_organization_for_update`) before reading and advancing the counter, so concurrent creations never read the same
  value.
- The requirement and action services keep their own `next_*_seq` columns on `Project`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.sequence import OrganizationSequenceCounter, ProjectSequenceCounter
from app.services.code_prefixes import effective_prefix
from app.services.rbac import lock_organization_for_update, lock_project_for_update


def _next_sequence(db: Session, owner: Project | Organization, artefact_type: str) -> int:
    """Returns the next sequence number for `(owner, artefact_type)`,
    advancing the counter so it is never reused, creating the counter row
    on first use. Locks `owner` first — see this module's docstring for
    why. `owner` is the project for a project-scoped record and the
    organisation for an organisation-scoped one."""
    if isinstance(owner, Organization):
        lock_organization_for_update(db, owner.id)
        org_counter = db.scalar(
            select(OrganizationSequenceCounter).where(
                OrganizationSequenceCounter.organization_id == owner.id,
                OrganizationSequenceCounter.artefact_type == artefact_type,
            )
        )
        if org_counter is None:
            org_counter = OrganizationSequenceCounter(organization_id=owner.id, artefact_type=artefact_type, next_seq=1)
            db.add(org_counter)
            db.flush()
        seq = org_counter.next_seq
        org_counter.next_seq = seq + 1
        return seq
    else:
        lock_project_for_update(db, owner.id)
        project_counter = db.scalar(
            select(ProjectSequenceCounter).where(
                ProjectSequenceCounter.project_id == owner.id,
                ProjectSequenceCounter.artefact_type == artefact_type,
            )
        )
        if project_counter is None:
            project_counter = ProjectSequenceCounter(project_id=owner.id, artefact_type=artefact_type, next_seq=1)
            db.add(project_counter)
            db.flush()
        seq = project_counter.next_seq
        project_counter.next_seq = seq + 1
        return seq


def generate_unique_code(db: Session, owner: Project | Organization, artefact_type: str, prefix: str) -> str:
    """Builds a unique, never-reused artefact identifier for `owner`,
    e.g. `generate_unique_code(db, project, "decision", "DEC")` ->
    `"DEC-003"` (mirrors `services.requirements.generate_unique_code`'s
    `{prefix}-{seq:03d}` format exactly, for consistency with existing
    codes). Pass the organisation for an organisation-scoped record.

    `prefix` is the type's built-in default: the prefix actually used is the one the
    owner's project, a parent project or the organisation chose for the type
    (`services.code_prefixes.effective_prefix`), so no call site names an override.
    The counter is per type, not per prefix, so a change never reuses a number.

    Raises:
        ValueError: If `artefact_type` isn't a currently-registered
            artefact type (core built-in or a registered module's own
            `ModuleDefinition.artefact_types` entry) — catches a typo'd or
            stale type string the same way `create_link` catches one for
            `ArtefactLink`, rather than silently starting a counter for a
            value nothing else will ever recognise.
    """
    from app.modules.registry import get_all_registered_artefact_types

    if artefact_type not in get_all_registered_artefact_types():
        raise ValueError(f"{artefact_type!r} is not a registered artefact type.")
    seq = _next_sequence(db, owner, artefact_type)
    return f"{effective_prefix(db, owner, artefact_type, prefix)}-{seq:03d}"


def code_owner(
    db: Session, *, is_org_scope: bool, organization_id: uuid.UUID, project_id: uuid.UUID | None
) -> Project | Organization:
    """The row whose counter numbers a record of a type that exists at both scopes: the
    organisation for an organisation-scoped record, otherwise the project.

    Raises:
        ValueError: If the owner does not exist (a project-scoped record without a project).
    """
    owner = db.get(Organization, organization_id) if is_org_scope or project_id is None else db.get(Project, project_id)
    if owner is None:
        raise ValueError("The record's owning project or organisation does not exist.")
    return owner
