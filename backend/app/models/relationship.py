"""
Module: models.relationship

The generic, polymorphic cross-artefact relationship table that every content module builds its
artefact-to-artefact links on, instead of a per-pair join table.

Design decision (**Decided by: User**, docs/decisions.md's Platform Foundations entry): one polymorphic
table (`source_type`/`source_id`/`target_type`/`target_id`/`link_type_id`) rather than one per artefact-type
pair. `source_id`/`target_id` carry no foreign key because a polymorphic id cannot reference one table
(as `ReviewComment.target_id`, see `models.enums.ReviewTargetType`). Cleaning up orphaned rows when an
artefact's table is fully removed is an application-level responsibility.

`link_type_id` is nullable with two meanings:
- Non-null: an org-defined, typed traceability link; it points at a `RequirementLinkTypeDefinition`.
- Null: an untyped structural link (many-to-many membership, such as an action's requirements).

Links are not gated by an artefact's lock state by default (see `routers.requirements.create_link` for the
opt-in exception): traceability metadata is not requirement content under C-G-12, as a `ReviewComment` is
not.

Duplicate prevention: Postgres treats multiple `NULL`s in a UNIQUE constraint as distinct, so one
5-column constraint including nullable `link_type_id` would not prevent duplicate untyped links. The
table has two constraints instead (see `__table_args__`).

The module performs no authorisation or tenant-scoping checks; that stays in the routers (see
`services.relationships`).

`source_type`/`target_type` are plain validated strings, not an `ArtefactType` enum column, which would need
a core edit per module; modules register values through `ModuleDefinition.artefact_types` and
`get_all_registered_artefact_types` (`app.modules.registry`; see `app.models.enums.ArtefactType`).
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
    """A relationship between two artefacts of any registered artefact type: typed requirement-to-requirement
    traceability, or untyped membership such as action-to-requirement.

    Attributes:
        source_type / source_id: The link's origin artefact. No FK on `source_id` (see the module docstring).
            `source_type` is a plain string validated in `app.services.relationships.create_link`.
        target_type / target_id: The destination artefact; the same no-FK caveat and plain-string type.
        link_type_id: Null for an untyped structural link; non-null for a typed traceability link, pointing
            at a `RequirementLinkTypeDefinition` (see the module docstring).
        source_project_id / target_project_id: Set (both) only for a link between a project and one of its
            ancestors or descendants, naming each end's project; `NULL` for a same-project link. This keeps
            cross-level links out of readers that assume both ends share a project:
            `services.relationships` excludes rows where these are set unless asked
            (`include_cross_project`), so no reader shows an ancestor's artefact to someone who cannot open it.
        created_by: The user who created the link.
        note: Optional short provenance text (a carried-over link says where it was copied from).
    """

    __tablename__ = "artefact_links"
    # Every constraint and index is named explicitly: generated names for wide multi-column constraints can
    # exceed Postgres's 63-byte NAMEDATALEN limit (see `RequirementLinkTypeDefinition.__table_args__`).
    __table_args__ = (
        # Typed case: a 5-column uniqueness rule.
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "link_type_id",
            name="uq_artefact_links_typed",
        ),
        # Untyped case: the constraint above does not prevent duplicate untyped links (NULLs are distinct;
        # see the module docstring), so this partial unique index does.
        Index(
            "ux_artefact_links_untyped", "source_type", "source_id", "target_type", "target_id",
            unique=True, postgresql_where=sa_text("link_type_id IS NULL"),
        ),
        # Reverse lookup ("what links to X"); the constraints above serve forward lookups through
        # source_type/source_id.
        Index("ix_artefact_links_target", "target_type", "target_id"),
        Index("ix_artefact_links_source_project", "source_project_id", postgresql_where=sa_text("source_project_id IS NOT NULL")),
        Index("ix_artefact_links_target_project", "target_project_id", postgresql_where=sa_text("target_project_id IS NOT NULL")),
    )

    # Plain strings, not `str_enum(ArtefactType, ...)`: a closed enum cannot represent every module's
    # registered artefact types. Validated in `app.services.relationships.create_link`; 40 characters fit
    # the longest registered value.
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
    # Why the link exists when it was not authored directly ("Copied from REQ-001" on a link a requirement
    # carried over when made independent). Plain text, shown beside the link, never a Restricted value.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
