"""
Module: models.project_status

Org-definable project statuses. Every project carries exactly one status
(`Project.status_id`), and the set of selectable statuses is defined per
organisation (not hard-coded), seeded with four defaults (Proposed, Active,
Abandoned, Completed) at organisation creation and backfilled onto every
pre-existing organisation by migration 0012.

Design decision: `Project.status_id` has no `ondelete` action (implicit
RESTRICT) even though it's a NOT NULL column with an app-layer 409 check
already preventing deletion of an in-use status (see the shared
rename/delete/reassign rules in `routers/orgs.py`'s project-statuses
section). The app-layer check and the DB-level RESTRICT are deliberately
redundant: silently orphaning a NOT NULL FK (which `ON DELETE SET NULL`
can't even do here) would corrupt data far worse than a delete simply
failing, so the second backstop is cheap insurance against any future
code path that forgets the app-layer check.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ProjectStatusDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined project status (e.g. "Proposed", "Active").

    Attributes:
        organization_id: The owning organisation — statuses are org-scoped,
            not project-scoped, so every project in an organisation picks
            from the same shared list.
        name: Display name, unique within the organisation.
        sort_order: Display/picker order among the organisation's statuses.
    """

    __tablename__ = "project_status_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
