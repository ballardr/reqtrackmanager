"""
Module: modules.architecture.export

The Architecture module's contribution to the organisation and project bundles:
the organisation's default element and connection types, and a project's own types
with the organisation defaults it has hidden. Registered through
`ModuleOrgBundleHooks` and `ModuleProjectBundleHooks`, so no core export file
names this module.

Design decisions:
- A project exports the configuration it owns (rows and tombstones), not an
  ancestor's it merely inherits: the project the bundle is imported into has its own
  ancestors.
- Types travel by name. An import skips a name the target already lists (so a fresh
  organisation's seeded defaults are not doubled) and reports a hidden default the
  organisation does not have.
- All four project keys are configuration, so a template project carries them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.architecture.service import (
    CONNECTION_TYPES,
    ELEMENT_TYPES,
    ArchitectureVocabulary,
)
from app.services import definition_suppression
from app.services.bundle_common import BundleImportWarnings, UserResolver

ORG_ELEMENT_TYPES_KEY = "architecture_element_types"
ORG_CONNECTION_TYPES_KEY = "architecture_connection_types"
PROJECT_ELEMENT_TYPES_KEY = "architecture_project_element_types"
PROJECT_CONNECTION_TYPES_KEY = "architecture_project_connection_types"
HIDDEN_ELEMENT_TYPES_KEY = "architecture_hidden_element_types"
HIDDEN_CONNECTION_TYPES_KEY = "architecture_hidden_connection_types"

#: Each vocabulary with the bundle key of its organisation rows, its project rows and its hidden defaults.
_VOCABULARIES: tuple[tuple[ArchitectureVocabulary, str, str, str], ...] = (
    (ELEMENT_TYPES, ORG_ELEMENT_TYPES_KEY, PROJECT_ELEMENT_TYPES_KEY, HIDDEN_ELEMENT_TYPES_KEY),
    (CONNECTION_TYPES, ORG_CONNECTION_TYPES_KEY, PROJECT_CONNECTION_TYPES_KEY, HIDDEN_CONNECTION_TYPES_KEY),
)

#: Project bundle keys, for the template classification.
PROJECT_KEYS = frozenset(key for _v, _o, project_key, hidden_key in _VOCABULARIES for key in (project_key, hidden_key))


def _row_json(vocabulary: ArchitectureVocabulary, row) -> dict[str, Any]:
    """A row's bundle form: every column except identity, owner and timestamps."""
    return {column: getattr(row, column) for column in vocabulary.copied_columns()}


def _add_rows(
    db: Session, vocabulary: ArchitectureVocabulary, entries: list[dict[str, Any]], *, taken: set[str], owner: dict[str, Any],
) -> None:
    """Adds the bundle rows whose name is not in `taken`, keeping their order after the owner's existing rows."""
    columns = set(vocabulary.copied_columns())
    for entry in entries:
        name = entry.get("name")
        if not name or name.lower() in taken:
            continue
        db.add(vocabulary.model(**owner, **{k: v for k, v in entry.items() if k in columns}))
        taken.add(name.lower())
    db.flush()


# --- Organisation level ------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's default element and connection types."""
    return {
        org_key: [_row_json(vocabulary, row) for row in vocabulary.org_rows(db, org.id)]
        for vocabulary, org_key, _project_key, _hidden_key in _VOCABULARIES
    }


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates the defaults, skipping names the organisation already has."""
    for vocabulary, org_key, _project_key, _hidden_key in _VOCABULARIES:
        rows = vocabulary.org_rows(db, org.id)
        taken = {r.name.lower() for r in rows}
        _add_rows(db, vocabulary, data.get(org_key, []), taken=taken, owner={"organization_id": org.id})


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict]:
    """`ModuleProjectBundleHooks.export`: the project's own types and the organisation defaults it has hidden
    (no file is bundled yet)."""
    data: dict[str, Any] = {}
    for vocabulary, _org_key, project_key, hidden_key in _VOCABULARIES:
        data[project_key] = [_row_json(vocabulary, row) for row in vocabulary.project_rows(db, project.id)]
        hidden = definition_suppression.get_suppressed_ids(db, project.id, vocabulary.kind)
        data[hidden_key] = [r.name for r in vocabulary.org_rows(db, project.organization_id) if r.id in hidden]
    return data, {}


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's own types and hides the organisation defaults
    it had hidden. A name the project already lists is skipped; a hidden default the organisation lacks is reported."""
    for vocabulary, _org_key, project_key, hidden_key in _VOCABULARIES:
        entries = data.get(project_key, [])
        if entries:
            taken = {r.name.lower() for r in vocabulary.resolve_effective(db, project.id, project.organization_id).rows}
            _add_rows(db, vocabulary, entries, taken=taken, owner={"project_id": project.id})
        for name in vocabulary.hide_by_names(db, project.id, project.organization_id, data.get(hidden_key, [])):
            warnings.add(f"{vocabulary.label} {name!r} was hidden in the source project but the organisation has no such type.")
