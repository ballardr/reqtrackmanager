"""
Module: modules.product_feedback.vocabulary_bundle

Bundle (export / import) halves of the module's two classified lists (`vocabularies.py`), shared so the external
system list and the request channel list travel the same way:

- Organisation level: the organisation's entries by name, order and active flag; an import skips names the
  organisation already has, so a fresh organisation's seeded defaults are not doubled.
- Project level: the project's own rows (an override of an organisation entry by its name, or a project-local entry)
  and the organisation entries it has hidden, by name.
- `NameResolver`: turns an entry name in an imported record into the row the record stores, creating a
  passthrough row for an organisation entry and a project-local entry for a name nothing matches (with a warning), so
  a reference or channel is never silently dropped.

Cross-references are always by name, never id, so a bundle moves between organisations.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.services.bundle_common import BundleImportWarnings
from app.services.type_vocabulary import TypeVocabulary

#: The longest an entry name may be (the column's width); a longer name in a bundle is skipped, not truncated.
MAX_NAME_LENGTH = 100


def export_org_list(db: Session, org: Organization, vocabulary: TypeVocabulary) -> list[dict[str, Any]]:
    """The organisation's entries of `vocabulary` in order."""
    model = vocabulary.org_model
    rows = db.scalars(select(model).where(model.organization_id == org.id).order_by(model.sort_order)).all()
    return [{"name": r.name, "sort_order": r.sort_order, "is_active": r.is_active} for r in rows]


def import_org_list(db: Session, org: Organization, vocabulary: TypeVocabulary, rows: list[dict[str, Any]]) -> None:
    """Adds the bundle's entries the organisation does not already have (by name)."""
    model = vocabulary.org_model
    existing = {r.name for r in db.scalars(select(model).where(model.organization_id == org.id))}
    for row in rows:
        if row["name"] in existing or not row["name"] or len(row["name"]) > MAX_NAME_LENGTH:
            continue
        db.add(model(
            organization_id=org.id, name=row["name"], sort_order=row.get("sort_order", len(existing)),
            is_active=row.get("is_active", True),
        ))
        existing.add(row["name"])
    db.flush()


def export_project_list(db: Session, project: Project, vocabulary: TypeVocabulary) -> dict[str, Any]:
    """The project's own rows and hidden organisation entries for `vocabulary`."""
    own = list(db.scalars(select(vocabulary.project_model).where(vocabulary.project_model.project_id == project.id)))
    org_ids = {r.org_type_id for r in own if r.org_type_id is not None}
    org_names = {
        t.id: t.name for t in db.scalars(select(vocabulary.org_model).where(vocabulary.org_model.id.in_(org_ids)))
    } if org_ids else {}
    return {
        "rows": [
            {
                "org_type_name": org_names.get(r.org_type_id) if r.org_type_id else None, "name_override": r.name_override,
                "display_order_override": r.display_order_override, "is_enabled": r.is_enabled,
            }
            for r in own
        ],
        "hidden": vocabulary.hidden_names(db, project.id, project.organization_id),
    }


class NameResolver:
    """Resolves entry names to the rows an imported record stores.

    Args:
        db: Active session (rows may be added; the caller commits).
        vocabulary: The list.
        organization_id: The target organisation.
        project: The target project, or `None` for the organisation tier (entries resolve to organisation ids).
        warnings: Where a name nothing matched is reported.
        what: Singular noun for warnings (e.g. "external system").
    """

    def __init__(
        self, db: Session, vocabulary: TypeVocabulary, organization_id: uuid.UUID, project: Project | None,
        warnings: BundleImportWarnings, what: str,
    ) -> None:
        self.db = db
        self.vocabulary = vocabulary
        self.organization_id = organization_id
        self.project = project
        self.warnings = warnings
        self.what = what
        self._local: dict[str, uuid.UUID] = {}
        self._org = {
            t.name: t for t in db.scalars(select(vocabulary.org_model).where(vocabulary.org_model.organization_id == organization_id))
        }

    def import_project_rows(self, rows: list[dict[str, Any]]) -> None:
        """Recreates the bundle's project rows (overrides and project-local entries); call before resolving names."""
        assert self.project is not None
        for t in rows:
            if t.get("org_type_name"):
                org_type = self._org.get(t["org_type_name"])
                if org_type is None:
                    self.warnings.add(f"The {self.what} override for {t['org_type_name']!r} was skipped — the organisation has no such entry.")
                    continue
                row = self.vocabulary.get_or_create_project_type(self.db, self.project.id, self.organization_id, org_type.id)
                self.vocabulary.set_override(
                    self.db, row, name=t.get("name_override"), display_order=t.get("display_order_override"),
                    is_enabled=t.get("is_enabled"),
                )
                self._local[t.get("name_override") or org_type.name] = row.id
            else:
                row = self.vocabulary.create_project_local(
                    self.db, self.project.id, t["name_override"], display_order=t.get("display_order_override"),
                )
                row.is_enabled = t.get("is_enabled", True)
                self._local[t["name_override"]] = row.id

    def row_id(self, name: str | None) -> uuid.UUID | None:
        """The id to store for the entry called `name`: the project row (a project), or the organisation's entry
        (the organisation tier). `None`, with a warning, when it cannot be placed."""
        if not name:
            return None
        if len(name) > MAX_NAME_LENGTH:
            self.warnings.add(f"A {self.what} name longer than {MAX_NAME_LENGTH} characters was skipped.")
            return None
        if self.project is None:
            org_type = self._org.get(name)
            if org_type is None:
                self.warnings.add(f"The {self.what} {name!r} was skipped — the organisation has no such entry.")
                return None
            return org_type.id
        if name in self._local:
            return self._local[name]
        org_type = self._org.get(name)
        if org_type is not None and org_type.is_active:
            try:
                return self.vocabulary.get_or_create_project_type(
                    self.db, self.project.id, self.organization_id, org_type.id,
                ).id
            except ValueError:
                pass
        row = self.vocabulary.create_project_local(self.db, self.project.id, name)
        self._local[name] = row.id
        self.warnings.add(f"The {self.what} {name!r} is not in the organisation's list — added to the project as its own entry.")
        return row.id

    def hide(self, names: list[str]) -> None:
        """Hides the organisation entries named in the bundle (call last: a record above may use one)."""
        assert self.project is not None
        for name in self.vocabulary.hide_by_names(self.db, self.project.id, self.organization_id, names):
            self.warnings.add(f"The hidden {self.what} {name!r} was skipped — the organisation has no such entry.")
