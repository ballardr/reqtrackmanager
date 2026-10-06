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

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
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
        project_id: `None` for an organisation-wide type (the default and the
            only kind before project-level link types existed); a project's
            id for a type its project admin defined, usable in that project
            and every descendant. Local types keep `organization_id` set so
            org deletion and the same-organisation checks still cover them.
            Name uniqueness is per scope (see `__table_args__`); the
            cross-scope "ancestor wins" rule is service-level
            (`services.link_type_scope`).
    """

    __tablename__ = "requirement_link_type_definitions"
    # Two partial unique indexes replace the original (organization_id,
    # forward_name) constraint: an org-wide type is unique per organisation,
    # a project-local one per project, so two projects can each own a type
    # with the same name.
    __table_args__ = (
        Index(
            "uq_requirement_link_type_definitions_org_forward", "organization_id", "forward_name",
            unique=True, postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_requirement_link_type_definitions_project_forward", "project_id", "forward_name",
            unique=True, postgresql_where=text("project_id IS NOT NULL"),
        ),
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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )


class ArtefactTypeLinkRule(UUIDPKMixin, TimestampMixin, Base):
    """The closed list of link types an artefact type may use ("a Requirement
    may only be linked with *Derives from* and *Implements*"), the other half
    of the restriction a link type states about the artefact types it joins.

    No rule for an artefact type means any link type; a rule is never empty
    (the API rejects it). `artefact_type` is a plain validated string, as on
    `ArtefactLink`, so a module's types need no core edit. Enforced at link
    creation only (`services.link_types.validate_link_allowed`).

    Attributes:
        organization_id: The owning organisation (always set, project rules
            included).
        project_id: `None` for the organisation's rule; a project's id for a
            project-scope rule. The nearest rule for an artefact type wins
            (project, each ancestor, then the organisation) and replaces the
            farther one entirely (`services.link_type_scope.resolve_artefact_rules`).
        artefact_type: A registered artefact type; unique per scope.
        allowed_link_types: The permitted link types (real FKs, so a deleted
            type cannot dangle; deleting an in-use type substitutes or
            removes it from the rule first).
    """

    __tablename__ = "artefact_type_link_rules"
    __table_args__ = (
        Index(
            "uq_artefact_type_link_rules_org_type", "organization_id", "artefact_type",
            unique=True, postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_artefact_type_link_rules_project_type", "project_id", "artefact_type",
            unique=True, postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
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


class ProjectLinkTypeVisibility(Base):
    """A project's decision to hide (or re-show) a link type it can reach.

    One row per `(project, link type)`. The nearest row up the project chain
    wins, so a parent's hide carries down to its children and a child can show
    the type again with its own `hidden=False` row. Applies to any type visible
    to the project (organisation-wide or an ancestor's local type). Hiding means
    "not offered for new links": existing links of a hidden type keep
    displaying (`services.link_type_scope`).

    Attributes:
        project_id: The project making the choice.
        link_type_id: The link type affected.
        hidden: True to hide it from this project's pickers, False to override
            an ancestor's hide.
    """

    __tablename__ = "project_link_type_visibility"
    __table_args__ = (Index("ix_project_link_type_visibility_link_type", "link_type_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    link_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_link_type_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    hidden: Mapped[bool] = mapped_column(Boolean, default=True)
