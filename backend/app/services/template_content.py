"""
Module: services.template_content

The configuration and starter content a project created from a template receives beyond what
`services.templates.clone_project` copies for the core record types:

- the project's plain settings (review reminder lead days, tag mode) and tag vocabulary,
- module enablement (which modules and sub-components the template has on, still capped by what
  the organisation allows),
- report setup (layouts, packs, snippets, placements, folders),
- every module's configuration and starter records, through its `ModuleProjectBundleHooks`,
- the project's own scoring configuration (`services.scoring_config`).

Design decisions:
- Modules are copied by re-using their bundle export and import (the same round-trip code a project
  bundle relies on), filtered to the keys the module declares (`template_configuration_keys`,
  `template_record_keys`) and with `template_reset` returning the records to their starting state.
  No per-module clone code exists, and a module cannot add a bundle key without classifying it.
- Starter records are fresh drafts: initial status, never archived, no reviews, votes, scores or other
  history, numbered afresh, owned by the person creating the project when the original owner cannot be
  carried. An approval gate is never bypassed because no approval state is copied.
- Links are copied, including those to requirements: a clone keeps the template's requirement codes, so
  a link names the same requirement in the new project.

External dependencies: the module registry, the report setup bundle helpers and the file storage backend.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.module import ProjectModuleEnablement, ProjectModuleSubComponentEnablement
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    get_all_module_project_bundle_hooks,
    get_module_registry,
    is_module_enabled,
    resolve_org_subcomponent_state,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.files import read_file, resolve_bundle_files
from app.services.report_folder_bundle import export_project_folders, import_project_folders
from app.services.report_layout_bundle import export_project_layouts, import_project_layouts
from app.services.report_pack_bundle import export_project_packs, import_project_packs
from app.services.report_placement_bundle import export_project_placements, import_project_placements
from app.services.report_snippet_bundle import export_project_snippets, import_project_snippets
from app.services.scoring_config import export_project_scoring, import_project_scoring
from app.services.tags import export_vocabulary, import_vocabulary


def _file_refs(value: Any, found: set[str]) -> None:
    """Collects every `file_ref` string in a nested bundle structure."""
    if isinstance(value, dict):
        ref = value.get("file_ref")
        if isinstance(ref, str):
            found.add(ref)
        for item in value.values():
            _file_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _file_refs(item, found)


def copy_module_enablement(db: Session, source: Project, new_project: Project) -> None:
    """Copies the template's explicit module and sub-component switches to the new project.

    A switch is copied only where the organisation still allows the module or sub-component: an
    organisation's hard Off reaches every project (`snapshot_project_module_state` has the same floor).
    Anything the template left to the organisation default is filled in by `snapshot_project_module_state`
    afterwards, which skips a row that exists.

    Args:
        db: An active database session; rows are flushed by the caller's commit.
        source: The template project.
        new_project: The new project (already flushed).
    """
    registry = get_module_registry()
    for row in db.scalars(select(ProjectModuleEnablement).where(ProjectModuleEnablement.project_id == source.id)).all():
        if row.module_key in registry and is_module_enabled(db, new_project.organization_id, row.module_key):
            db.add(ProjectModuleEnablement(project_id=new_project.id, module_key=row.module_key, enabled=row.enabled))
    for sub in db.scalars(
        select(ProjectModuleSubComponentEnablement).where(ProjectModuleSubComponentEnablement.project_id == source.id)
    ).all():
        state = resolve_org_subcomponent_state(db, new_project.organization_id, sub.module_key, sub.subcomponent_key)
        definition = registry[sub.module_key].sub_components if sub.module_key in registry else ()
        if any(s.key == sub.subcomponent_key and s.organization_only for s in definition):
            continue
        if state is not None and state[0] and is_module_enabled(db, new_project.organization_id, sub.module_key):
            db.add(ProjectModuleSubComponentEnablement(
                project_id=new_project.id, module_key=sub.module_key, subcomponent_key=sub.subcomponent_key, enabled=sub.enabled,
            ))
    db.flush()


def copy_project_setup(
    db: Session, source: Project, new_project: Project, creator: User, warnings: BundleImportWarnings,
    skip_files: bool = False,
) -> None:
    """Copies plain settings, the tag vocabulary and report setup from the template.

    Args:
        db: An active database session; flushed, not committed.
        source: The template project.
        new_project: The new project (already flushed).
        creator: The user creating the project (recorded as the actor of the copied rows).
        warnings: Collects anything that could not be copied.
        skip_files: Copy without the template's files; honoured only while files cannot be stored.

    Raises:
        HTTPException: 403 (`uploads_disabled`) when the template has files, they cannot be stored and `skip_files`
            is not set.
    """
    new_project.review_reminder_lead_days_default = source.review_reminder_lead_days_default
    import_vocabulary(db, new_project, export_vocabulary(db, source), creator.id)

    assets: dict = {}
    data: dict[str, Any] = {
        **export_project_layouts(db, source, assets), **export_project_packs(db, source),
        **export_project_placements(db, source), **export_project_snippets(db, source, assets),
        **export_project_folders(db, source),
    }
    file_bytes = {f"{a.id}_{a.filename}": read_file(a) for a in assets.values()}
    file_bytes = resolve_bundle_files(db, new_project.organization_id, file_bytes, skip_files=skip_files, warn=warnings.add)
    import_project_layouts(db, new_project, data, creator, warnings, file_bytes)
    import_project_packs(db, new_project, data, creator, warnings)
    import_project_snippets(db, new_project, data, creator, warnings, file_bytes)
    import_project_placements(db, new_project, data, creator, warnings)
    import_project_folders(db, new_project, data, creator, warnings)
    db.flush()


def copy_module_content(
    db: Session, source: Project, new_project: Project, creator: User, warnings: BundleImportWarnings,
    skip_files: bool = False,
) -> None:
    """Copies every module's configuration and starter records from the template into the new project.

    Each module's bundle export is filtered to its declared template keys, its records are returned to
    fresh drafts, and the result goes through the module's own bundle import (then `import_late`, which
    runs after every module has imported).

    Args:
        db: An active database session; flushed, not committed.
        source: The template project.
        new_project: The new project, with its components, categories and tag vocabulary already copied.
        creator: The user creating the project; owns every copied record whose original creator is dropped.
        warnings: Collects anything that could not be matched (a group, a persona, a link end).
        skip_files: Copy without the template's files; honoured only while files cannot be stored.

    Raises:
        HTTPException: 403 (`uploads_disabled`) when the template has files, they cannot be stored and `skip_files`
            is not set.
    """
    users = UserResolver(db, creator, warnings, organization_id=new_project.organization_id)
    prepared = []
    refs: set[str] = set()
    assets: dict = {}
    for _key, hooks in get_all_module_project_bundle_hooks():
        keep = hooks.template_configuration_keys | hooks.template_record_keys
        if not keep:
            continue
        exported, exported_assets = hooks.export(db, source)
        data = {k: v for k, v in exported.items() if k in keep}
        if hooks.template_reset is not None:
            hooks.template_reset(data)
        _file_refs(data, refs)
        assets.update(exported_assets)
        prepared.append((hooks, data))
    file_bytes = {f"{a.id}_{a.filename}": read_file(a) for a in assets.values() if f"{a.id}_{a.filename}" in refs}
    file_bytes = resolve_bundle_files(db, new_project.organization_id, file_bytes, skip_files=skip_files, warn=warnings.add)
    for hooks, data in prepared:
        hooks.import_(db, new_project, data, file_bytes, creator, users, warnings)
    for hooks, data in prepared:
        if hooks.import_late is not None:
            hooks.import_late(db, new_project, data, file_bytes, creator, users, warnings)
    # The template's own scoring configuration (default model, offered models, bands, thresholds, cell ratings), once
    # the custom models and axes it names exist in the new project.
    import_project_scoring(db, new_project, export_project_scoring(db, source), warnings)
    db.flush()
