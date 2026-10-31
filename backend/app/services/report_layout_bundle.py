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
- **There is no branding template.** An older bundle's `report_template` is ignored with a notice: the organisation has
  one report look, and a layout reads it where it asks (`{{org.*}}`).
- **Hides travel by layout name**, resolved against the target project's inherited layouts after the
  organisation's layouts have been imported (organisation bundle) or against the organisation it joins
  (project bundle). A name with no inherited layout of that name is reported, not guessed.
- **Pictures travel with the layouts that use them** (`report_layout_images` section: file reference, name, type, library tier;
  the bytes in the bundle's `files/`). An import copies each into the target's own library (a project's for a project
  layout, the organisation's for an organisation layout) and rewrites the image blocks' file ids, so a restored layout
  keeps its pictures. An organisation picture that already exists in the importing organisation is kept by reference
  instead of copied. A picture whose bytes are missing leaves its block pointing nowhere, and the version that holds it
  is dropped with a warning like any invalid version (the save-time image check names it).
- **Names that already exist** (organisation merge into a live organisation) are never overwritten: the
  import is added as "<name> (imported)", or skipped with a warning when that is also taken.

Dependencies: `services.report_layouts`, `services.report_layout_scope`, `services.bundle_common`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.user import User
from app.services import report_layout_scope, report_layouts
from app.services.bundle_common import BundleImportWarnings, import_bundled_file
from app.services.report_folders import imported_folder
from app.services.report_images import SVG_TYPE, image_nodes, usable_by_layout
from app.services.report_layout_tree import InvalidLayoutError

PROJECT_KEY = "report_layouts"
HIDDEN_KEY = "report_layouts_hidden"
ORG_KEY = "report_layouts"
#: Not `report_images`: that name belonged to removed report content and is a legacy key the importers warn about.
IMAGES_KEY = "report_layout_images"


def layout_entry(db: Session, layout: ReportLayout, *, latest_only: bool = False) -> dict[str, Any]:
    """One layout with every version, oldest first. Author email and time are information only.

    `latest_only` keeps just the current version, noted "Copied from <name>, version n" (what a copy between
    projects carries; the source keeps its history).
    """
    versions = report_layouts.list_versions(db, layout.id)
    if latest_only:
        versions = [v for v in versions if v.version == layout.current_version]
    emails = {
        u.id: u.email for u in db.scalars(select(User).where(User.id.in_({v.created_by for v in versions if v.created_by})))
    } if any(v.created_by for v in versions) else {}
    return {
        "name": layout.name, "description": layout.description, "folder": layout.folder, "family": layout.family,
        "versions": [
            {
                "version": v.version, "schema_version": v.schema_version, "tree": v.tree,
                "comment": f"Copied from {layout.name}, version {v.version}"[: report_layouts.MAX_COMMENT_CHARS] if latest_only else v.comment,
                "created_by_email": emails.get(v.created_by) if v.created_by else None, "created_at": v.created_at.isoformat(),
            }
            for v in reversed(versions)
        ],
    }


def image_entries(
    db: Session, layouts: list[dict[str, Any]], organization_id: uuid.UUID, project_id: uuid.UUID | None,
    assets: dict[uuid.UUID, FileAsset],
) -> list[dict[str, Any]]:
    """The pictures the exported layouts' versions use, as bundle entries; their files are added to `assets`.

    A picture the layouts' owner could not use (another tier, another organisation, deleted) is left out.
    """
    wanted: dict[uuid.UUID, FileAsset] = {}
    for layout in layouts:
        for version in layout["versions"]:
            for _, node in image_nodes(version["tree"]):
                try:
                    file_id = uuid.UUID(str(node.get("file")))
                except ValueError:
                    continue
                asset = db.get(FileAsset, file_id)
                if file_id not in wanted and usable_by_layout(asset, organization_id, project_id):
                    assert asset is not None
                    wanted[file_id] = asset
    assets.update(wanted)
    return [
        {
            "id": str(a.id), "file_ref": f"{a.id}_{a.filename}", "filename": a.filename, "content_type": a.content_type,
            "tier": "organisation" if a.is_org_resource else "project",
        }
        for a in wanted.values()
    ]


def export_project_layouts(db: Session, project: Project, assets: dict[uuid.UUID, FileAsset]) -> dict[str, Any]:
    """The project's own layouts and the inherited layouts it hides (by name), and the pictures they use, as `project.json` sections.

    `assets` is filled with the pictures' files so the bundle embeds their bytes.
    """
    own = db.scalars(
        select(ReportLayout).where(ReportLayout.project_id == project.id).order_by(ReportLayout.name)
    ).all()
    hidden = [
        {"name": s.layout.name, "origin": s.origin}
        for s in report_layout_scope.resolve_project_layouts(db, project) if s.hidden
    ]
    layouts = [layout_entry(db, layout) for layout in own]
    return {
        PROJECT_KEY: layouts, HIDDEN_KEY: hidden,
        IMAGES_KEY: image_entries(db, layouts, project.organization_id, project.id, assets),
    }


def export_org_layouts(db: Session, organization_id: uuid.UUID, assets: dict[uuid.UUID, FileAsset]) -> dict[str, Any]:
    """The organisation's own layouts and the pictures they use, as `org.json` sections (`assets` as for a project)."""
    layouts = [layout_entry(db, layout) for layout in report_layout_scope.list_org_layouts(db, organization_id)]
    return {ORG_KEY: layouts, IMAGES_KEY: image_entries(db, layouts, organization_id, None, assets)}


def import_images(
    db: Session, entries: Any, file_bytes_by_ref: dict[str, bytes], *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None, actor: User, warnings: BundleImportWarnings,
) -> dict[str, str]:
    """Recreates the bundle's pictures in this tier's library and returns `{old file id: new file id}`.

    An organisation picture that already exists in the importing organisation maps to itself. A picture whose bytes
    are missing is reported and left unmapped.
    """
    mapping: dict[str, str] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        old = str(entry.get("id", ""))
        try:
            old_id = uuid.UUID(old)
        except ValueError:
            continue
        existing = db.get(FileAsset, old_id)
        if entry.get("tier") == "organisation" and usable_by_layout(existing, organization_id, None):
            mapping[old] = old
            continue
        data = file_bytes_by_ref.get(str(entry.get("file_ref", "")))
        content_type = str(entry.get("content_type", ""))
        if data is None:
            warnings.add(f'Report image "{entry.get("filename", "")}" has no file in the bundle, so layouts using it need another picture.')
            continue
        asset = import_bundled_file(
            db, organization_id=organization_id, uploaded_by=actor.id, filename=str(entry.get("filename", "image")),
            content_type=content_type if content_type == SVG_TYPE or content_type.startswith("image/") else "image/png", data=data,
        )
        asset.is_org_resource = project_id is None
        asset.project_id = project_id
        mapping[old] = str(asset.id)
    return mapping


def rewrite_images(tree: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """A copy of `tree` whose image blocks name the imported pictures (a block with no mapping keeps its id)."""
    copy: dict[str, Any] = json.loads(json.dumps(tree))
    for _, node in image_nodes(copy):
        old = node.get("file")
        node["file"] = mapping.get(old, old) if isinstance(old, str) else old
    return copy


def import_layout_entry(
    db: Session, entry: dict[str, Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None, actor: User,
    warnings: BundleImportWarnings, existing_names: set[str] | None = None, images: dict[str, str] | None = None,
) -> uuid.UUID | None:
    """Creates one layout from its bundle entry. Returns the new layout's id, or `None` when none was stored.

    `existing_names` (lower-cased names the owner already has) switches on the merge rule: a taken name is
    imported as "<name> (imported)" instead. `images` maps the bundle's picture ids to the imported ones.
    """
    name = str(entry.get("name", "")).strip()
    family = entry.get("family")
    versions = sorted(
        (v for v in entry.get("versions", []) if isinstance(v, dict) and isinstance(v.get("tree"), dict)),
        key=lambda v: v.get("version", 0),
    )
    if existing_names is not None and name.casefold() in existing_names:
        name = f"{name} (imported)"
    template_name = entry.get("report_template")
    if isinstance(template_name, str) and template_name:
        warnings.add(
            f'Report layout "{name}": the report template "{template_name}" it named is no longer used; '
            "the organisation's report look applies."
        )
    layout_id: uuid.UUID | None = None
    stored = 0
    dropped = 0
    for v in versions:
        comment = str(v.get("comment", ""))[: report_layouts.MAX_COMMENT_CHARS]
        tree = rewrite_images(v["tree"], images or {})
        try:
            if layout_id is None:
                saved = report_layouts.create_layout(
                    db, organization_id=organization_id, project_id=project_id, name=name,
                    description=str(entry.get("description", "")), folder=imported_folder(entry.get("folder")),
                    family=str(family),
                    tree=tree, actor_id=actor.id, comment=comment,
                )
                layout_id = saved.layout.id
            else:
                saved = report_layouts.save_version(
                    db, layout_id, tree, base_version=stored, actor_id=actor.id, comment=comment,
                )
        except report_layouts.LayoutNameTakenError:
            warnings.add(f'Report layout "{name}" was skipped: a layout with that name already exists.')
            return None
        except (InvalidLayoutError, ValueError):
            dropped += 1
            continue
        stored = saved.layout.current_version
    if layout_id is None:
        warnings.add(f'Report layout "{name}" was skipped: none of its versions is valid in this installation.')
        return None
    if dropped:
        warnings.add(f'Report layout "{name}": {dropped} version(s) that are not valid in this installation were left out.')
    return layout_id


def import_org_layouts(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings, *,
    merge: bool, file_bytes_by_ref: dict[str, bytes],
) -> int:
    """Imports the `org.json` layouts and their pictures. `merge` is true when the organisation already exists.

    Returns:
        How many layouts were stored.
    """
    existing = (
        {n.casefold() for n in db.scalars(select(ReportLayout.name).where(
            ReportLayout.organization_id == organization_id, ReportLayout.project_id.is_(None)))}
        if merge else None
    )
    images = import_images(
        db, data.get(IMAGES_KEY), file_bytes_by_ref, organization_id=organization_id, project_id=None, actor=actor,
        warnings=warnings,
    )
    return sum(
        import_layout_entry(
            db, entry, organization_id=organization_id, project_id=None, actor=actor, warnings=warnings,
            existing_names=existing, images=images,
        ) is not None
        for entry in data.get(ORG_KEY, []) if isinstance(entry, dict)
    )


def import_project_layouts(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
    file_bytes_by_ref: dict[str, bytes],
) -> None:
    """Imports a `project.json`'s own layouts and their pictures, then re-applies the hides to this project's inherited layouts."""
    images = import_images(
        db, data.get(IMAGES_KEY), file_bytes_by_ref, organization_id=project.organization_id, project_id=project.id,
        actor=actor, warnings=warnings,
    )
    for entry in data.get(PROJECT_KEY, []):
        if isinstance(entry, dict):
            import_layout_entry(
                db, entry, organization_id=project.organization_id, project_id=project.id, actor=actor, warnings=warnings,
                images=images,
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


__all__ = [
    "export_org_layouts", "export_project_layouts", "image_entries", "import_images", "import_layout_entry",
    "import_org_layouts", "import_project_layouts", "layout_entry", "rewrite_images",
]
