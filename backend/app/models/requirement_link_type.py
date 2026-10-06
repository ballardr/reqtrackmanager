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

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import LinkFlow


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
        flow: Which way the link points in a traceability chain, so the link
            graph can split a node's neighbours into upstream/downstream
            (`models.enums.LinkFlow`); `none` until an admin classifies it.
        allowed_source_types / allowed_target_types: Optional restriction on
            which artefact types a link of this type may run from / to, read
            in the forward direction (`None` = any registered artefact type).
            Plain validated strings (checked against `modules.registry.
            get_all_registered_artefact_types` on write), never a closed
            enum, so a module's artefact types are linkable without a core
            edit. Enforced at link creation only (`services.link_types.
            validate_link_allowed`); editing never invalidates existing links.
        dedicated_endpoint: The type carries a fixed meaning with its own
            action (e.g. "Supersedes" flips a status), so the generic link
            endpoints neither offer nor delete it. Set by seeding, never by
            the admin API.
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
    flow: Mapped[LinkFlow] = mapped_column(str_enum(LinkFlow, 30), default=LinkFlow.NONE, server_default=LinkFlow.NONE.value)
    allowed_source_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    allowed_target_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    dedicated_endpoint: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class ArtefactTypeLinkRule(UUIDPKMixin, TimestampMixin, Base):
    """The closed list of link types an artefact type may use ("a Requirement
    may only be linked with *Derives from* and *Implements*"), the other half
    of the restriction a link type states about the artefact types it joins.

    No rule for an artefact type means any link type; a rule is never empty
    (the API rejects it). `artefact_type` is a plain validated string, as on
    `ArtefactLink`, so a module's types need no core edit. Enforced at link
    creation only (`services.link_types.validate_link_allowed`).

    Attributes:
        organization_id: The owning organisation (rules are org-scoped).
        artefact_type: A registered artefact type; unique per organisation.
        allowed_link_types: The permitted link types (real FKs, so a deleted
            type cannot dangle; deleting an in-use type substitutes or
            removes it from the rule first).
    """

    __tablename__ = "artefact_type_link_rules"
    __table_args__ = (UniqueConstraint("organization_id", "artefact_type", name="uq_artefact_type_link_rules_org_type"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    allowed_link_types: Mapped[list[ArtefactTypeLinkRuleEntry]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class ArtefactTypeLinkRuleEntry(Base):
    """One permitted link type within an `ArtefactTypeLinkRule`."""

    __tablename__ = "artefact_type_link_rule_entries"
    __table_args__ = (Index("ix_artefact_type_link_rule_entries_link_type", "link_type_id"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artefact_type_link_rules.id", ondelete="CASCADE"), primary_key=True
    )
    link_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_link_type_definitions.id"), primary_key=True
    )
