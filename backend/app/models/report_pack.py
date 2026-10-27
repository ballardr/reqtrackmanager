"""
Module: models.report_pack

Report packs: a named configuration that lists several reports (custom layouts and module reports), each
with its own output format, and is run with one set of variables into a zip with a manifest
(`services.report_pack_run`).

Responsibilities:
- `ReportPack`: the named, owned definition (organisation- or project-level) and a pointer to its latest version.
- `ReportPackVersion`: one immutable saved definition. Editing a pack appends a version; a run pins one.

Design decisions:
- A pack is configuration, not an artefact type: no `PREFIX-nnn` code, not linkable, not searched (as a layout).
- `project_id IS NULL` is an organisation-level pack. Both ids are real foreign keys with `ON DELETE CASCADE`,
  so deleting the owner removes its packs and versions with no cleanup code.
- The definition (variables and entries, `schema_version` inside) is stored as the author wrote it (JSONB)
  plus a SHA-256 of its canonical JSON. A version row is never updated; an ORM-level guard refuses it so a
  later change cannot rewrite history that a provenance row points at.
- Entries name their layout by name and tier, never by id, so a definition is portable in a bundle and
  resolves for the project it runs in.
- Name uniqueness is per owner (two partial unique indexes, as for layouts).
- Saved variable sets belong to a pack, not to a version, so a new version keeps the people's saved choices; a value
  naming a variable the new version no longer declares is ignored at run with a warning. A pack-defined set can be
  overridden per project (`ReportPackSetOverride`, per variable) and a project can add sets of its own beside it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, utcnow


class ReportPack(UUIDPKMixin, TimestampMixin, Base):
    """A named report pack owned by an organisation or one of its projects.

    Attributes:
        organization_id: Owning organisation (always set).
        project_id: The owning project, or `None` for an organisation-level pack.
        name: Display name, unique within the owner (case-insensitively, checked by the service).
        description: What the pack is for (for example who receives it).
        current_version: The latest `ReportPackVersion.version`.
        created_by: The author, `None` once that user is deleted.
    """

    __tablename__ = "report_packs"
    __table_args__ = (
        Index(
            "uq_report_packs_org_name", "organization_id", "name", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_packs_project_name", "project_id", "name", unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReportPackVersion(UUIDPKMixin, Base):
    """One immutable saved version of a pack.

    Attributes:
        pack_id: The pack.
        version: 1, 2, 3 ... within the pack.
        schema_version: The definition vocabulary version it was written in.
        definition: The pack definition (`services.report_pack_definition`): `variables` and `entries`.
        definition_hash: SHA-256 hex of the canonical JSON of `definition`.
        comment: The author's note on this change.
        created_by: The author, `None` once that user is deleted.
        created_at: When saved (UTC).
    """

    __tablename__ = "report_pack_versions"
    __table_args__ = (UniqueConstraint("pack_id", "version", name="uq_report_pack_versions_pack_version"),)

    pack_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_packs.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    definition_hash: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportPackVariableSet(UUIDPKMixin, TimestampMixin, Base):
    """A named set of values for a pack's variables, so a repeat download for the same audience is one click.

    Attributes:
        pack_id: The pack (any tier).
        project_id: `None` for a set defined with the pack by its owner; a project's id for a set that project added
            beside the pack's own (visible to that project and its descendants).
        name: Display name, unique within `(pack_id, project_id)` (case-insensitively, checked by the service).
        variable_values: `{variable name: value}` for some or all of the pack's variables (a variable left out takes its default).
        created_by: The author, `None` once that user is deleted.
    """

    __tablename__ = "report_pack_variable_sets"
    __table_args__ = (
        Index(
            "uq_report_pack_sets_pack_name", "pack_id", "name", unique=True, postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_pack_sets_project_name", "pack_id", "project_id", "name", unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    pack_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_packs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    variable_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReportPackSetOverride(UUIDPKMixin, TimestampMixin, Base):
    """One project's values layered over a pack-defined set (per variable; a variable not listed falls back).

    Attributes:
        set_id: The pack-defined set overridden.
        project_id: The project whose runs (and its descendants' that have no nearer override) see these values.
        variable_values: `{variable name: value}` for the variables this project changes.
    """

    __tablename__ = "report_pack_set_overrides"
    __table_args__ = (UniqueConstraint("set_id", "project_id", name="uq_report_pack_set_overrides_set_project"),)

    set_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_pack_variable_sets.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    variable_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


@event.listens_for(ReportPackVersion, "before_update")
def _refuse_version_update(mapper: Any, connection: Any, target: ReportPackVersion) -> None:
    """Refuses to update a saved version: history that a run's provenance points at must not change."""
    raise ValueError("A report pack version is immutable; save a new version instead.")
