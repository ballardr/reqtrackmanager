"""
Module: modules.stakeholders.type_vocabulary

Generic two-tier type vocabulary (Phase 0 resolution 3): an org base list
plus per-project rename/reorder/disable/add, shared by every typed artefact
in this module (Persona now; Stakeholder in Phase 1.2) so each is a
`TypeVocabulary` instance rather than a copy of Context & Strategy's
Pain-Point-specific functions.

Design decisions:
- No ancestor fallback for nested projects: the org list is the base every
  project already sees, so an empty project table already means "use org
  defaults" (resolution 3, Decided by: Agent).
- Org types are never deleted while referenced; a project is asked to stop
  using one, or it is disabled instead. Cross-project reassignment has no
  single correct target (same reasoning as Pain Point types).
- `EffectiveType.id` is either an org type id (no override yet) or a project
  type row id; `get_or_create_project_type` resolves either, lazily creating a
  passthrough row the first time an org type is selected.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class EffectiveType:
    """One row of a project's merged type list.

    Attributes:
        id: Org type id (`source == "org"`) or project type row id
            (`"project_override"`/`"project_local"`).
        name: Effective display name.
        display_order: Effective picker order.
        is_enabled: Disabled types stay listed (so they can be re-enabled)
            but are rejected when selected.
        source: `"org"`, `"project_override"` or `"project_local"`.
    """

    id: uuid.UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


class TypeVocabulary:
    """Operations over one artefact's org/project type tables.

    Args:
        label: Singular noun used in error messages (e.g. "Persona type").
        org_model: The org-level definition model (`organization_id`, `name`,
            `sort_order`, `is_active`).
        project_model: The project-level model (`project_id`, `org_type_id`,
            `name_override`, `display_order_override`, `is_enabled`).
        default_names: Names seeded for each new organisation.
        org_type_in_use: `(db, org_type_id) -> bool`, whether any artefact
            row references the org type directly.
        project_type_in_use: `(db, project_type_id) -> bool`, whether any
            artefact row references the project type row.
    """

    def __init__(
        self, *, label: str, org_model, project_model, default_names: tuple[str, ...],
        org_type_in_use: Callable[[Session, uuid.UUID], bool],
        project_type_in_use: Callable[[Session, uuid.UUID], bool],
    ) -> None:
        self.label = label
        self.org_model = org_model
        self.project_model = project_model
        self.default_names = default_names
        self._org_type_in_use = org_type_in_use
        self._project_type_in_use = project_type_in_use

    def seed_defaults(self, db: Session, organization_id: uuid.UUID) -> None:
        """Adds the default org types for a new organisation. The caller owns
        the transaction."""
        for i, name in enumerate(self.default_names):
            db.add(self.org_model(organization_id=organization_id, name=name, sort_order=i, is_active=True))

    def create_org_type(self, db: Session, organization_id: uuid.UUID, name: str):
        """Creates an org type at the end of the organisation's order.

        Raises:
            ValueError: If the organisation already has a type with `name`.
        """
        if db.scalar(
            select(self.org_model.id).where(self.org_model.organization_id == organization_id, self.org_model.name == name)
        ) is not None:
            raise ValueError(f"A {self.label} named {name!r} already exists for this organisation.")
        count = len(db.scalars(select(self.org_model.id).where(self.org_model.organization_id == organization_id)).all())
        org_type = self.org_model(organization_id=organization_id, name=name, sort_order=count)
        db.add(org_type)
        db.flush()
        return org_type

    def delete_org_type(self, db: Session, org_type) -> None:
        """Deletes an org type.

        Raises:
            ValueError: If a project row or an artefact still references it.
        """
        referenced = db.scalar(select(self.project_model.id).where(self.project_model.org_type_id == org_type.id).limit(1))
        if referenced is not None or self._org_type_in_use(db, org_type.id):
            raise ValueError(
                f"This {self.label} is still in use and cannot be removed. "
                "Disable it instead, or ask each referencing project to stop using it first."
            )
        db.delete(org_type)
        db.flush()

    def resolve_effective(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> list[EffectiveType]:
        """A project's effective list: every active org type (with the
        project's override applied) plus every project-local type, ordered
        by effective display order."""
        org_types = db.scalars(
            select(self.org_model).where(self.org_model.organization_id == organization_id, self.org_model.is_active.is_(True))
        ).all()
        rows = db.scalars(select(self.project_model).where(self.project_model.project_id == project_id)).all()
        overrides = {r.org_type_id: r for r in rows if r.org_type_id is not None}
        effective: list[EffectiveType] = []
        for org_type in org_types:
            o = overrides.get(org_type.id)
            if o is None:
                effective.append(EffectiveType(org_type.id, org_type.name, org_type.sort_order, True, "org"))
            else:
                effective.append(EffectiveType(
                    o.id, o.name_override if o.name_override is not None else org_type.name,
                    o.display_order_override if o.display_order_override is not None else org_type.sort_order,
                    o.is_enabled, "project_override",
                ))
        for r in rows:
            if r.org_type_id is None:
                effective.append(EffectiveType(r.id, r.name_override or "", r.display_order_override or 0, r.is_enabled, "project_local"))
        effective.sort(key=lambda e: e.display_order)
        return effective

    def get_or_create_project_type(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID):
        """Resolves an `EffectiveType.id` to a project row, creating a
        passthrough row the first time an org type is selected.

        Raises:
            ValueError: If the id is not a type this project can use.
        """
        existing = db.get(self.project_model, type_ref_id)
        if existing is not None and existing.project_id == project_id:
            return existing
        org_type = db.get(self.org_model, type_ref_id)
        if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
            raise ValueError(f"This is not a valid {self.label} for this project.")
        passthrough = db.scalar(
            select(self.project_model).where(self.project_model.project_id == project_id, self.project_model.org_type_id == org_type.id)
        )
        if passthrough is not None:
            return passthrough
        passthrough = self.project_model(project_id=project_id, org_type_id=org_type.id, is_enabled=True)
        db.add(passthrough)
        db.flush()
        return passthrough

    def create_project_local(self, db: Session, project_id: uuid.UUID, name: str, *, display_order: int | None = None):
        """Creates a fully project-local type.

        Raises:
            ValueError: If the project already has a local type named `name`.
        """
        if db.scalar(
            select(self.project_model.id).where(
                self.project_model.project_id == project_id, self.project_model.org_type_id.is_(None),
                self.project_model.name_override == name,
            )
        ) is not None:
            raise ValueError(f"A project-local {self.label} named {name!r} already exists for this project.")
        if display_order is None:
            display_order = len(db.scalars(select(self.project_model.id).where(self.project_model.project_id == project_id)).all())
        row = self.project_model(project_id=project_id, org_type_id=None, name_override=name, display_order_override=display_order, is_enabled=True)
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def set_override(db: Session, row, *, name: str | None = None, display_order: int | None = None, is_enabled: bool | None = None):
        """Partial update of a project type row; only non-`None` fields change."""
        if name is not None:
            row.name_override = name
        if display_order is not None:
            row.display_order_override = display_order
        if is_enabled is not None:
            row.is_enabled = is_enabled
        db.flush()
        return row

    def delete_project_type(self, db: Session, row) -> None:
        """Deletes a project type row (an org override reverts to the org
        default; a local type is removed).

        Raises:
            ValueError: If an artefact still references the row.
        """
        if self._project_type_in_use(db, row.id):
            raise ValueError(f"This {self.label} is still in use and cannot be removed.")
        db.delete(row)
        db.flush()

    def display_name(self, db: Session, *, org_type_id: uuid.UUID | None, project_type_id: uuid.UUID | None) -> str | None:
        """Effective name for whichever reference an artefact version holds,
        or `None` when untyped."""
        if project_type_id is not None:
            row = db.get(self.project_model, project_type_id)
            if row is None:
                return None
            if row.name_override is not None:
                return row.name_override
            org_type = db.get(self.org_model, row.org_type_id) if row.org_type_id else None
            return org_type.name if org_type is not None else None
        if org_type_id is not None:
            org_type = db.get(self.org_model, org_type_id)
            return org_type.name if org_type is not None else None
        return None
