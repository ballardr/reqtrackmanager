"""
Module: models.org_dashboard

Organisation dashboards: the named pages of widgets an organisation shows on its overview.

Responsibilities:
- `OrganizationDashboard`: one page, with its position, its widget layout (the same `{scope, widgets}` object a
  project overview stores) and whether it is the built-in first page.
- `OrganizationDashboardViewer`: one user or group a restricted page is limited to; a page with no viewer rows is
  shown to every member of the organisation.

Design decisions:
- The viewers are rows, not a JSON list, so a deleted group is found by the shared principal machinery
  (`services.principals`) instead of leaving a dangling id in a column. The reference is mandatory, so deleting a
  group that restricts a page needs a replacement and never silently widens who may see the page.
- A page is an organisation-scoped table with no project analogue, so there is no nested-project fallback.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column

#: Longest dashboard name.
MAX_DASHBOARD_NAME_LENGTH = 100


class OrganizationDashboard(UUIDPKMixin, TimestampMixin, Base):
    """One dashboard page of an organisation.

    Attributes:
        organization_id: The owning organisation.
        name: Unique within the organisation.
        position: Order of the pages (lowest first); the built-in page is kept first by the service.
        is_default: True for the built-in "Overview" page, which cannot be deleted or renamed.
        layout: The cleaned layout `{scope, widgets}` (`services.overview_widgets`).
    """

    __tablename__ = "organization_dashboards"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_organization_dashboards_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(MAX_DASHBOARD_NAME_LENGTH))
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OrganizationDashboardViewer(UUIDPKMixin, Base):
    """A user or group a restricted dashboard is limited to (`viewer_type` is a `PrincipalType`)."""

    __tablename__ = "organization_dashboard_viewers"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "viewer_type", "viewer_id", name="uq_organization_dashboard_viewers"),
        principal_check_constraint("viewer"),
    )

    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_dashboards.id", ondelete="CASCADE"), index=True,
    )
    viewer_type: Mapped[str] = principal_type_column()
    viewer_id: Mapped[uuid.UUID] = principal_id_column()
