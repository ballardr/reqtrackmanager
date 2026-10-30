"""
Module: services.report_snippet_bundle

Author-saved report snippets in the project and organisation export bundles.

Responsibilities:
- Export a project's own snippets and the inherited ones it has hidden (by name); export an organisation's own snippets.
- Import them: validate every fragment again, store through the snippet store, re-apply the hides by name.

Design decisions:
- **A bundle is untrusted input.** Each fragment goes through `report_snippet_store.create_snippet`, so it is checked against
  this deployment's block schemas and the library rule at its tier; one that fails is skipped with a warning.
- **Pictures travel with the snippets that use them** (`report_snippet_images`, the same entry shape and importer as the
  layouts' pictures, bytes in the bundle's `files/`): an import copies each into the target's own library and rewrites
  the image blocks' file ids. An organisation picture the importing organisation already has is kept by reference.
- **Authors and times are not restored.** The importer becomes the author.
- **Hides travel by name**, resolved against the project's inherited snippets after the organisation's have been imported.
  A name with no inherited snippet is reported, not guessed.
- **Names that already exist** (organisation merge into a live organisation) are never overwritten: the import is added as
  "<name> (imported)", or skipped with a warning when that is also taken.

Dependencies: `services.report_snippet_store`, `services.report_snippet_scope`, `services.report_layout_bundle` (pictures),
`services.bundle_common`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_snippet import SavedReportSnippet
from app.models.user import User
from app.services import report_layout_bundle, report_snippet_scope, report_snippet_store
from app.services.bundle_common import BundleImportWarnings

PROJECT_KEY = "report_snippets"
HIDDEN_KEY = "report_snippets_hidden"
ORG_KEY = "report_snippets"
IMAGES_KEY = "report_snippet_images"


def snippet_entry(row: SavedReportSnippet) -> dict[str, Any]:
    """One saved snippet as its bundle entry (no ids, author or time)."""
    return {
        "name": row.name, "description": row.description, "category": row.category, "family": row.family,
        "blocks": row.blocks, "root": row.root,
    }


def _image_entries(
    db: Session, entries: list[dict[str, Any]], organization_id: uuid.UUID, project_id: uuid.UUID | None,
    assets: dict[uuid.UUID, FileAsset],
) -> list[dict[str, Any]]:
    """The pictures the exported snippets use (the layouts' picture entries over the fragments as one-version trees)."""
    shaped = [{"versions": [{"tree": {"nodes": e["blocks"], **e["root"]}}]} for e in entries]
    return report_layout_bundle.image_entries(db, shaped, organization_id, project_id, assets)


def export_project_snippets(db: Session, project: Project, assets: dict[uuid.UUID, FileAsset]) -> dict[str, Any]:
    """The project's own snippets, the inherited snippets it hides (by name) and the pictures they use, as `project.json` sections."""
    own = db.scalars(
        select(SavedReportSnippet).where(SavedReportSnippet.project_id == project.id).order_by(SavedReportSnippet.name)
    ).all()
    entries = [snippet_entry(row) for row in own]
    hidden = [
        {"name": s.snippet.name, "origin": s.origin}
        for s in report_snippet_scope.resolve_project_snippets(db, project) if s.hidden
    ]
    return {PROJECT_KEY: entries, HIDDEN_KEY: hidden, IMAGES_KEY: _image_entries(db, entries, project.organization_id, project.id, assets)}


def export_org_snippets(db: Session, organization_id: uuid.UUID, assets: dict[uuid.UUID, FileAsset]) -> dict[str, Any]:
    """The organisation's own snippets and the pictures they use, as `org.json` sections."""
    entries = [snippet_entry(row) for row in report_snippet_scope.list_org_snippets(db, organization_id)]
    return {ORG_KEY: entries, IMAGES_KEY: _image_entries(db, entries, organization_id, None, assets)}


def import_snippet_entry(
    db: Session, entry: dict[str, Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None, actor: User,
    warnings: BundleImportWarnings, existing_names: set[str] | None = None, images: dict[str, str] | None = None,
) -> SavedReportSnippet | None:
    """Creates one snippet from its bundle entry. Returns the new row, or `None` when none was stored.

    `existing_names` (lower-cased names the owner already has) switches on the merge rule: a taken name is imported as
    "<name> (imported)". `images` maps the bundle's picture ids to the imported ones.
    """
    name = str(entry.get("name", "")).strip()
    blocks, root = entry.get("blocks"), entry.get("root") or {}
    if existing_names is not None and name.casefold() in existing_names:
        name = f"{name} (imported)"
    if not isinstance(blocks, list) or not isinstance(root, dict):
        warnings.add(f'Report snippet "{name}" was skipped: it is not a list of blocks.')
        return None
    carried = report_layout_bundle.rewrite_images({"nodes": blocks, **root}, images or {})
    blocks = carried.pop("nodes")
    try:
        row = report_snippet_store.create_snippet(
            db, organization_id=organization_id, project_id=project_id, name=name,
            description=str(entry.get("description", "")), category=str(entry.get("category", "")),
            family=str(entry.get("family")), blocks=blocks, root=carried, actor_id=actor.id,
        )
    except report_snippet_store.SnippetNameTakenError:
        warnings.add(f'Report snippet "{name}" was skipped: a snippet with that name already exists.')
        return None
    except report_snippet_store.SnippetSaveError:
        warnings.add(f'Report snippet "{name}" was skipped: it is not valid in this installation.')
        return None
    return row


def import_org_snippets(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings, *,
    merge: bool, file_bytes_by_ref: dict[str, bytes],
) -> int:
    """Imports the `org.json` snippets and their pictures. `merge` is true when the organisation already exists.

    Returns:
        How many snippets were stored.
    """
    existing = (
        {n.casefold() for n in db.scalars(select(SavedReportSnippet.name).where(
            SavedReportSnippet.organization_id == organization_id, SavedReportSnippet.project_id.is_(None)))}
        if merge else None
    )
    images = report_layout_bundle.import_images(
        db, data.get(IMAGES_KEY), file_bytes_by_ref, organization_id=organization_id, project_id=None, actor=actor,
        warnings=warnings,
    )
    return sum(
        import_snippet_entry(
            db, entry, organization_id=organization_id, project_id=None, actor=actor, warnings=warnings,
            existing_names=existing, images=images,
        ) is not None
        for entry in data.get(ORG_KEY, []) if isinstance(entry, dict)
    )


def import_project_snippets(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
    file_bytes_by_ref: dict[str, bytes],
) -> None:
    """Imports a `project.json`'s own snippets and their pictures, then re-applies the hides to the snippets it inherits."""
    images = report_layout_bundle.import_images(
        db, data.get(IMAGES_KEY), file_bytes_by_ref, organization_id=project.organization_id, project_id=project.id,
        actor=actor, warnings=warnings,
    )
    for entry in data.get(PROJECT_KEY, []):
        if isinstance(entry, dict):
            import_snippet_entry(
                db, entry, organization_id=project.organization_id, project_id=project.id, actor=actor, warnings=warnings,
                images=images,
            )
    hidden_names = [str(h.get("name", "")) for h in data.get(HIDDEN_KEY, []) if isinstance(h, dict)]
    if not hidden_names:
        return
    inherited = {
        s.snippet.name.casefold(): s.snippet.id
        for s in report_snippet_scope.resolve_project_snippets(db, project) if s.origin != "project"
    }
    for name in hidden_names:
        snippet_id = inherited.get(name.casefold())
        if snippet_id is None:
            warnings.add(f'Hidden report snippet "{name}" was not applied: this project inherits no snippet of that name.')
            continue
        report_snippet_scope.hide_snippet(db, project, snippet_id, actor_id=actor.id)


__all__ = [
    "export_org_snippets", "export_project_snippets", "import_org_snippets", "import_project_snippets", "import_snippet_entry",
    "snippet_entry",
]
