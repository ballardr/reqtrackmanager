"""
Module: models.requirement_link_type

Org-definable, bidirectional traceability relationship types between
requirements (C-G-09), replacing the previous fixed `RequirementLinkType`
enum (relates_to/depends_on/derived_from). An organisation gets 12 seeded
defaults (forward/reverse pairs — e.g. "Derives from" / "Is the source of")
covering the common traceability vocabulary, and may add its own beyond
that with no artificial cap, matching how this codebase already treats
seeded `ProjectGroup`s and default report templates as ordinary, renamable/
deletable rows rather than protected "builtin" ones.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class RequirementLinkTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Org-definable, bidirectional relationship type between requirements.

    Stores both directional display names so a link renders correctly from
    either the source or target requirement's page without a naming-
    convention guess: a link created with this definition reads as
    `forward_name` from its source requirement's side (e.g. "Derives from")
    and `reverse_name` from its target's side (e.g. "Is the source of").
    A symmetric relationship (e.g. "Related to") simply has the same value
    in both columns.

    Attributes:
        organization_id: The owning organisation — link types are org-
            scoped so every project in an organisation shares one
            vocabulary, matching `ProjectStatusDefinition`.
        forward_name: Display name for the link when read from its source
            requirement.
        reverse_name: Display name for the link when read from its target
            requirement.
        sort_order: Display/picker order among the organisation's link types.
    """

    __tablename__ = "requirement_link_type_definitions"
    # Explicit short name: the SQLAlchemy/Postgres default-generated name for
    # this constraint ("requirement_link_type_definitions_organization_id_
    # forward_name_key") is 66 bytes, over Postgres's 63-byte NAMEDATALEN
    # limit — Postgres would silently truncate it, making the truncated name
    # unpredictable to reproduce exactly in migration 0012's legacy-database
    # path. An explicit name sidesteps that ambiguity entirely (same
    # technique this codebase already uses in migration 0009 for exactly
    # this class of problem).
    __table_args__ = (
        UniqueConstraint("organization_id", "forward_name", name="uq_requirement_link_type_definitions_org_forward"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    forward_name: Mapped[str] = mapped_column(String(100))
    reverse_name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
