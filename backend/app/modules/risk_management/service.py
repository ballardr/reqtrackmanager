"""
Module: modules.risk_management.service

Business logic for the Risk Management module, Phase 1:

- Risk CRUD as an identity row plus temporal `RiskVersion` snapshots
  (`create_risk`, `apply_new_version`), archive/unarchive, and the project-wide
  listing.
- The Risk type vocabulary (`RISK_TYPES`, a `TypeVocabulary`) and resolving a
  risk's type reference against the project's effective list.
- Validation of the six scoring-level references against the organisation's
  `risk` scheme (`validate_levels`).
- `resolve_risk_file_project_id`, the file-ownership hook.

Design decisions:
- Status is versioned content but is not editable through the update API: a
  risk is created `IDENTIFIED`, and the lifecycle transitions are Phase 2's.
- No content lock yet; each edit is a new version, so history is complete.
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
from app.modules.risk_management.models import (
    ProjectRiskType,
    Risk,
    RiskTypeDefinition,
    RiskVersion,
)
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
    "acceptance_criteria", *LEVEL_COLUMN_AXES, "status", "owner_id", "review_date",
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
