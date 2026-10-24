"""
Module: modules.compliance.evidence_edits

The create and edit paths of a piece of supporting evidence, shared by the project endpoints
(`project_router.evidence`) and the record-table import (`record_tables`) so a rule added here reaches both.

Responsibilities:
- Create a `ComplianceEvidence` row with its project-unique code, the provider and time stamped by the system,
  and record the `created` audit event.
- Edit its metadata in place (title, description, issuing organisation, issue date, notes) and record the
  `updated` audit event.

Design decisions:
- Nothing here commits and nothing here checks who may do it: the caller owns the transaction and the role gate
  (`evidence._require_evidence_manage` for the endpoint, the provider's `can_update` for the import).
- The expiry date is set at creation only. Changing it is a revalidation (`POST .../revalidate`), which keeps the
  previous value in `ComplianceEvidenceRevalidation`, so this module's edit function has no expiry parameter.
- An edit takes the fields to change and keeps every other, because the endpoint sends all of them and a file
  names only the cells it changes.

Dependencies: `models` (the row and its code constants), `services.sequences`, `services.audit`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.compliance.models import ARTEFACT_TYPE_EVIDENCE, EVIDENCE_CODE_PREFIX, ComplianceEvidence
from app.services.audit import log_event
from app.services.sequences import generate_unique_code

#: The metadata an edit may change (the expiry date is revalidation-only).
EDITABLE_FIELDS = ("title", "description", "issuing_organisation", "issued_date", "notes")


def stage_evidence(
    db: Session, project: Project, creator: User, *, title: str, description: str = "", issuing_organisation: str | None = None,
    issued_date: date | None = None, expiry_date: date | None = None, notes: str = "",
) -> ComplianceEvidence:
    """Creates a piece of evidence for `project` (provider and time set from `creator` and now) and records the
    `created` event. Flushes; does not commit.

    Args:
        project: The owning project.
        creator: The acting user.
        title: Short display name.
        description / issuing_organisation / issued_date / expiry_date / notes: Optional metadata.

    Returns:
        The new row, with its `EVD-nnn` code.
    """
    evidence = ComplianceEvidence(
        project_id=project.id, unique_code=generate_unique_code(db, project, ARTEFACT_TYPE_EVIDENCE, EVIDENCE_CODE_PREFIX),
        title=title, description=description, issuing_organisation=issuing_organisation, issued_date=issued_date,
        expiry_date=expiry_date, provided_by=creator.id, provided_at=datetime.now(UTC), notes=notes,
    )
    db.add(evidence)
    db.flush()
    log_event(
        db, entity_type=ARTEFACT_TYPE_EVIDENCE, entity_id=evidence.id, action="created", actor_id=creator.id,
        project_id=project.id, detail={"title": evidence.title},
    )
    return evidence


def stage_evidence_update(db: Session, evidence: ComplianceEvidence, actor: User, changes: dict[str, Any]) -> None:
    """Applies `changes` (any of `EDITABLE_FIELDS`; a key absent is kept) and records the `updated` event.
    Does not commit."""
    for field in EDITABLE_FIELDS:
        if field in changes:
            setattr(evidence, field, changes[field])
    log_event(
        db, entity_type=ARTEFACT_TYPE_EVIDENCE, entity_id=evidence.id, action="updated", actor_id=actor.id,
        project_id=evidence.project_id,
    )
