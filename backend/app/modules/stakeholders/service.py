"""
Module: modules.stakeholders.service

Business logic for the Stakeholders & Personas module, Phase 1.1 (Persona)
and Phase 1.2 (Stakeholder — second half of this file):

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
- Stakeholder CRUD/lifecycle with the same version-table shape, the
  Influence × Interest grid read-out (`grid_quadrant`, `suggest_cadence`),
  the Stakeholder → Persona "represents" links, and `erase_stakeholder`
  (hard delete of one person's data, Phase 0 resolution 15).

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
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.registry import ScoringTarget, is_module_subcomponent_enabled
from app.modules.stakeholders.enums import (
    PersonaScope,
    PersonaStatus,
    StakeholderScope,
    StakeholderStatus,
    TargetCadence,
)
from app.modules.stakeholders.models import (
    Persona,
    PersonaTypeDefinition,
    PersonaVersion,
    ProjectPersonaType,
    ProjectPersonaWeight,
    ProjectStakeholderType,
    Stakeholder,
    StakeholderComment,
    StakeholderCommentFile,
    StakeholderFile,
    StakeholderTypeDefinition,
    StakeholderVersion,
)
from app.modules.stakeholders.scoring import INFLUENCE_AXIS_KEY, INTEREST_AXIS_KEY, STAKEHOLDER_SCORING_SCHEME_KEY
from app.modules.stakeholders.type_vocabulary import TypeVocabulary
from app.services.audit import log_event
from app.services.files import delete_file
from app.services.project_hierarchy import get_ancestor_chain
from app.services.relationships import create_link, delete_link, get_all_links, get_link_between

STAKEHOLDERS_MODULE_KEY = "stakeholders"
PERSONA_ARTEFACT_TYPE = "persona"
STAKEHOLDER_ARTEFACT_TYPE = "stakeholder"

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


def resolve_type_refs(
    db: Session, vocabulary: TypeVocabulary, *, is_org_scope: bool, organization_id: uuid.UUID,
    project_id: uuid.UUID | None, type_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolves a payload's type id to `(org_type_id, project_type_id)` for an
    artefact of the given scope, against `vocabulary`.

    An org artefact must use an active org type; a project artefact uses the
    project's effective list (`TypeVocabulary.get_or_create_project_type`)
    and the type must be enabled there.

    Raises:
        ValueError: If `type_id` is not usable for this scope/project.
    """
    label = vocabulary.label
    if type_id is None:
        return None, None
    if is_org_scope:
        org_type = db.get(vocabulary.org_model, type_id)
        if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
            raise ValueError(f"This is not a valid {label} for this organisation.")
        return org_type.id, None
    assert project_id is not None
    row = vocabulary.get_or_create_project_type(db, project_id, organization_id, type_id)
    if not row.is_enabled:
        raise ValueError(f"This {label} is disabled for this project.")
    return None, row.id


def resolve_persona_type_refs(
    db: Session, persona_scope: PersonaScope, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    type_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """`resolve_type_refs` for a persona of `persona_scope`."""
    return resolve_type_refs(
        db, PERSONA_TYPES, is_org_scope=persona_scope == PersonaScope.ORGANIZATION, organization_id=organization_id,
        project_id=project_id, type_id=type_id,
    )


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


def archive_record(db: Session, record: Persona | Stakeholder, actor: User) -> None:
    """Soft-archives a persona or stakeholder."""
    record.is_archived = True
    record.archived_at = datetime.now(UTC)
    record.archived_by = actor.id


def unarchive_record(db: Session, record: Persona | Stakeholder) -> None:
    """Reverses `archive_record`."""
    record.is_archived = False
    record.archived_at = None
    record.archived_by = None


archive_persona = archive_record
unarchive_persona = unarchive_record


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
    from app.modules.stakeholders._attachments import resolve_file_project_id
    from app.modules.stakeholders._shared import PERSONA_ATTACHMENTS

    return resolve_file_project_id(db, PERSONA_ATTACHMENTS, Persona, file_id)


# =============================================================================
# Stakeholder (Phase 1.2)
# =============================================================================

# §10.2's list (Phase 0 resolution 3); all are org-editable.
DEFAULT_STAKEHOLDER_TYPES: tuple[str, ...] = (
    "Customer", "End user", "Operator", "Maintainer", "Service engineer", "Business owner", "Project sponsor",
    "Regulator", "Supplier", "Internal engineering team", "Support organisation",
)

STAKEHOLDER_TYPES = TypeVocabulary(
    label="Stakeholder type",
    org_model=StakeholderTypeDefinition,
    project_model=ProjectStakeholderType,
    default_names=DEFAULT_STAKEHOLDER_TYPES,
    org_type_in_use=lambda db, type_id: db.scalar(
        select(StakeholderVersion.id).where(StakeholderVersion.org_type_id == type_id).limit(1)
    ) is not None,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(StakeholderVersion.id).where(StakeholderVersion.project_type_id == type_id).limit(1)
    ) is not None,
)

# Versioned content fields `apply_stakeholder_new_version` carries forward.
STAKEHOLDER_CONTENT_FIELDS: tuple[str, ...] = (
    "name", "description", "org_type_id", "project_type_id", "role", "organisation_group", "interests",
    "responsibilities", "goals_needs", "priorities", "constraints", "workflows_scenarios", "contact_info",
    "target_cadence", "availability_constraints", "influence_level_id", "interest_level_id", "status", "owner_id",
    "user_id",
)

STAKEHOLDER_ALLOWED_TRANSITIONS: dict[StakeholderStatus, frozenset[StakeholderStatus]] = {
    StakeholderStatus.DRAFT: frozenset({StakeholderStatus.ACTIVE, StakeholderStatus.RETIRED}),
    StakeholderStatus.ACTIVE: frozenset({StakeholderStatus.RETIRED}),
    StakeholderStatus.RETIRED: frozenset({StakeholderStatus.ACTIVE}),
}

GridQuadrant = Literal["manage_closely", "keep_satisfied", "keep_informed", "monitor"]

# Phase 0 addendum 2, resolution 21 (default mapping Decided by: Agent).
CADENCE_HINT_BY_QUADRANT: dict[GridQuadrant, TargetCadence] = {
    "manage_closely": TargetCadence.MONTHLY,
    "keep_satisfied": TargetCadence.QUARTERLY,
    "keep_informed": TargetCadence.QUARTERLY,
    "monitor": TargetCadence.AD_HOC,
}

_REPRESENTS_FORWARD = "Represents"
_REPRESENTS_REVERSE = "Is represented by"


def get_current_stakeholder_version(db: Session, stakeholder_id: uuid.UUID) -> StakeholderVersion:
    """Returns the current (`valid_to IS NULL`) version of a stakeholder.

    Raises:
        ValueError: If none exists (a data-integrity bug).
    """
    version = db.scalar(
        select(StakeholderVersion).where(
            StakeholderVersion.stakeholder_id == stakeholder_id, StakeholderVersion.valid_to.is_(None)
        )
    )
    if version is None:
        raise ValueError(f"Stakeholder {stakeholder_id} has no current version.")
    return version


def resolve_stakeholder_type_refs(
    db: Session, scope: StakeholderScope, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    type_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """`resolve_type_refs` for a stakeholder of `scope`."""
    return resolve_type_refs(
        db, STAKEHOLDER_TYPES, is_org_scope=scope == StakeholderScope.ORGANIZATION, organization_id=organization_id,
        project_id=project_id, type_id=type_id,
    )


def validate_scoring_levels(
    db: Session, organization_id: uuid.UUID, *, influence_level_id: uuid.UUID | None,
    interest_level_id: uuid.UUID | None,
) -> None:
    """Checks each given level is a level of this organisation on the right
    axis of the `stakeholder` scheme.

    Raises:
        ValueError: If a level belongs to another organisation, scheme or axis.
    """
    for level_id, axis_key in ((influence_level_id, INFLUENCE_AXIS_KEY), (interest_level_id, INTEREST_AXIS_KEY)):
        if level_id is None:
            continue
        level = db.get(ScoringLevel, level_id)
        if (
            level is None or level.organization_id != organization_id
            or level.scheme_key != STAKEHOLDER_SCORING_SCHEME_KEY or level.axis_key != axis_key
        ):
            raise ValueError(f"This is not a valid {axis_key} level for this organisation.")


def create_stakeholder(
    db: Session, *, scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    creator: User, **content: Any,
) -> Stakeholder:
    """Creates a stakeholder and its version 1 in `DRAFT`.

    Args:
        scope: Org or project scope.
        organization_id: The owning organisation (stored only for org scope).
        project_id: The owning project (stored only for project scope).
        creator: The acting user.
        **content: Any `STAKEHOLDER_CONTENT_FIELDS` except `status`; `name`
            is required.
    """
    stakeholder = Stakeholder(
        scope=scope,
        organization_id=organization_id if scope == StakeholderScope.ORGANIZATION else None,
        project_id=project_id if scope == StakeholderScope.PROJECT else None,
        creator_id=creator.id,
    )
    db.add(stakeholder)
    db.flush()
    now = datetime.now(UTC)
    content = {k: v for k, v in content.items() if k in STAKEHOLDER_CONTENT_FIELDS and k != "status"}
    db.add(StakeholderVersion(
        stakeholder_id=stakeholder.id, version_number=1, valid_from=now, valid_to=None,
        status=StakeholderStatus.DRAFT, change_note="Initial creation.", created_by=creator.id, created_at=now,
        **content,
    ))
    db.flush()
    return stakeholder


def apply_stakeholder_new_version(
    db: Session, stakeholder: Stakeholder, current_version: StakeholderVersion, actor: User, *,
    changes: dict[str, Any], change_note: str = "",
) -> StakeholderVersion:
    """Closes `current_version` and inserts a new one with `changes` applied
    over the carried-forward content. A key present in `changes` is applied
    even when `None`, so nullable fields can be cleared; absent keys are
    carried forward."""
    now = datetime.now(UTC)
    current_version.valid_to = now
    values = {f: getattr(current_version, f) for f in STAKEHOLDER_CONTENT_FIELDS}
    values.update({k: v for k, v in changes.items() if k in STAKEHOLDER_CONTENT_FIELDS})
    new_version = StakeholderVersion(
        stakeholder_id=stakeholder.id, version_number=current_version.version_number + 1, valid_from=now,
        valid_to=None, change_note=change_note, created_by=actor.id, created_at=now, **values,
    )
    db.add(new_version)
    db.flush()
    return new_version


def transition_stakeholder(
    db: Session, stakeholder: Stakeholder, current_version: StakeholderVersion, new_status: StakeholderStatus,
    actor: User, *, action: str, comment: str | None = None,
) -> StakeholderVersion:
    """Applies a lifecycle transition as a new version and audit-logs it.

    Raises:
        ValueError: If `new_status` is not reachable from the current status.
    """
    if new_status not in STAKEHOLDER_ALLOWED_TRANSITIONS[current_version.status]:
        raise ValueError(
            f"Cannot move a Stakeholder from '{current_version.status.value}' to '{new_status.value}'."
        )
    new_version = apply_stakeholder_new_version(
        db, stakeholder, current_version, actor, changes={"status": new_status}, change_note=comment or "",
    )
    log_event(
        db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action=action, actor_id=actor.id,
        organization_id=stakeholder.organization_id, project_id=stakeholder.project_id,
        detail={"comment": comment} if comment else None,
    )
    return new_version


def list_project_visible_stakeholders(
    db: Session, project: Project, *, include_archived: bool = False
) -> list[Stakeholder]:
    """The stakeholders a project can see: its own plus its organisation's."""
    query = select(Stakeholder).where(
        or_(
            (Stakeholder.scope == StakeholderScope.PROJECT) & (Stakeholder.project_id == project.id),
            (Stakeholder.scope == StakeholderScope.ORGANIZATION)
            & (Stakeholder.organization_id == project.organization_id),
        )
    )
    if not include_archived:
        query = query.where(Stakeholder.is_archived.is_(False))
    return list(db.scalars(query.order_by(Stakeholder.created_at)).all())


def find_stakeholder_for_user(
    db: Session, scope: StakeholderScope, *, organization_id: uuid.UUID | None, project_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> Stakeholder | None:
    """The non-archived stakeholder in this org/project scope that already
    represents platform user `user_id`, if any (stops "create from org user"
    minting a duplicate)."""
    owner = (
        Stakeholder.organization_id == organization_id if scope == StakeholderScope.ORGANIZATION
        else Stakeholder.project_id == project_id
    )
    return db.scalar(
        select(Stakeholder).join(StakeholderVersion, StakeholderVersion.stakeholder_id == Stakeholder.id).where(
            Stakeholder.scope == scope, owner, Stakeholder.is_archived.is_(False),
            StakeholderVersion.valid_to.is_(None), StakeholderVersion.user_id == user_id,
        )
    )


# --- Influence x Interest grid -----------------------------------------------


def _is_high(db: Session, level: ScoringLevel) -> bool:
    """Whether `level` sits in the upper half of its axis: its weight is at
    least half the axis's top weight, so Medium counts as high on the default
    Low/Medium/High levels and the read-out survives org re-weighting."""
    top = db.scalar(
        select(func.max(ScoringLevel.weight)).where(
            ScoringLevel.organization_id == level.organization_id, ScoringLevel.scheme_key == level.scheme_key,
            ScoringLevel.axis_key == level.axis_key,
        )
    )
    return top is not None and Decimal(level.weight) * 2 >= Decimal(top)


def grid_quadrant(
    db: Session, organization_id: uuid.UUID, *, influence_level_id: uuid.UUID | None,
    interest_level_id: uuid.UUID | None,
) -> GridQuadrant | None:
    """The power/interest grid quadrant for a pair of levels, or `None` when
    either is unset (an unscored stakeholder has no position).

    Raises:
        ValueError: If a level is not valid for the organisation.
    """
    if influence_level_id is None or interest_level_id is None:
        return None
    validate_scoring_levels(
        db, organization_id, influence_level_id=influence_level_id, interest_level_id=interest_level_id
    )
    high_influence = _is_high(db, db.get(ScoringLevel, influence_level_id))
    high_interest = _is_high(db, db.get(ScoringLevel, interest_level_id))
    if high_influence and high_interest:
        return "manage_closely"
    if high_influence:
        return "keep_satisfied"
    if high_interest:
        return "keep_informed"
    return "monitor"


def suggest_cadence(quadrant: GridQuadrant | None) -> TargetCadence | None:
    """The cadence hint for a grid quadrant (resolution 21); a hint only, never
    applied automatically."""
    return CADENCE_HINT_BY_QUADRANT[quadrant] if quadrant is not None else None


# --- Represents Persona ------------------------------------------------------


def _get_or_create_represents_link_type(db: Session, organization_id: uuid.UUID) -> RequirementLinkTypeDefinition:
    """The org's "Represents"/"Is represented by" link type, created on first
    use (the same convention Context & Strategy and Decisions follow for their
    own link types)."""
    link_type = db.scalar(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == _REPRESENTS_FORWARD,
        )
    )
    if link_type is not None:
        return link_type
    count = db.scalar(
        select(func.count()).select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=_REPRESENTS_FORWARD, reverse_name=_REPRESENTS_REVERSE,
        sort_order=count,
    )
    db.add(link_type)
    db.flush()
    return link_type


def _represents_type_id(db: Session, organization_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == _REPRESENTS_FORWARD,
        )
    )


def persona_visible_to_stakeholder(stakeholder: Stakeholder, persona: Persona, organization_id: uuid.UUID) -> bool:
    """Whether `stakeholder` may represent `persona`: same organisation, and
    an org stakeholder only ever represents org personas (so an org-level
    record never depends on one project's data); a project stakeholder may
    represent org personas or its own project's."""
    if persona.scope == PersonaScope.ORGANIZATION:
        return persona.organization_id == organization_id
    return stakeholder.scope == StakeholderScope.PROJECT and persona.project_id == stakeholder.project_id


def add_represents_link(
    db: Session, stakeholder: Stakeholder, persona: Persona, actor: User, *, organization_id: uuid.UUID
) -> Any:
    """Records that `stakeholder` represents `persona`. The caller has
    authorised both; this validates compatibility and de-duplicates.

    Raises:
        ValueError: If the pair is incompatible (cross-org, or an org
            stakeholder and a project persona) or the link already exists.
    """
    if not persona_visible_to_stakeholder(stakeholder, persona, organization_id):
        raise ValueError("This Stakeholder cannot represent that Persona.")
    link_type = _get_or_create_represents_link_type(db, organization_id)
    if get_link_between(
        db, source_type=STAKEHOLDER_ARTEFACT_TYPE, source_id=stakeholder.id, target_type=PERSONA_ARTEFACT_TYPE,
        target_id=persona.id, link_type_id=link_type.id,
    ) is not None:
        raise ValueError("This Stakeholder already represents that Persona.")
    return create_link(
        db, source_type=STAKEHOLDER_ARTEFACT_TYPE, source_id=stakeholder.id, target_type=PERSONA_ARTEFACT_TYPE,
        target_id=persona.id, link_type_id=link_type.id, created_by=actor.id,
    )


def list_represented_personas(db: Session, stakeholder: Stakeholder, organization_id: uuid.UUID) -> list[tuple[Any, Persona]]:
    """`(link, persona)` for every Persona `stakeholder` represents."""
    type_id = _represents_type_id(db, organization_id)
    if type_id is None:
        return []
    rows = []
    for link in get_all_links(db, STAKEHOLDER_ARTEFACT_TYPE, stakeholder.id):
        if link.source_id == stakeholder.id and link.target_type == PERSONA_ARTEFACT_TYPE and link.link_type_id == type_id:
            persona = db.get(Persona, link.target_id)
            if persona is not None:
                rows.append((link, persona))
    return rows


def list_representing_stakeholders(db: Session, persona: Persona, organization_id: uuid.UUID) -> list[tuple[Any, Stakeholder]]:
    """`(link, stakeholder)` for every Stakeholder that represents `persona`."""
    type_id = _represents_type_id(db, organization_id)
    if type_id is None:
        return []
    rows = []
    for link in get_all_links(db, PERSONA_ARTEFACT_TYPE, persona.id):
        if link.target_id == persona.id and link.source_type == STAKEHOLDER_ARTEFACT_TYPE and link.link_type_id == type_id:
            stakeholder = db.get(Stakeholder, link.source_id)
            if stakeholder is not None:
                rows.append((link, stakeholder))
    return rows


def delete_represents_link(db: Session, link: Any) -> None:
    """Removes a "represents" link."""
    delete_link(db, link)


# --- Erasure -----------------------------------------------------------------


def erase_stakeholder(db: Session, stakeholder: Stakeholder, actor: User) -> None:
    """Hard-deletes a stakeholder and everything that holds data about them
    (Phase 0 resolution 15): version rows (contact info included), comments,
    every file in storage (direct and comment attachments), and every
    `ArtefactLink` touching them. Writes one audit event carrying only the id
    and the acting user, never the name or any content. The caller commits.

    Audit events logged earlier for this stakeholder never held a name,
    filename or content (`STAKEHOLDER_ATTACHMENTS.log_filenames` is off and the
    routers log no names), so none need scrubbing.
    """
    file_ids = set(db.scalars(select(StakeholderFile.file_id).where(StakeholderFile.stakeholder_id == stakeholder.id)))
    comment_ids = select(StakeholderComment.id).where(StakeholderComment.stakeholder_id == stakeholder.id)
    file_ids |= set(db.scalars(select(StakeholderCommentFile.file_id).where(StakeholderCommentFile.comment_id.in_(comment_ids))))
    for link in get_all_links(db, STAKEHOLDER_ARTEFACT_TYPE, stakeholder.id):
        delete_link(db, link)
    # The attachment rows cascade from the stakeholder; the bytes must be
    # removed explicitly, so delete the assets (their FK cascades the links).
    for asset in db.scalars(select(FileAsset).where(FileAsset.id.in_(file_ids))).all() if file_ids else []:
        delete_file(db, asset)
    db.flush()
    log_event(
        db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="erased", actor_id=actor.id,
        organization_id=stakeholder.organization_id, project_id=stakeholder.project_id,
    )
    db.delete(stakeholder)
    db.flush()


def resolve_stakeholder_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """The project owning a file attached to a project-scoped stakeholder (or
    its comment); `None` for an org stakeholder's or an unknown file."""
    from app.modules.stakeholders._attachments import resolve_file_project_id
    from app.modules.stakeholders._stakeholder_shared import STAKEHOLDER_ATTACHMENTS

    return resolve_file_project_id(db, STAKEHOLDER_ATTACHMENTS, Stakeholder, file_id)
