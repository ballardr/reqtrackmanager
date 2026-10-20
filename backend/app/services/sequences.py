"""
Module: services.sequences

The generic per-project (or, for an organisation-scoped record,
per-organisation), per-artefact-type unique-code generator every *new* identified artefact
type in the future-modules roadmap uses, replacing the
`next_<type>_seq`-column-on-`Project` plus per-service `generate_unique_code`
pair that `services.requirements`/`services.actions` each currently
duplicate (`Project.next_requirement_seq`/`next_action_seq`). Those two are
deliberately left untouched by this module — this is additive
infrastructure for new artefact types going forward, not a migration of the
existing two.

`artefact_type` is a plain string, validated here against
`app.modules.registry.get_all_registered_artefact_types()` — the same
merged core-plus-every-module set `services.relationships.create_link`
already validates `ArtefactLink.source_type`/`target_type` against.
**Corrected 2026-09-21** from an
earlier shape that took a `models.enums.ArtefactType` enum member, which
required a core-file hand-edit for every new artefact-generating module —
see `models.sequence.ProjectSequenceCounter`'s own docstring for the full
story.

Scope: a record owned by a project is numbered from that project's counter;
a record owned by an organisation (a Persona shared across projects, say) from
the organisation's own counter (`OrganizationSequenceCounter`). A type that
exists at both scopes therefore has independent sequences, and a code is unique
per owner, never globally.

Concurrency: `_next_sequence` locks the owning project or organisation row
(`services.rbac.lock_project_for_update` / `lock_organization_for_update`,
reused as-is) before reading and
advancing the counter, so two concurrent creations of the same artefact
type in the same project can never observe and increment the same
pre-update value — the second transaction blocks on the lock until the
first commits, then reads the already-advanced counter. See
`lock_project_for_update`'s own docstring for the general race this closes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.sequence import OrganizationSequenceCounter, ProjectSequenceCounter
from app.services.rbac import lock_organization_for_update, lock_project_for_update


def _next_sequence(db: Session, owner: Project | Organization, artefact_type: str) -> int:
    """Returns the next sequence number for `(owner, artefact_type)`,
    advancing the counter so it is never reused, creating the counter row
    on first use. Locks `owner` first — see this module's docstring for
    why. `owner` is the project for a project-scoped record and the
    organisation for an organisation-scoped one."""
    if isinstance(owner, Organization):
        lock_organization_for_update(db, owner.id)
        counter = db.scalar(
            select(OrganizationSequenceCounter).where(
                OrganizationSequenceCounter.organization_id == owner.id,
                OrganizationSequenceCounter.artefact_type == artefact_type,
            )
        )
        if counter is None:
            counter = OrganizationSequenceCounter(organization_id=owner.id, artefact_type=artefact_type, next_seq=1)
            db.add(counter)
            db.flush()
    else:
        lock_project_for_update(db, owner.id)
        counter = db.scalar(
            select(ProjectSequenceCounter).where(
                ProjectSequenceCounter.project_id == owner.id,
                ProjectSequenceCounter.artefact_type == artefact_type,
            )
        )
        if counter is None:
            counter = ProjectSequenceCounter(project_id=owner.id, artefact_type=artefact_type, next_seq=1)
            db.add(counter)
            db.flush()
    seq = counter.next_seq
    counter.next_seq = seq + 1
    return seq


def generate_unique_code(db: Session, owner: Project | Organization, artefact_type: str, prefix: str) -> str:
    """Builds a unique, never-reused artefact identifier for `owner`,
    e.g. `generate_unique_code(db, project, "decision", "DEC")` ->
    `"DEC-003"` (mirrors `services.requirements.generate_unique_code`'s
    `{prefix}-{seq:03d}` format exactly, for consistency with existing
    codes). Pass the organisation for an organisation-scoped record.

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
    return f"{prefix}-{seq:03d}"


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
