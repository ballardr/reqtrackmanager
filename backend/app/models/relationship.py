"""
Module: models.relationship

The generic, polymorphic
cross-artefact relationship table every content module in the future-
modules roadmap builds its own artefact-to-artefact links on top of,
instead of each module inventing its own per-pair join table the way
`RequirementLink` (requirement-to-requirement traceability) and
`RequirementActionLink` (action-to-requirement membership) used to.

Design decision (Decided by: User, docs/decisions.md's Platform Foundations entry): a single polymorphic table
(`source_type`/`source_id`/`target_type`/`target_id`/`link_type_id`)
rather than a dedicated table per artefact-type pair. `source_id`/
`target_id` deliberately carry no foreign key — a polymorphic id can't
reference a single table when the type it points at varies per row — this
mirrors the same, already-established precedent `ReviewTargetType`/
`ReviewComment.target_id` uses for exactly the same reason (see
`models.enums.ReviewTargetType`). The accepted cost: cleaning up orphaned
`ArtefactLink` rows if an artefact's own table is ever fully removed (not
just disabled via the module registry) is an application-level
responsibility, not something the database enforces the way a real FK
would.

`link_type_id` is nullable and carries two distinct meanings depending on
whether it's set:

- **Non-null**: an org-defined, typed traceability link (what
  `RequirementLink` used to be) — `link_type_id` points at a
  `RequirementLinkTypeDefinition` row (reused as-is; not extended with a
  type-pair constraint — YAGNI).
- **Null**: an untyped, structural link (what `RequirementActionLink` used
  to be — it never had a type, just membership in a many-to-many set).

Both meanings share one table rather than two so every future module gets
one relationship surface regardless of which shape its own links need.

Links are not gated by an artefact's own lock state by default (see
`routers.requirements.create_link`'s docstring for the opt-in exception
a later opt-in introduced) — traceability metadata isn't
"requirement content" under C-G-12 any more than a `ReviewComment` is
(carried over unchanged from `RequirementLink`'s own original docstring,
which this model replaces).

**Correctness note on duplicate prevention**: Postgres treats multiple
`NULL`s in a UNIQUE constraint as distinct from one another (not equal), so
a single 5-column unique constraint including nullable `link_type_id` would
NOT prevent duplicate *untyped* links the way `RequirementActionLink`'s old
`UniqueConstraint("requirement_id", "action_id")` did. This table therefore
has two separate constraints instead of one — see `__table_args__` below.

This module intentionally does not perform authorization/tenant-scoping
checks anywhere — see `services.relationships`' own module docstring for
why that responsibility stays at the router layer.

`source_type`/`target_type` are plain, validated strings, not a closed
`ArtefactType` enum column: an enum would need a core file hand-edited per
module that introduces an artefact type — see `app.models.enums.
ArtefactType`'s own docstring and `app.modules.registry.ModuleDefinition.
artefact_types`/`get_all_registered_artefact_types` for the registration
mechanism that replaced it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.requirement_link_type import RequirementLinkTypeDefinition  # noqa: F401  (FK target, for clarity)


class ArtefactLink(UUIDPKMixin, TimestampMixin, Base):
    """A relationship between two artefacts of any registered artefact
    type, replacing both the old `RequirementLink` (requirement-to-
    requirement traceability) and `RequirementActionLink`
    (action-to-requirement membership) tables, which this table
    replaces.

    Attributes:
        source_type / source_id: The link's origin artefact. No FK on
            `source_id` — see this module's docstring for why. `source_type`
            is a plain string (not a closed `ArtefactType` enum, as of
            Platform Foundations) — see `app.services.relationships.
            create_link`'s docstring for where it's validated.
        target_type / target_id: The link's destination artefact. Same
            no-FK caveat and plain-string type as `source_id`/`source_type`.
        link_type_id: Null for an untyped/structural link (e.g. what
            `RequirementActionLink` used to represent); non-null for a
            typed traceability link, pointing at a
            `RequirementLinkTypeDefinition` row (what `RequirementLink`
            used to represent). See this module's docstring for the full
            reasoning.
        source_project_id / target_project_id: Set (both) only for a link
            between a project and one of its ancestors or descendants, naming
            the project each end belongs to; `NULL` for the ordinary
            same-project link. This is what keeps cross-level links out of
            every reader that assumes both ends share a project:
            `services.relationships` excludes rows where these are set unless
            asked (`include_cross_project`), so a legacy reader can never show an
            ancestor's artefact to someone who cannot open it.
        created_by: The user who created the link.
    """

    __tablename__ = "artefact_links"
    # Explicit short names throughout: this codebase has hit Postgres's
    # 63-byte NAMEDATALEN limit before on wide, auto-generated constraint
    # names for multi-column constraints on this exact kind of table (see
    # migration 0009's own comment and
    # `RequirementLinkTypeDefinition.__table_args__`'s docstring for the
    # established fix/precedent) — every constraint/index below is named
    # explicitly rather than left to SQLAlchemy's default naming.
    __table_args__ = (
        # Non-null case: an ordinary 5-column uniqueness rule, mirroring
        # old `RequirementLink`'s own 3-column constraint extended with the
        # two new type columns.
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "link_type_id",
            name="uq_artefact_links_typed",
        ),
        # Null case: Postgres's NULL-distinctness means the constraint above
        # does NOT prevent duplicate untyped links (see module docstring) —
        # this partial unique index is what actually replaces
        # `RequirementActionLink`'s old 2-column uniqueness guarantee for
        # links with no type.
        Index(
            "ux_artefact_links_untyped", "source_type", "source_id", "target_type", "target_id",
            unique=True, postgresql_where=sa_text("link_type_id IS NULL"),
        ),
        # Reverse-lookup index ("what links to X") — the two constraints
        # above already give forward lookups ("what does X link to") a
        # usable leading-column index via source_type/source_id.
        Index("ix_artefact_links_target", "target_type", "target_id"),
        Index("ix_artefact_links_source_project", "source_project_id", postgresql_where=sa_text("source_project_id IS NOT NULL")),
        Index("ix_artefact_links_target_project", "target_project_id", postgresql_where=sa_text("target_project_id IS NOT NULL")),
    )

    # Plain strings, not a `str_enum(ArtefactType, ...)` column (unlike
    # every other enum-typed column in this codebase) — deliberately, as
    # of migration 0043: a closed Python `enum.Enum`
    # can't gain members at runtime, so it can't represent every module's
    # own registered artefact types, only the two this app owns outright.
    # Validated at the service layer instead — see `app.services.
    # relationships.create_link`. Widened from 20 to 40 chars at the same
    # time, to fit the longest currently-registered value.
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    link_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_link_type_definitions.id"), nullable=True
    )
    source_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
