"""
Module: modules.risk_management.service

Business logic for the Risk Management module (Phases 1-2):

- Risk CRUD as an identity row plus temporal `RiskVersion` snapshots
  (`create_risk`, `apply_new_version`), archive/unarchive, and the project-wide
  listing.
- The Risk type vocabulary (`RISK_TYPES`, a `TypeVocabulary`) and resolving a
  risk's type reference against the project's effective list.
- Validation of the six scoring-level references against the organisation's
  `risk` scheme (`validate_levels`).
- `resolve_risk_file_project_id`, the file-ownership hook.
- The lifecycle (Phase 2): the branching `RISK_ALLOWED_TRANSITIONS` table, the
  per-target guards (`check_transition_guards`) and `transition_risk`, plus the
  `ACCEPTED` content lock (`check_accepted_content_unchanged`). `MITIGATED` also
  needs an effective treatment (Phase 3, `treatment.py`).

Design decisions:
- Status is versioned content but is not editable through the update API: a
  risk is created `IDENTIFIED` and only `transition_risk` moves it, so every move
  is validated, audited and visible in the version history.
- Guards sit on the *target* state, so a forward move and a move back to the same
  state demand the same facts (Decided by: Agent, Phase 2).
- While `ACCEPTED`, the assessment an acceptor signed off (inherent/residual
  levels, acceptance criteria, strategy) cannot be edited in place; the risk must
  be moved back first. Otherwise a Risk Manager could change the residual rating
  after the acceptor approved it, which defeats the separate acceptor role.
- A risk's type is optional (Decided by: Agent): quick capture matters more than
  a category at the moment of identification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.risk_management.enums import RiskStatus
from app.modules.risk_management.labels import risk_status_label
from app.modules.risk_management.models import (
    ProjectRiskType,
    Risk,
    RiskTypeDefinition,
    RiskVersion,
)
from app.modules.risk_management.ratings import RatingContext, rate_version
from app.modules.risk_management.scoring import LEVEL_COLUMN_AXES, RISK_SCORING_SCHEME_KEY
from app.services.sequences import generate_unique_code
from app.services.type_vocabulary import TypeVocabulary

RISK_MODULE_KEY = "risk_management"
RISK_ARTEFACT_TYPE = "risk"
RISK_SUBCOMPONENT_KEY = "risk"
RISK_CODE_PREFIX = "RSK"

# Overview §11.3's categories; all are org-editable (plan Phase 0 resolution 2).
DEFAULT_RISK_TYPES: tuple[str, ...] = (
    "Safety", "Technical", "Reliability", "Performance", "Security", "Compliance", "Operational", "Schedule",
    "Cost", "Supply chain", "Integration", "Environmental",
)

RISK_TYPES = TypeVocabulary(
    label="Risk type",
    org_model=RiskTypeDefinition,
    project_model=ProjectRiskType,
    default_names=DEFAULT_RISK_TYPES,
    # A version references a project type row, never an org type directly.
    org_type_in_use=lambda db, type_id: False,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(RiskVersion.id).where(RiskVersion.project_type_id == type_id).limit(1)
    ) is not None,
)

# Versioned content fields `apply_new_version` carries forward.
RISK_CONTENT_FIELDS: tuple[str, ...] = (
    "title", "statement", "cause", "risk_event", "consequence", "project_type_id", "treatment_strategy",
    "acceptance_criteria", *LEVEL_COLUMN_AXES, "status", "owner_type", "owner_id", "review_date",
)


def get_current_risk_version(db: Session, risk_id: uuid.UUID) -> RiskVersion:
    """Returns the current (`valid_to IS NULL`) version of a risk.

    Raises:
        ValueError: If none exists (a data-integrity bug).
    """
    version = db.scalar(select(RiskVersion).where(RiskVersion.risk_id == risk_id, RiskVersion.valid_to.is_(None)))
    if version is None:
        raise ValueError(f"Risk {risk_id} has no current version.")
    return version


def resolve_risk_type(db: Session, project: Project, type_id: uuid.UUID | None) -> uuid.UUID | None:
    """Resolves a payload's type id (an `EffectiveType.id`) to the project type
    row a version references, creating the passthrough row the first time an org
    type is chosen.

    Raises:
        ValueError: If `type_id` is not usable in this project or is disabled here.
    """
    if type_id is None:
        return None
    row = RISK_TYPES.get_or_create_project_type(db, project.id, project.organization_id, type_id)
    if not row.is_enabled:
        raise ValueError(f"This {RISK_TYPES.label} is disabled for this project.")
    return row.id


def validate_levels(db: Session, organization_id: uuid.UUID, levels: dict[str, uuid.UUID | None]) -> None:
    """Checks each given level is a level of this organisation on the right axis
    of the `risk` scheme.

    Args:
        organization_id: The project's organisation.
        levels: `RiskVersion` level column name -> level id (`None` entries are skipped).

    Raises:
        ValueError: If a level belongs to another organisation, scheme or axis.
    """
    for column, level_id in levels.items():
        if level_id is None:
            continue
        axis_key = LEVEL_COLUMN_AXES[column]
        level = db.get(ScoringLevel, level_id)
        if (
            level is None or level.organization_id != organization_id
            or level.scheme_key != RISK_SCORING_SCHEME_KEY or level.axis_key != axis_key
        ):
            raise ValueError(f"This is not a valid {axis_key} level for this organisation.")


def create_risk(db: Session, *, project: Project, creator: User, **content: Any) -> Risk:
    """Creates a risk and its version 1 in `IDENTIFIED`.

    Args:
        project: The owning project.
        creator: The acting user.
        **content: Any `RISK_CONTENT_FIELDS` except `status`; `title` is required.
    """
    risk = Risk(
        project_id=project.id, creator_id=creator.id,
        unique_code=generate_unique_code(db, project, RISK_ARTEFACT_TYPE, RISK_CODE_PREFIX),
    )
    db.add(risk)
    db.flush()
    now = datetime.now(UTC)
    content = {k: v for k, v in content.items() if k in RISK_CONTENT_FIELDS and k != "status"}
    db.add(RiskVersion(
        risk_id=risk.id, version_number=1, valid_from=now, valid_to=None, status=RiskStatus.IDENTIFIED,
        change_note="Initial creation.", created_by=creator.id, created_at=now, **content,
    ))
    db.flush()
    return risk


def apply_new_version(
    db: Session, risk: Risk, current_version: RiskVersion, actor: User, *, changes: dict[str, Any], change_note: str = "",
) -> RiskVersion:
    """Closes `current_version` and inserts a new one with `changes` applied over
    the carried-forward content. A key present in `changes` is applied even when
    `None`, so nullable fields can be cleared; absent keys are carried forward."""
    now = datetime.now(UTC)
    current_version.valid_to = now
    values = {f: getattr(current_version, f) for f in RISK_CONTENT_FIELDS}
    values.update({k: v for k, v in changes.items() if k in RISK_CONTENT_FIELDS})
    new_version = RiskVersion(
        risk_id=risk.id, version_number=current_version.version_number + 1, valid_from=now, valid_to=None,
        change_note=change_note, created_by=actor.id, created_at=now, **values,
    )
    db.add(new_version)
    db.flush()
    return new_version


# --- Lifecycle (Phase 2) ------------------------------------------------------

_S = RiskStatus
# The alternative outcomes a risk can reach once assessed; each leads to CLOSED.
_OUTCOMES = frozenset({_S.ACCEPTED, _S.TRANSFERRED, _S.AVOIDED, _S.REALISED, _S.REJECTED})
_ACTIVE = (_S.ASSESSED, _S.TREATMENT_PLANNED, _S.TREATMENT_IN_PROGRESS)

# Legal moves (plan Phase 0 resolution 4; exact table Decided by: Agent). Forward
# along the main line, the outcomes from any assessed-or-later working state
# (`REJECTED` also straight from `IDENTIFIED`), a settled risk may still be
# `REALISED`, and a reassessment moves a risk back to any earlier working state.
# `CLOSED` reopens to `ASSESSED`; a wrongly `REJECTED` risk returns to `IDENTIFIED`.
RISK_ALLOWED_TRANSITIONS: dict[RiskStatus, frozenset[RiskStatus]] = {
    _S.IDENTIFIED: frozenset({_S.ASSESSED, _S.REJECTED}),
    _S.ASSESSED: frozenset({_S.TREATMENT_PLANNED}) | _OUTCOMES,
    _S.TREATMENT_PLANNED: frozenset({_S.ASSESSED, _S.TREATMENT_IN_PROGRESS}) | _OUTCOMES,
    _S.TREATMENT_IN_PROGRESS: frozenset({_S.ASSESSED, _S.TREATMENT_PLANNED, _S.MITIGATED}) | _OUTCOMES,
    _S.MITIGATED: frozenset({*_ACTIVE, _S.CLOSED, _S.REALISED}),
    _S.ACCEPTED: frozenset({*_ACTIVE, _S.CLOSED, _S.REALISED}),
    _S.TRANSFERRED: frozenset({*_ACTIVE, _S.CLOSED, _S.REALISED}),
    _S.AVOIDED: frozenset({*_ACTIVE, _S.CLOSED}),
    _S.REALISED: frozenset({*_ACTIVE, _S.CLOSED}),
    _S.REJECTED: frozenset({_S.IDENTIFIED, _S.CLOSED}),
    _S.CLOSED: frozenset({_S.ASSESSED}),
}

# Fields frozen while a risk is ACCEPTED (see the module docstring).
ACCEPTED_LOCKED_FIELDS: tuple[str, ...] = (*LEVEL_COLUMN_AXES, "acceptance_criteria", "treatment_strategy")


def check_transition_guards(
    version: RiskVersion, target: RiskStatus, ctx: RatingContext, *, effective_treatments: int = 0
) -> None:
    """Checks the facts the target state demands of a risk's current content.

    - `ASSESSED`: an inherent rating (every axis the project's model needs is set).
    - `TREATMENT_PLANNED`: an owner and a treatment strategy.
    - `MITIGATED`: a residual rating and at least one treatment link assessed
      effective (a risk is mitigated by something that works, not by a link).
    - `ACCEPTED`: a residual rating and written acceptance criteria.

    Args:
        version: The risk's current version.
        target: The state being moved to.
        ctx: The project's rating context.
        effective_treatments: How many of the risk's treatment links are
            assessed effective (`treatment.effective_treatment_counts`).

    Raises:
        ValueError: Naming what is missing.
    """
    inherent, residual = rate_version(ctx, version)
    missing: list[str] = []
    if target == RiskStatus.ASSESSED and inherent is None:
        missing.append("an inherent rating (set every inherent scoring level the project's model needs)")
    if target == RiskStatus.TREATMENT_PLANNED:
        if version.owner_id is None:
            missing.append("an owner")
        if version.treatment_strategy is None:
            missing.append("a treatment strategy")
    if target in (RiskStatus.MITIGATED, RiskStatus.ACCEPTED) and residual is None:
        missing.append("a residual rating (set every residual scoring level the project's model needs)")
    if target == RiskStatus.MITIGATED and effective_treatments == 0:
        missing.append("a treatment assessed effective (link a mitigating requirement, design or action and assess it)")
    if target == RiskStatus.ACCEPTED and not version.acceptance_criteria.strip():
        missing.append("acceptance criteria")
    if missing:
        raise ValueError(f"A risk needs {' and '.join(missing)} before it can be {target.value.replace('_', ' ')}.")


def check_accepted_content_unchanged(current: RiskVersion, changes: dict[str, Any]) -> None:
    """Rejects an in-place edit of an accepted risk's signed-off assessment.

    Raises:
        ValueError: If `current` is `ACCEPTED` and `changes` alters a locked field.
    """
    if current.status != RiskStatus.ACCEPTED:
        return
    changed = [f for f in ACCEPTED_LOCKED_FIELDS if f in changes and changes[f] != getattr(current, f)]
    if changed:
        raise ValueError(
            "An accepted risk's assessment cannot be edited in place; move it back to Assessed first "
            f"(would change: {', '.join(changed)})."
        )


def transition_risk(
    db: Session, risk: Risk, current: RiskVersion, target: RiskStatus, actor: User, ctx: RatingContext,
    *, comment: str = "",
) -> RiskVersion:
    """Moves a risk to `target` as a new version.

    The caller has locked the risk row, re-read `current` under that lock and
    checked the actor's role for `target`. Does not commit or audit-log.

    Args:
        current: The risk's current version.
        ctx: The project's rating context (for the guards).
        comment: Becomes the version's change note (a default note otherwise).

    Raises:
        ValueError: If the risk is archived, the move is not in
            `RISK_ALLOWED_TRANSITIONS`, or a guard fails.
    """
    if risk.is_archived:
        raise ValueError("An archived risk cannot change status; unarchive it first.")
    if target not in RISK_ALLOWED_TRANSITIONS[current.status]:
        raise ValueError(f"Cannot move a Risk from '{current.status.value}' to '{target.value}'.")
    from app.modules.risk_management.treatment import effective_treatment_counts

    check_transition_guards(
        current, target, ctx, effective_treatments=effective_treatment_counts(db, [risk.id]).get(risk.id, 0)
    )
    note = comment.strip() or f"Status: {risk_status_label(current.status.value)} -> {risk_status_label(target.value)}."
    return apply_new_version(db, risk, current, actor, changes={"status": target}, change_note=note)


def archive_risk(risk: Risk, actor: User) -> None:
    """Soft-archives a risk."""
    risk.is_archived = True
    risk.archived_at = datetime.now(UTC)
    risk.archived_by = actor.id


def unarchive_risk(risk: Risk) -> None:
    """Reverses `archive_risk`."""
    risk.is_archived = False
    risk.archived_at = None
    risk.archived_by = None


def list_project_risks(db: Session, project_id: uuid.UUID, *, include_archived: bool = False) -> list[Risk]:
    """The project's risks in identifier order (oldest first)."""
    query = select(Risk).where(Risk.project_id == project_id)
    if not include_archived:
        query = query.where(Risk.is_archived.is_(False))
    return list(db.scalars(query.order_by(Risk.created_at, Risk.unique_code)).all())


def resolve_risk_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """The project owning a file attached to a risk (or its comment); `None`
    for an unknown file."""
    from app.modules.risk_management._shared import RISK_ATTACHMENTS
    from app.services.module_attachments import resolve_file_project_id

    return resolve_file_project_id(db, RISK_ATTACHMENTS, Risk, file_id)
