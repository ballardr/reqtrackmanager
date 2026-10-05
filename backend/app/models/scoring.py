"""
Module: models.scoring

Generic, module-agnostic storage for configurable scoring matrices
(Module 1 — Context & Strategy — Phase 10). A module registers a scoring
*scheme* (axes, models, default bands) via `ModuleDefinition.
scoring_schemes`; these tables hold each organisation's/project's data for
it, keyed by the scheme's/axis's/model's plain string keys and validated
against the registry (`app.modules.registry.get_all_registered_scoring_
schemes`) at the service layer — the `ArtefactLink.source_type` pattern,
never a closed core enum a module would need a value added to.

- `ScoringLevel` — an org's ordered, weighted levels for one axis. Org-only
  (no project tier): module rows reference a level by id, so levels must be
  one shared vocabulary per org. Seeded from registry defaults.
- `ScoringModelDefault` — the default model for a scheme: one org row
  (`project_id IS NULL`) and/or per-project override rows.
- `ScoringBand` — rating bands for one (scheme, model): an org set
  (`project_id IS NULL`) and/or per-project override sets. A set is
  all-or-nothing; no rows means "inherit".

Resolution (project → nearest ancestor → org → registry default) lives in
`app.services.scoring`, following `resolve_effective_action_types`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ScoringLevel(UUIDPKMixin, TimestampMixin, Base):
    """One named, weighted level of a scoring axis in an organisation.

    Attributes:
        organization_id: The owning organisation.
        scheme_key: Registered scoring scheme key (e.g. "pain_point").
        axis_key: Registered axis key within the scheme (e.g. "severity").
        name: Display name, unique within (org, scheme, axis).
        description: Optional scorer guidance.
        weight: Positive weight, unique within (org, scheme, axis); levels
            are ordered by weight, so the highest is the axis's top level.
    """

    __tablename__ = "scoring_levels"
    __table_args__ = (
        UniqueConstraint("organization_id", "scheme_key", "axis_key", "name", name="uq_scoring_levels_name"),
        UniqueConstraint("organization_id", "scheme_key", "axis_key", "weight", name="uq_scoring_levels_weight"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scheme_key: Mapped[str] = mapped_column(String(64))
    axis_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class ScoringModelDefault(UUIDPKMixin, TimestampMixin, Base):
    """The default scoring model for a scheme at org level (`project_id`
    NULL) or as a project override.

    Attributes:
        organization_id: The owning organisation.
        project_id: The overriding project, or `None` for the org default.
        scheme_key: Registered scoring scheme key.
        model_key: Registered model key within the scheme.
    """

    __tablename__ = "scoring_model_defaults"
    __table_args__ = (
        Index(
            "uq_scoring_model_defaults_org", "organization_id", "scheme_key",
            unique=True, postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_scoring_model_defaults_project", "project_id", "scheme_key",
            unique=True, postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    scheme_key: Mapped[str] = mapped_column(String(64))
    model_key: Mapped[str] = mapped_column(String(64))


class ScoringBand(UUIDPKMixin, TimestampMixin, Base):
    """One rating band of an org-level (`project_id` NULL) or project-level
    band set for a (scheme, model).

    Attributes:
        organization_id: The owning organisation.
        project_id: The overriding project, or `None` for the org set.
        scheme_key: Registered scoring scheme key.
        model_key: Registered model key within the scheme.
        label: Display label.
        min_score: Normalised lower bound in [0, 1) (score ÷ max score).
        tone: One of `app.modules.registry.SCORING_BAND_TONES`.
        sort_order: Position within the set (ascending thresholds).
    """

    __tablename__ = "scoring_bands"
    __table_args__ = (
        Index("ix_scoring_bands_scope", "organization_id", "project_id", "scheme_key", "model_key"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    scheme_key: Mapped[str] = mapped_column(String(64))
    model_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(100))
    min_score: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    tone: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
