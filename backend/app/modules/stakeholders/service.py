"""
Module: modules.stakeholders.service

Business logic for the Stakeholders & Personas module, Phase 1.1 (Persona):

- Persona CRUD as an identity row plus temporal `PersonaVersion` snapshots
  (`create_persona`, `apply_persona_new_version`), archive/unarchive, and the
  `Draft -> Active -> Retired` lifecycle (`transition_persona`).
- The Persona type vocabulary (`PERSONA_TYPES`, a `TypeVocabulary`) and
  resolving a persona's type reference by scope.
- Weight resolution (`resolve_persona_weight`): the project's own override,
  then the nearest ancestor project's, then the persona's own weight, then
  `None` (equal weighting).
- `persona_scoring_targets`, this module's `scoring_target_providers` entry
  for Module 1's per-persona Pain Point scoring.
- `resolve_persona_file_project_id`, the file-ownership hook.

Design decisions:
- No content lock: with no approval gate (Phase 0 resolution 6) a persona
  stays editable in every status, and each edit is a new version.
- Only `ACTIVE` personas are offered as scoring targets, so an unvetted
  draft cannot skew a weighted roll-up (Decided by: Agent).
- A persona's own weight lives on its version, not the identity row, so a
  re-weighting is part of its history.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import ScoringTarget, is_module_subcomponent_enabled
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus
from app.modules.stakeholders.models import (
    Persona,
    PersonaComment,
    PersonaCommentFile,
    PersonaFile,
    PersonaTypeDefinition,
    PersonaVersion,
    ProjectPersonaType,
    ProjectPersonaWeight,
)
from app.modules.stakeholders.type_vocabulary import TypeVocabulary
from app.services.audit import log_event
from app.services.project_hierarchy import get_ancestor_chain

STAKEHOLDERS_MODULE_KEY = "stakeholders"
PERSONA_ARTEFACT_TYPE = "persona"

# §10.2 names no persona categories, so these are Agent defaults (Phase 0
# resolution 3); all are org-editable.
DEFAULT_PERSONA_TYPES: tuple[str, ...] = ("Primary", "Secondary", "Negative")

PERSONA_TYPES = TypeVocabulary(
    label="Persona type",
    org_model=PersonaTypeDefinition,
    project_model=ProjectPersonaType,
    default_names=DEFAULT_PERSONA_TYPES,
    org_type_in_use=lambda db, type_id: db.scalar(
        select(PersonaVersion.id).where(PersonaVersion.org_type_id == type_id).limit(1)
    ) is not None,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(PersonaVersion.id).where(PersonaVersion.project_type_id == type_id).limit(1)
    ) is not None,
)

# Versioned content fields `apply_persona_new_version` carries forward.
PERSONA_CONTENT_FIELDS: tuple[str, ...] = (
    "name", "description", "org_type_id", "project_type_id", "role_title", "goals", "needs", "behaviours",
    "context_environment", "skills_proficiency", "frequency_of_use", "constraints", "weight", "status",
    "owner_id", "champion_id",
)

PERSONA_ALLOWED_TRANSITIONS: dict[PersonaStatus, frozenset[PersonaStatus]] = {
    PersonaStatus.DRAFT: frozenset({PersonaStatus.ACTIVE, PersonaStatus.RETIRED}),
    PersonaStatus.ACTIVE: frozenset({PersonaStatus.RETIRED}),
    PersonaStatus.RETIRED: frozenset({PersonaStatus.ACTIVE}),
}


def get_current_persona_version(db: Session, persona_id: uuid.UUID) -> PersonaVersion:
    """Returns the current (`valid_to IS NULL`) version of a persona.

    Raises:
        ValueError: If none exists (a data-integrity bug).
    """
    version = db.scalar(
        select(PersonaVersion).where(PersonaVersion.persona_id == persona_id, PersonaVersion.valid_to.is_(None))
    )
    if version is None:
        raise ValueError(f"Persona {persona_id} has no current version.")
    return version


def resolve_persona_type_refs(
    db: Session, persona_scope: PersonaScope, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    type_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolves a payload's `persona_type_id` to `(org_type_id,
    project_type_id)` for a persona of `persona_scope`.

    An org persona must use an active org type; a project persona uses the
    project's effective list (`TypeVocabulary.get_or_create_project_type`)
    and the type must be enabled there.

    Raises:
        ValueError: If `type_id` is not usable for this scope/project.
    """
    if type_id is None:
        return None, None
    if persona_scope == PersonaScope.ORGANIZATION:
        org_type = db.get(PersonaTypeDefinition, type_id)
        if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
            raise ValueError("This is not a valid Persona type for this organisation.")
        return org_type.id, None
    assert project_id is not None
    row = PERSONA_TYPES.get_or_create_project_type(db, project_id, organization_id, type_id)
    if not row.is_enabled:
        raise ValueError("This Persona type is disabled for this project.")
    return None, row.id


def create_persona(
    db: Session, *, scope: PersonaScope, organization_id: uuid.UUID, project_id: uuid.UUID | None, creator: User,
    **content: Any,
) -> Persona:
    """Creates a persona and its version 1 in `DRAFT`.

    Args:
        scope: Org or project scope.
        organization_id: The owning organisation (stored only for org scope).
        project_id: The owning project (stored only for project scope).
        creator: The acting user.
        **content: Any `PERSONA_CONTENT_FIELDS` except `status`; `name` is
            required.
    """
    persona = Persona(
        scope=scope,
        organization_id=organization_id if scope == PersonaScope.ORGANIZATION else None,
        project_id=project_id if scope == PersonaScope.PROJECT else None,
        creator_id=creator.id,
    )
    db.add(persona)
    db.flush()
    now = datetime.now(UTC)
    content = {k: v for k, v in content.items() if k in PERSONA_CONTENT_FIELDS and k != "status"}
    db.add(PersonaVersion(
        persona_id=persona.id, version_number=1, valid_from=now, valid_to=None, status=PersonaStatus.DRAFT,
        change_note="Initial creation.", created_by=creator.id, created_at=now, **content,
    ))
    db.flush()
    return persona


def apply_persona_new_version(
    db: Session, persona: Persona, current_version: PersonaVersion, actor: User, *, changes: dict[str, Any],
    change_note: str = "",
) -> PersonaVersion:
    """Closes `current_version` and inserts a new one with `changes` applied
    over the carried-forward content. A key present in `changes` is applied
    even when `None`, so nullable fields (weight, owner, champion, type) can
    be cleared; absent keys are carried forward."""
    now = datetime.now(UTC)
    current_version.valid_to = now
    values = {f: getattr(current_version, f) for f in PERSONA_CONTENT_FIELDS}
    values.update({k: v for k, v in changes.items() if k in PERSONA_CONTENT_FIELDS})
    new_version = PersonaVersion(
        persona_id=persona.id, version_number=current_version.version_number + 1, valid_from=now, valid_to=None,
        change_note=change_note, created_by=actor.id, created_at=now, **values,
    )
    db.add(new_version)
    db.flush()
    return new_version


def archive_persona(db: Session, persona: Persona, actor: User) -> None:
    """Soft-archives a persona."""
    persona.is_archived = True
    persona.archived_at = datetime.now(UTC)
    persona.archived_by = actor.id


def unarchive_persona(db: Session, persona: Persona) -> None:
    """Reverses `archive_persona`."""
    persona.is_archived = False
    persona.archived_at = None
    persona.archived_by = None


def transition_persona(
    db: Session, persona: Persona, current_version: PersonaVersion, new_status: PersonaStatus, actor: User,
    *, action: str, comment: str | None = None,
) -> PersonaVersion:
    """Applies a lifecycle transition as a new version and audit-logs it.

    Raises:
        ValueError: If `new_status` is not reachable from the current status.
    """
    if new_status not in PERSONA_ALLOWED_TRANSITIONS[current_version.status]:
        raise ValueError(f"Cannot move a Persona from '{current_version.status.value}' to '{new_status.value}'.")
    new_version = apply_persona_new_version(
        db, persona, current_version, actor, changes={"status": new_status}, change_note=comment or "",
    )
    log_event(
        db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action=action, actor_id=actor.id,
        organization_id=persona.organization_id, project_id=persona.project_id,
        detail={"comment": comment} if comment else None,
    )
    return new_version


# --- Weights -----------------------------------------------------------------


def resolve_persona_weight_with_source(
    db: Session, project_id: uuid.UUID, persona_id: uuid.UUID, own_weight: float | None
) -> tuple[float | None, str]:
    """A persona's effective weight in `project_id` and the tier it came from:
    the project's own override (`"project"`), else the nearest ancestor
    project's (`"ancestor_project"`), else `own_weight` (`"persona"`), else
    `None` (`"none"`, equal weighting). Cycle-safe via `get_ancestor_chain`."""
    chain = [project_id, *(p.id for p in reversed(get_ancestor_chain(db, project_id)))]
    overrides = {
        row.project_id: row.weight
        for row in db.scalars(
            select(ProjectPersonaWeight).where(
                ProjectPersonaWeight.persona_id == persona_id, ProjectPersonaWeight.project_id.in_(chain)
            )
        ).all()
    }
    for pid in chain:
        if pid in overrides:
            return overrides[pid], "project" if pid == project_id else "ancestor_project"
    return own_weight, "persona" if own_weight is not None else "none"


def resolve_persona_weight(db: Session, project_id: uuid.UUID, persona_id: uuid.UUID, own_weight: float | None) -> float | None:
    """The effective weight alone; see `resolve_persona_weight_with_source`."""
    return resolve_persona_weight_with_source(db, project_id, persona_id, own_weight)[0]


def set_project_persona_weight(db: Session, project_id: uuid.UUID, persona_id: uuid.UUID, weight: float) -> ProjectPersonaWeight:
    """Creates or updates a project's weight override for a persona.

    Raises:
        ValueError: If `weight` is not positive.
    """
    if weight <= 0:
        raise ValueError("A persona weight must be greater than zero.")
    row = db.scalar(
        select(ProjectPersonaWeight).where(
            ProjectPersonaWeight.project_id == project_id, ProjectPersonaWeight.persona_id == persona_id
        )
    )
    if row is None:
        row = ProjectPersonaWeight(project_id=project_id, persona_id=persona_id, weight=weight)
        db.add(row)
    else:
        row.weight = weight
    db.flush()
    return row


def clear_project_persona_weight(db: Session, project_id: uuid.UUID, persona_id: uuid.UUID) -> bool:
    """Removes a project's override. Returns whether one existed."""
    row = db.scalar(
        select(ProjectPersonaWeight).where(
            ProjectPersonaWeight.project_id == project_id, ProjectPersonaWeight.persona_id == persona_id
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def list_project_visible_personas(db: Session, project: Project, *, include_archived: bool = False) -> list[Persona]:
    """The personas a project can use: its own plus its organisation's."""
    query = select(Persona).where(
        or_(
            (Persona.scope == PersonaScope.PROJECT) & (Persona.project_id == project.id),
            (Persona.scope == PersonaScope.ORGANIZATION) & (Persona.organization_id == project.organization_id),
        )
    )
    if not include_archived:
        query = query.where(Persona.is_archived.is_(False))
    return list(db.scalars(query.order_by(Persona.created_at)).all())


def persona_scoring_targets(db: Session, project_id: uuid.UUID) -> list[ScoringTarget]:
    """`ModuleDefinition.scoring_target_providers["persona"]`: the project's
    visible, non-archived personas with their effective weights. Returns
    `[]` when the `persona` sub-component is off for the project; only
    `ACTIVE` personas are flagged `is_active`."""
    project = db.get(Project, project_id)
    if project is None or not is_module_subcomponent_enabled(db, project_id, STAKEHOLDERS_MODULE_KEY, "persona"):
        return []
    targets: list[ScoringTarget] = []
    for persona in list_project_visible_personas(db, project):
        version = get_current_persona_version(db, persona.id)
        targets.append(ScoringTarget(
            id=persona.id, label=version.name,
            weight=resolve_persona_weight(db, project_id, persona.id, version.weight),
            is_active=version.status == PersonaStatus.ACTIVE,
        ))
    return targets


# --- File ownership ----------------------------------------------------------


def resolve_persona_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project of the **project-scoped**
    persona it is attached to (directly or via a comment). Org personas'
    files are org shared resources and never resolved here."""
    direct = db.scalar(select(PersonaFile).where(PersonaFile.file_id == file_id))
    if direct is not None:
        persona = db.get(Persona, direct.persona_id)
        return persona.project_id if persona is not None else None
    via_comment = db.scalar(select(PersonaCommentFile).where(PersonaCommentFile.file_id == file_id))
    if via_comment is not None:
        comment = db.get(PersonaComment, via_comment.comment_id)
        persona = db.get(Persona, comment.persona_id) if comment is not None else None
        return persona.project_id if persona is not None else None
    return None
