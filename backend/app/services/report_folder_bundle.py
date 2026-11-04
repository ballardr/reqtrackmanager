"""
Module: services.report_folder_bundle

The folders an organisation or project added to its Reports picker (`ReportFolder`) in the project and organisation
export bundles.

Responsibilities:
- Export a scope's own folder paths (a folder with reports in it travels as the label on those reports as well).
- Import them: tidy each path again, skip one the scope already lists, and store the rest.

Design decisions:
- **A bundle is untrusted input.** An invalid path is dropped with a warning rather than failing the import.
- Folders are configuration: no author or time is restored; the audit event of the store is the record.

Dependencies: `services.report_folder_store`, `models.report_folder`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_folder import ReportFolder
from app.models.user import User
from app.services import report_folder_store
from app.services.bundle_common import BundleImportWarnings

PROJECT_KEY = "report_folders"
ORG_KEY = "report_folders"


def export_project_folders(db: Session, project: Project) -> dict[str, Any]:
    """The project's own folders as a `project.json` section."""
    rows = db.scalars(select(ReportFolder).where(ReportFolder.project_id == project.id).order_by(ReportFolder.path)).all()
    return {PROJECT_KEY: [row.path for row in rows]}


def export_org_folders(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The organisation's own folders as an `org.json` section."""
    rows = db.scalars(
        select(ReportFolder)
        .where(ReportFolder.organization_id == organization_id, ReportFolder.project_id.is_(None))
        .order_by(ReportFolder.path)
    ).all()
    return {ORG_KEY: [row.path for row in rows]}


def _import(
    db: Session, entries: Any, *, organization_id: uuid.UUID, project: Project | None, actor: User, warnings: BundleImportWarnings,
) -> None:
    if not isinstance(entries, list):
        return
    for entry in entries:
        try:
            if not isinstance(entry, str):
                raise report_folder_store.FolderError("not a path")
            report_folder_store.add_folder(db, organization_id=organization_id, project=project, path=entry, actor_id=actor.id)
        except report_folder_store.FolderExists:
            continue
        except report_folder_store.FolderError:
            warnings.add("A report folder was not imported: its path is not valid.")


def import_org_folders(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports an `org.json`'s folders."""
    _import(db, data.get(ORG_KEY, []), organization_id=organization_id, project=None, actor=actor, warnings=warnings)


def import_project_folders(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports a `project.json`'s folders."""
    _import(db, data.get(PROJECT_KEY, []), organization_id=project.organization_id, project=project, actor=actor, warnings=warnings)
