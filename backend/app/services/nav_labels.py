"""
Module: services.nav_labels

Navigation names: a project or an organisation renames an entry of the project navigation ("Decisions" to
"ADRs"), and the new name is shown in the navigation, the page title, the breadcrumb-style back link and the
module's own page heading.

Responsibilities:
- Define the stable navigation keys: a fixed key for each core entry and one derived from the registry for each
  module entry (`nav_key`), so a key never contains a project id and means the same in every project.
- Validate an override map (known keys only, plain single-line text, length limited).
- Resolve the effective name per key for a project: its own name, else the nearest ancestor's, else the
  organisation's, else none (the built-in name applies).
- Set the project's or the organisation's own names, audited with the keys changed and never the text.

Design decisions:
- Resolution is per key, not all-or-nothing: a child project that renames one entry still inherits the others.
- Keys are validated against every registered module entry, whether or not the module is enabled, so switching a
  module off does not invalidate the names stored for it; the catalogue shown to a person lists only what the
  project (or organisation) can currently reach.
- Only the navigation name changes. Record nouns (a requirement, a change request) keep the terminology feature.
- No module is named here: module entries come from `ModuleFrontendManifest.all_nav_entries`.

External dependencies: the module registry, `services.project_hierarchy` (ancestor chain), `services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import (
    get_frontend_manifest,
    get_module_registry,
    is_module_enabled,
    is_module_enabled_for_project,
    is_module_subcomponent_enabled,
)
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.project_hierarchy import get_project_chain_ids

#: Longest navigation name accepted.
MAX_LABEL_LENGTH = 40

#: Prefix every module entry path starts with; removed to form the key.
_MODULE_PATH_PREFIX = "/projects/{project_id}/modules/"


@dataclass(frozen=True)
class NavItem:
    """One entry of the project navigation as the catalogue lists it.

    Attributes:
        key: Stable navigation key.
        label: Built-in name in English.
        path: Route with `{project_id}` still in it.
        module_key: Owning module's key, `None` for a core entry.
    """

    key: str
    label: str
    path: str
    module_key: str | None = None


#: Core entries in navigation order. The built-in names here are the English defaults; a page that
#: resolves a noun through the terminology feature supplies its own built-in name on the client.
CORE_ITEMS: tuple[NavItem, ...] = (
    NavItem("overview", "Overview", "/projects/{project_id}"),
    NavItem("requirements", "Requirements", "/projects/{project_id}/requirements"),
    NavItem("change-requests", "Change requests", "/projects/{project_id}/change-requests"),
    NavItem("actions", "Actions", "/projects/{project_id}/actions"),
    NavItem("files", "Files", "/projects/{project_id}/files"),
    NavItem("reviews-due", "Reviews due", "/projects/{project_id}/reviews-due"),
    NavItem("stage-phases", "Stage phases", "/projects/{project_id}/stage-phases"),
    NavItem("history", "History", "/projects/{project_id}/history"),
    NavItem("admin", "Project administration", "/projects/{project_id}/admin"),
)


def nav_key(module_key: str, nav_path: str) -> str:
    """The stable key of a module's navigation entry.

    Args:
        module_key: The module's registry key.
        nav_path: The entry's path template (with `{project_id}` unresolved).

    Returns:
        `<module_key>:<path below the module root>`, or `<module_key>:` for the module's own landing page.
    """
    tail = nav_path.removeprefix(_MODULE_PATH_PREFIX + module_key).strip("/") if nav_path.startswith(_MODULE_PATH_PREFIX) else nav_path
    return f"{module_key}:{tail}"


def module_items() -> list[NavItem]:
    """Every module navigation entry in the registry, enabled or not, in registration order."""
    items: list[NavItem] = []
    for module_key in get_module_registry():
        manifest = get_frontend_manifest(module_key)
        if manifest is None:
            continue
        for entry in manifest.all_nav_entries():
            items.append(NavItem(nav_key(module_key, entry.nav_path), entry.nav_label, entry.nav_path, module_key))
    return items


def valid_keys() -> frozenset[str]:
    """Every key an override may use."""
    return frozenset(item.key for item in (*CORE_ITEMS, *module_items()))


def catalogue_for_project(db: Session, project: Project) -> list[NavItem]:
    """The entries the project's navigation can show: the core entries and those of each module enabled for the project.

    An entry whose sub-component is off for the project is left out, as the navigation leaves it out.
    """
    items = list(CORE_ITEMS)
    for module_key in get_module_registry():
        if not is_module_enabled_for_project(db, project.id, module_key):
            continue
        manifest = get_frontend_manifest(module_key)
        if manifest is None:
            continue
        for entry in manifest.all_nav_entries():
            if entry.sub_component and not is_module_subcomponent_enabled(db, project.id, module_key, entry.sub_component):
                continue
            items.append(NavItem(nav_key(module_key, entry.nav_path), entry.nav_label, entry.nav_path, module_key))
    return items


def catalogue_for_organization(db: Session, organization_id: uuid.UUID) -> list[NavItem]:
    """The entries an organisation default can name: the core entries and those of each module the organisation has enabled."""
    items = list(CORE_ITEMS)
    items.extend(item for item in module_items() if item.module_key and is_module_enabled(db, organization_id, item.module_key))
    return items


def validate_overrides(values: dict[str, str]) -> dict[str, str]:
    """Checks an override map and returns it cleaned (names trimmed, blank names dropped).

    Raises:
        HTTPException: 422 for an unknown key, or a name that is too long or has a line break or control character.
    """
    known = valid_keys()
    cleaned: dict[str, str] = {}
    for key, raw in values.items():
        if key not in known:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown navigation entry.")
        name = " ".join(raw.split()) if isinstance(raw, str) else ""
        if len(name) > MAX_LABEL_LENGTH:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"A navigation name may have at most {MAX_LABEL_LENGTH} characters.")
        if any(not ch.isprintable() for ch in name):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A navigation name must be plain text.")
        if name:
            cleaned[key] = name
    return cleaned


@dataclass(frozen=True)
class ResolvedName:
    """The name that applies to one key and where it comes from (`own`, `ancestor`, `organisation` or `none`)."""

    value: str | None
    source: str


def inherited_names(db: Session, project: Project) -> dict[str, ResolvedName]:
    """What each key would be named with the project's own names removed: the nearest ancestor's, else the organisation's."""
    resolved: dict[str, ResolvedName] = {}
    org = db.get(Organization, project.organization_id)
    for key, value in (org.nav_label_overrides if org else {}).items():
        resolved[key] = ResolvedName(value, "organisation")
    # Farthest ancestor first so a nearer one overwrites it.
    for project_id in reversed(get_project_chain_ids(db, project.id)[1:]):
        for key, value in (db.scalar(select(Project.nav_label_overrides).where(Project.id == project_id)) or {}).items():
            resolved[key] = ResolvedName(value, "ancestor")
    return resolved


def effective_names(db: Session, project: Project) -> dict[str, ResolvedName]:
    """The name that applies to each key that has one for `project`: its own, else inherited."""
    resolved = inherited_names(db, project)
    for key, value in (project.nav_label_overrides or {}).items():
        resolved[key] = ResolvedName(value, "own")
    return resolved


def set_project_names(db: Session, project: Project, values: dict[str, str], actor_id: uuid.UUID) -> None:
    """Replaces the project's own names (an absent key follows what it inherits); audited, not committed.

    Raises:
        HTTPException: 422 when `validate_overrides` refuses the map.
    """
    cleaned = validate_overrides(values)
    previous = project.nav_label_overrides or {}
    changed = sorted({k for k in set(cleaned) | set(previous) if cleaned.get(k) != previous.get(k)})
    project.nav_label_overrides = cleaned
    log_event(
        db, entity_type="nav_labels", entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail={"keys": changed, "count": len(cleaned)},
    )


def set_organization_names(db: Session, organization: Organization, values: dict[str, str], actor_id: uuid.UUID) -> None:
    """Replaces the organisation's default names; audited, not committed.

    Raises:
        HTTPException: 422 when `validate_overrides` refuses the map.
    """
    cleaned = validate_overrides(values)
    previous = organization.nav_label_overrides or {}
    changed = sorted({k for k in set(cleaned) | set(previous) if cleaned.get(k) != previous.get(k)})
    organization.nav_label_overrides = cleaned
    log_event(
        db, entity_type="nav_labels", entity_id=organization.id, action="updated", actor_id=actor_id,
        organization_id=organization.id, detail={"keys": changed, "count": len(cleaned)},
    )


#: Section of `project.json` and of the organisation bundle that carries the names.
BUNDLE_KEY = "nav_label_overrides"


def export_names(names: dict[str, str] | None) -> dict[str, dict[str, str]]:
    """A project's or organisation's own names as a bundle section."""
    return {BUNDLE_KEY: dict(names or {})}


def import_names(data: dict[str, object], warnings: BundleImportWarnings, current: dict[str, str] | None = None) -> dict[str, str]:
    """The names an import leaves in place: `current` plus the bundle's, the bundle's winning where both name a key.

    A name for a key this installation does not know (a module that is not installed), or one that is not valid
    plain text, is skipped with a warning; the rest are kept.
    """
    result = dict(current or {})
    raw = data.get(BUNDLE_KEY)
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            result.update(validate_overrides({str(key): value} if isinstance(value, str) else {}))
        except HTTPException:
            warnings.add("A navigation name in the bundle was not imported because its entry is not available here or the name is not valid.")
    return result
