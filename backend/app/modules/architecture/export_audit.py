"""
Module: modules.architecture.export_audit

Writes the one audit event for a file download of the module (the project's JSON or Structurizr file, a diagram's SVG or
Mermaid text).

- `audit_export` records a `records_exported` event (the action every record-list export writes) with the record type,
  the format and a row count, never a name, a cell or drawing text, and commits it with the download so a file that was
  sent always has its event. One query then finds every export.

Dependencies: `services.audit`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.services.audit import log_event

#: `record_type` of the whole-project files (the JSON interchange file and the Structurizr workspace).
PROJECT_FILE_TYPE = "architecture_interchange"


def audit_export(db: Session, user: User, project: Project, *, record_type: str, fmt: str, rows: int) -> None:
    """Records one `records_exported` event for a file just built, and commits it.

    Args:
        db: Database session.
        user: The person downloading.
        project: The project the file was built from.
        record_type: What the file holds: a registered artefact type, or `PROJECT_FILE_TYPE`.
        fmt: The file format (`json`, `structurizr`, `svg`, `mermaid`).
        rows: How many records the file holds (a single diagram is one).
    """
    log_event(
        db, action="records_exported", actor_id=user.id, entity_type="project", entity_id=project.id, project_id=project.id,
        organization_id=project.organization_id,
        detail={
            "record_type": record_type, "format": fmt, "rows": rows, "columns": 0, "filters": [], "omitted_sensitivity": [],
            "included_sensitivity": [],
        },
    )
    db.commit()
