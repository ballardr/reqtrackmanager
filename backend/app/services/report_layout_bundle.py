"""
Module: services.report_layout_bundle

Report layouts in the project and organisation export bundles.

Responsibilities:
- Export a project's own layouts (every version) and the inherited layouts it has hidden; export an
  organisation's own layouts.
- Import them: validate every tree again, number versions afresh, re-apply the hides by name.

Design decisions:
- **A bundle is untrusted input.** Each version is validated against this deployment's field registry
  before it is stored (`report_layouts.create_layout` / `save_version`); a version that fails is dropped
  with a warning, and a layout with no valid version is skipped. Versions are renumbered 1..n so history
  stays gap-free.
- **Authors and times are not restored.** The importer becomes the author and the import time the save
  time (as for the other imported records); the version comment travels. The export carries the original
  author's email and save time as information only.
- **Hides travel by layout name**, resolved against the target project's inherited layouts after the
  organisation's layouts have been imported (organisation bundle) or against the organisation it joins
  (project bundle). A name with no inherited layout of that name is reported, not guessed.
- **Names that already exist** (organisation merge into a live organisation) are never overwritten: the
  import is added as "<name> (imported)", or skipped with a warning when that is also taken.

Dependencies: `services.report_layouts`, `services.report_layout_scope`, `services.bundle_common`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.user import User
from app.services import report_layout_scope, report_layouts
from app.services.bundle_common import BundleImportWarnings
from app.services.report_folders import imported_folder
from app.services.report_layout_tree import InvalidLayoutError

PROJECT_KEY = "report_layouts"
HIDDEN_KEY = "report_layouts_hidden"
ORG_KEY = "report_layouts"


def _layout_json(db: Session, layout: ReportLayout) -> dict[str, Any]:
    """One layout with every version, oldest first. Author email and time are information only."""
    versions = report_layouts.list_versions(db, layout.id)
    emails = {
        u.id: u.email for u in db.scalars(select(User).where(User.id.in_({v.created_by for v in versions if v.created_by})))
    } if any(v.created_by for v in versions) else {}
    return {
        "name": layout.name, "description": layout.description, "folder": layout.folder, "family": layout.family,
        "versions": [
            {
                "version": v.version, "schema_version": v.schema_version, "tree": v.tree, "comment": v.comment,
                "created_by_email": emails.get(v.created_by) if v.created_by else None, "created_at": v.created_at.isoformat(),
            }
            for v in reversed(versions)
        ],
    }


def export_project_layouts(db: Session, project: Project) -> dict[str, Any]:
    """The project's own layouts and the inherited layouts it hides (by name), as `project.json` sections."""
    own = db.scalars(
        select(ReportLayout).where(ReportLayout.project_id == project.id).order_by(ReportLayout.name)
    ).all()
    hidden = [
        {"name": s.layout.name, "origin": s.origin}
        for s in report_layout_scope.resolve_project_layouts(db, project) if s.hidden
    ]
    return {PROJECT_KEY: [_layout_json(db, layout) for layout in own], HIDDEN_KEY: hidden}


def export_org_layouts(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The organisation's own layouts as an `org.json` section."""
    return {ORG_KEY: [_layout_json(db, layout) for layout in report_layout_scope.list_org_layouts(db, organization_id)]}


def _import_layout(
    db: Session, entry: dict[str, Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None, actor: User,
    warnings: BundleImportWarnings, existing_names: set[str] | None = None,
) -> bool:
    """Creates one layout from its bundle entry. Returns whether a layout was stored.

    `existing_names` (lower-cased names the owner already has) switches on the merge rule: a taken name is
    imported as "<name> (imported)" instead.
    """
    name = str(entry.get("name", "")).strip()
    family = entry.get("family")
    versions = sorted(
        (v for v in entry.get("versions", []) if isinstance(v, dict) and isinstance(v.get("tree"), dict)),
        key=lambda v: v.get("version", 0),
    )
    if existing_names is not None and name.casefold() in existing_names:
        name = f"{name} (imported)"
    layout_id: uuid.UUID | None = None
    stored = 0
    dropped = 0
    for v in versions:
        comment = str(v.get("comment", ""))[: report_layouts.MAX_COMMENT_CHARS]
        try:
            if layout_id is None:
                saved = report_layouts.create_layout(
                    db, organization_id=organization_id, project_id=project_id, name=name,
                    description=str(entry.get("description", "")), folder=imported_folder(entry.get("folder")), family=str(family),
                    tree=v["tree"], actor_id=actor.id, comment=comment,
                )
                layout_id = saved.layout.id
            else:
                saved = report_layouts.save_version(
                    db, layout_id, v["tree"], base_version=stored, actor_id=actor.id, comment=comment,
                )
        except report_layouts.LayoutNameTakenError:
            warnings.add(f'Report layout "{name}" was skipped: a layout with that name already exists.')
            return False
        except (InvalidLayoutError, ValueError):
            dropped += 1
            continue
        stored = saved.layout.current_version
    if layout_id is None:
        warnings.add(f'Report layout "{name}" was skipped: none of its versions is valid in this installation.')
        return False
    if dropped:
        warnings.add(f'Report layout "{name}": {dropped} version(s) that are not valid in this installation were left out.')
    return True


def import_org_layouts(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings, *,
    merge: bool,
) -> int:
    """Imports the `org.json` layouts. `merge` is true when the organisation already exists.

    Returns:
        How many layouts were stored.
    """
    existing = (
        {n.casefold() for n in db.scalars(select(ReportLayout.name).where(
            ReportLayout.organization_id == organization_id, ReportLayout.project_id.is_(None)))}
        if merge else None
    )
    return sum(
        _import_layout(
            db, entry, organization_id=organization_id, project_id=None, actor=actor, warnings=warnings,
            existing_names=existing,
        )
        for entry in data.get(ORG_KEY, []) if isinstance(entry, dict)
    )


def import_project_layouts(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports a `project.json`'s own layouts, then re-applies the hides to this project's inherited layouts."""
    for entry in data.get(PROJECT_KEY, []):
        if isinstance(entry, dict):
            _import_layout(
                db, entry, organization_id=project.organization_id, project_id=project.id, actor=actor, warnings=warnings,
            )
    hidden_names = [str(h.get("name", "")) for h in data.get(HIDDEN_KEY, []) if isinstance(h, dict)]
    if not hidden_names:
        return
    inherited = {
        s.layout.name.casefold(): s.layout.id
        for s in report_layout_scope.resolve_project_layouts(db, project) if s.origin != "project"
    }
    for name in hidden_names:
        layout_id = inherited.get(name.casefold())
        if layout_id is None:
            warnings.add(f'Hidden report layout "{name}" was not applied: this project inherits no layout of that name.')
            continue
        report_layout_scope.hide_layout(db, project, layout_id, actor_id=actor.id)


__all__ = ["export_org_layouts", "export_project_layouts", "import_org_layouts", "import_project_layouts"]
