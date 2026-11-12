"""
Module: modules.architecture.service

The element type and connection type vocabularies: seeding an organisation's
defaults, resolving a project's effective list, and creating, editing, hiding
and deleting rows.

Responsibilities:
- `ArchitectureVocabulary`, one instance per vocabulary, holds every rule so the
  two vocabularies and their routers cannot drift.
- The default rows an organisation is created with.

Design decisions:
- A project's effective list is the organisation's rows it has not hidden plus
  the project's own rows. Nested projects (**Decided by: Agent**): a project with
  no configuration of its own (no row and no hidden default) shows the nearest
  ancestor's configuration, else the organisation's list. The first change made in
  such a project copies the inherited rows and hidden defaults into it
  (`materialize_inherited`), so a change never edits the ancestor's rows.
- Hiding stops new use only. A record that holds a hidden default keeps it,
  because it references the organisation's row directly.
- A row that records use is never deleted; `usage_checks` is where a record type
  registers its check.
- Seeding runs when an organisation is created and never for a project.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.architecture.enums import Domain, ElementShape, LineStyle
from app.modules.architecture.models import ArchitectureConnectionType, ArchitectureElementType
from app.services import definition_suppression

#: A vocabulary's model class.
VocabularyModel = type[ArchitectureElementType] | type[ArchitectureConnectionType]

ARCHITECTURE_MODULE_KEY = "architecture"
TYPE_SUBCOMPONENT_KEY = "architecture_type"
ELEMENT_SUBCOMPONENT_KEY = "architecture_element"
CONNECTION_SUBCOMPONENT_KEY = "architecture_connection"

#: The registered artefact types and the prefix of their human-readable codes.
ELEMENT_ARTEFACT_TYPE = "architecture_element"
CONNECTION_ARTEFACT_TYPE = "architecture_connection"
ELEMENT_CODE_PREFIX = "ELM"
CONNECTION_CODE_PREFIX = "CON"

ELEMENT_TYPE_KIND = "architecture_element_type"
CONNECTION_TYPE_KIND = "architecture_connection_type"

#: How many ancestors `configuration_source` walks (a guard against a corrupt tree).
_ANCESTOR_CAP = 50

#: Accent colour pair `(light, dark)` a seeded type gets, by domain.
DOMAIN_COLORS: dict[str, tuple[str, str]] = {
    Domain.SOFTWARE.value: ("#2563EB", "#60A5FA"),
    Domain.HARDWARE.value: ("#B45309", "#FBBF24"),
    Domain.ANY.value: ("#475569", "#94A3B8"),
}

#: `(name, shape, domain)` for each element type a new organisation is given.
DEFAULT_ELEMENT_TYPES: tuple[tuple[str, str, str], ...] = (
    ("System", ElementShape.ROUNDED.value, Domain.ANY.value),
    ("Subsystem", ElementShape.ROUNDED.value, Domain.ANY.value),
    ("Component", ElementShape.RECTANGLE.value, Domain.ANY.value),
    ("Service", ElementShape.HEXAGON.value, Domain.SOFTWARE.value),
    ("Container", ElementShape.RECTANGLE.value, Domain.SOFTWARE.value),
    ("Package", ElementShape.FOLDER.value, Domain.SOFTWARE.value),
    ("Datastore", ElementShape.CYLINDER.value, Domain.SOFTWARE.value),
    ("Queue", ElementShape.PARALLELOGRAM.value, Domain.SOFTWARE.value),
    ("Board", ElementShape.CHIP.value, Domain.HARDWARE.value),
    ("Sensor", ElementShape.ELLIPSE.value, Domain.HARDWARE.value),
    ("Connector", ElementShape.HEXAGON.value, Domain.HARDWARE.value),
    ("Enclosure", ElementShape.RECTANGLE.value, Domain.HARDWARE.value),
)

#: `(name, domain, directional)` for each connection type a new organisation is given.
DEFAULT_CONNECTION_TYPES: tuple[tuple[str, str, bool], ...] = (
    ("REST API", Domain.SOFTWARE.value, True),
    ("gRPC", Domain.SOFTWARE.value, True),
    ("Message queue", Domain.SOFTWARE.value, True),
    ("Event stream", Domain.SOFTWARE.value, True),
    ("Database access", Domain.SOFTWARE.value, True),
    ("File exchange", Domain.SOFTWARE.value, True),
    ("SPI", Domain.HARDWARE.value, False),
    ("I2C", Domain.HARDWARE.value, False),
    ("UART", Domain.HARDWARE.value, False),
    ("CAN", Domain.HARDWARE.value, False),
    ("Ethernet", Domain.ANY.value, False),
    ("USB", Domain.HARDWARE.value, False),
    ("Power", Domain.HARDWARE.value, True),
    ("Analogue signal", Domain.HARDWARE.value, True),
)


@dataclass(frozen=True)
class ResolvedVocabulary:
    """A project's effective list and where each row comes from.

    Attributes:
        rows: The usable rows in picker order.
        source_project_id: The project whose configuration `rows` shows (the project itself unless it inherits).
    """

    rows: list
    source_project_id: uuid.UUID


class ArchitectureVocabulary(ABC):
    """The operations over one vocabulary's single table.

    Args:
        kind: The registered `definition_suppression` kind.
        label: Singular noun for error messages (for example "Element type").
        model: The table's model.
    """

    def __init__(self, *, kind: str, label: str, model: VocabularyModel) -> None:
        self.kind = kind
        self.label = label
        self.model = model
        self.usage_checks: list[Callable[[Session, uuid.UUID], bool]] = []
        definition_suppression.register_definition_kind(kind)

    # --- Reading ---------------------------------------------------------

    def org_rows(self, db: Session, organization_id: uuid.UUID) -> list:
        """The organisation's rows in picker order."""
        m = self.model
        return list(db.scalars(select(m).where(m.organization_id == organization_id).order_by(m.sort_order, m.name)))

    def project_rows(self, db: Session, project_id: uuid.UUID) -> list:
        """The rows a project owns, in picker order."""
        m = self.model
        return list(db.scalars(select(m).where(m.project_id == project_id).order_by(m.sort_order, m.name)))

    def has_own_configuration(self, db: Session, project_id: uuid.UUID) -> bool:
        """Whether the project configures its list: it owns a row or has hidden a default."""
        m = self.model
        if db.scalar(select(m.id).where(m.project_id == project_id).limit(1)) is not None:
            return True
        return bool(definition_suppression.get_suppressed_ids(db, project_id, self.kind))

    def configuration_source(self, db: Session, project_id: uuid.UUID) -> uuid.UUID:
        """The project whose configuration `project_id` shows: itself, or when it has none of its own, its
        nearest ancestor that has some, else itself (the organisation's list). Cycle-safe and capped."""
        if self.has_own_configuration(db, project_id):
            return project_id
        visited = {project_id}
        current = db.scalar(select(Project.parent_project_id).where(Project.id == project_id))
        for _ in range(_ANCESTOR_CAP):
            if current is None or current in visited:
                break
            if self.has_own_configuration(db, current):
                return current
            visited.add(current)
            current = db.scalar(select(Project.parent_project_id).where(Project.id == current))
        return project_id

    def resolve_effective(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> ResolvedVocabulary:
        """A project's effective list: the organisation's rows not hidden in the configuration source, then that
        source's own rows, each group in its own order."""
        source = self.configuration_source(db, project_id)
        hidden = definition_suppression.get_suppressed_ids(db, source, self.kind)
        rows = [r for r in self.org_rows(db, organization_id) if r.id not in hidden] + self.project_rows(db, source)
        return ResolvedVocabulary(rows=rows, source_project_id=source)

    def usable_row(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_id: uuid.UUID):
        """The row a record in `project_id` may be typed as.

        Raises:
            ValueError: If the id is not in the project's effective list.
        """
        row = next((r for r in self.resolve_effective(db, project_id, organization_id).rows if r.id == type_id), None)
        if row is None:
            raise ValueError(f"This is not a valid {self.label.lower()} for this project.")
        return row

    # --- Writing ---------------------------------------------------------

    @abstractmethod
    def seed_defaults(self, db: Session, organization_id: uuid.UUID) -> None:
        """Adds the default rows to a new organisation. The caller owns the transaction."""

    def _check_name(self, db: Session, *, project_id: uuid.UUID | None, organization_id: uuid.UUID, name: str,
                    exclude_id: uuid.UUID | None = None) -> None:
        """Rejects a name another visible row already uses, ignoring case.

        Raises:
            ValueError: On a clash within the owner (organisation) or among the rows the project can see.
        """
        if project_id is None:
            taken = self.org_rows(db, organization_id)
        else:
            taken = self.resolve_effective(db, project_id, organization_id).rows
        wanted = name.strip().lower()
        if any(r.name.lower() == wanted and r.id != exclude_id for r in taken):
            raise ValueError(f"A {self.label.lower()} named {name!r} already exists.")

    def create(self, db: Session, *, project_id: uuid.UUID | None, organization_id: uuid.UUID, **fields):
        """Creates a row at the end of its owner's order. Pass `project_id` for a project row, `None` for an
        organisation default.

        Raises:
            ValueError: If the name clashes with a row the owner can see.
        """
        name = fields["name"].strip()
        self._check_name(db, project_id=project_id, organization_id=organization_id, name=name)
        m = self.model
        owner_filter = m.project_id == project_id if project_id is not None else m.organization_id == organization_id
        count = len(db.scalars(select(m.id).where(owner_filter)).all())
        row = m(
            project_id=project_id, organization_id=None if project_id is not None else organization_id,
            sort_order=count, **{**fields, "name": name},
        )
        db.add(row)
        db.flush()
        return row

    def update(self, db: Session, row, organization_id: uuid.UUID, **fields) -> None:
        """Applies the given fields (`None` values are skipped).

        Raises:
            ValueError: If a new name clashes with a row the owner can see.
        """
        if fields.get("name") is not None:
            fields["name"] = fields["name"].strip()
            self._check_name(
                db, project_id=row.project_id, organization_id=organization_id, name=fields["name"], exclude_id=row.id,
            )
        for key, value in fields.items():
            if value is not None:
                setattr(row, key, value)
        db.flush()

    def in_use(self, db: Session, row_id: uuid.UUID) -> bool:
        """Whether any record references the row."""
        return any(check(db, row_id) for check in self.usage_checks)

    def delete_org_row(self, db: Session, row) -> None:
        """Deletes an organisation default and every project's tombstone for it.

        Raises:
            ValueError: If a record uses it.
        """
        if self.in_use(db, row.id):
            raise ValueError(f"This {self.label.lower()} is in use and cannot be deleted.")
        definition_suppression.forget_definition(db, self.kind, row.id)
        db.delete(row)
        db.flush()

    def delete_project_row(self, db: Session, row) -> None:
        """Deletes a project's own row.

        Raises:
            ValueError: If a record uses it.
        """
        if self.in_use(db, row.id):
            raise ValueError(f"This {self.label.lower()} is in use and cannot be deleted.")
        db.delete(row)
        db.flush()

    # --- Nested projects -------------------------------------------------

    def materialize_inherited(self, db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
        """Before a project changes an inherited list, copies the source's own rows and hidden defaults into it.
        Does nothing when the project is not inheriting.

        Returns:
            `{the source's row id: the project's copy}`, for translating an id taken from the inherited list.
        """
        source = self.configuration_source(db, project_id)
        if source == project_id:
            return {}
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        for row in self.project_rows(db, source):
            copy = self.model(
                project_id=project_id, **{c: getattr(row, c) for c in self.copied_columns()},
            )
            db.add(copy)
            db.flush()
            mapping[row.id] = copy.id
        for org_row_id in definition_suppression.get_suppressed_ids(db, source, self.kind):
            definition_suppression.hide_definition(db, project_id, self.kind, org_row_id)
        return mapping

    def copied_columns(self) -> tuple[str, ...]:
        """The columns a copied project row carries (everything except identity, owner and timestamps)."""
        skip = {"id", "project_id", "organization_id", "created_at", "updated_at"}
        return tuple(c.key for c in self.model.__table__.columns if c.key not in skip)

    # --- Hide and restore (the shared endpoint bodies call these) --------

    def remove_type(
        self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID,
    ) -> tuple[str, uuid.UUID]:
        """What delete means in a project: its own row is deleted, an organisation default is hidden.

        Returns:
            `("deleted", row id)` or `("hidden", organisation row id)`.

        Raises:
            LookupError: If the id is no row of this project's effective list.
            ValueError: If the project's own row is in use.
        """
        effective = self.resolve_effective(db, project_id, organization_id)
        row = next((r for r in effective.rows if r.id == type_ref_id), None)
        if row is None:
            raise LookupError(f"This is not a {self.label.lower()} of this project.")
        mapping = self.materialize_inherited(db, project_id)
        if row.organization_id is not None:
            definition_suppression.hide_definition(db, project_id, self.kind, row.id)
            return "hidden", row.id
        own_id = mapping.get(row.id, row.id)
        own = db.get(self.model, own_id)
        self.delete_project_row(db, own)
        return "deleted", own_id

    def list_hidden(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> list:
        """The organisation rows hidden in the project's configuration source."""
        hidden = definition_suppression.get_suppressed_ids(db, self.configuration_source(db, project_id), self.kind)
        if not hidden:
            return []
        return [r for r in self.org_rows(db, organization_id) if r.id in hidden]

    def restore_hidden(
        self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, org_type_ids: set[uuid.UUID] | None = None,
    ) -> list:
        """Shows hidden organisation rows again: all, or only `org_type_ids`. Returns the restored rows."""
        self.materialize_inherited(db, project_id)
        hidden = self.list_hidden(db, project_id, organization_id)
        wanted = {r.id for r in hidden}
        if org_type_ids is not None:
            wanted &= org_type_ids
        restored = definition_suppression.restore_definitions(db, project_id, self.kind, wanted)
        return [r for r in hidden if r.id in restored]

    def hide_by_names(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, names: list[str]) -> list[str]:
        """Hides the organisation rows called `names` (a project bundle import).

        Returns:
            The names the organisation has no row for.
        """
        by_name = {r.name: r for r in self.org_rows(db, organization_id)}
        missing: list[str] = []
        for name in names:
            row = by_name.get(name)
            if row is None:
                missing.append(name)
            else:
                definition_suppression.hide_definition(db, project_id, self.kind, row.id)
        return missing

    def own_row(self, db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_id: uuid.UUID):
        """The project's own row for an edit, copying an inherited configuration into the project first.

        Raises:
            LookupError: If the id is not a row this project owns (or inherits).
        """
        effective = self.resolve_effective(db, project_id, organization_id)
        row = next((r for r in effective.rows if r.id == type_id and r.project_id is not None), None)
        if row is None:
            raise LookupError(f"{self.label} not found.")
        mapping = self.materialize_inherited(db, project_id)
        return db.get(self.model, mapping.get(row.id, row.id))


class ElementTypeVocabulary(ArchitectureVocabulary):
    """The element type vocabulary."""

    def seed_defaults(self, db: Session, organization_id: uuid.UUID) -> None:
        """Adds the default element types to a new organisation. The caller owns the transaction."""
        for i, (name, shape, domain) in enumerate(DEFAULT_ELEMENT_TYPES):
            light, dark = DOMAIN_COLORS[domain]
            db.add(ArchitectureElementType(
                organization_id=organization_id, name=name, shape=shape, domain=domain,
                color_light=light, color_dark=dark, sort_order=i,
            ))


class ConnectionTypeVocabulary(ArchitectureVocabulary):
    """The connection type vocabulary."""

    def seed_defaults(self, db: Session, organization_id: uuid.UUID) -> None:
        """Adds the default connection types to a new organisation. The caller owns the transaction."""
        for i, (name, domain, directional) in enumerate(DEFAULT_CONNECTION_TYPES):
            light, dark = DOMAIN_COLORS[domain]
            db.add(ArchitectureConnectionType(
                organization_id=organization_id, name=name, domain=domain, directional=directional,
                line_style=LineStyle.SOLID.value, color_light=light, color_dark=dark, sort_order=i,
            ))


ELEMENT_TYPES = ElementTypeVocabulary(kind=ELEMENT_TYPE_KIND, label="Element type", model=ArchitectureElementType)
CONNECTION_TYPES = ConnectionTypeVocabulary(
    kind=CONNECTION_TYPE_KIND, label="Connection type", model=ArchitectureConnectionType,
)


def seed_org_defaults(db: Session, organization_id: uuid.UUID) -> None:
    """`ModuleDefinition.on_org_created`: gives a new organisation the default element and connection types."""
    ELEMENT_TYPES.seed_defaults(db, organization_id)
    CONNECTION_TYPES.seed_defaults(db, organization_id)
