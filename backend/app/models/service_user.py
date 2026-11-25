"""
Module: models.service_user

The organisation-level facts of a service user (`User.is_service_account`): which organisation it belongs to, what it
is for, and who is responsible for it.

Responsibilities:
- One row per service user, kept apart from `User` so an ordinary account carries no integration columns and the
  responsible principal is an ordinary principal field (`models.principal`).

Design decisions:
- The organisation is stored, not derived from role rows, because "a service user belongs to one organisation" is a
  rule the rest of the product enforces (`services.org_membership`); a stored value is what it checks.
- The responsible principal is a user or an organisation group (parity); it is optional and a service user without one
  is flagged in the access review rather than refused at creation.

External dependencies: `models.user`, `models.organization`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column


class ServiceUserProfile(UUIDPKMixin, TimestampMixin, Base):
    """The organisation, purpose and responsible principal of one service user.

    Attributes:
        user_id: The service user's account (unique: one profile per account).
        organization_id: The one organisation the service user belongs to.
        description: What the service user is for.
        responsible_type / responsible_id: The user or organisation group answerable for it (optional).
        created_by: The administrator who created it.
    """

    __tablename__ = "service_user_profiles"
    __table_args__ = (principal_check_constraint("responsible", nullable=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(500), default="")
    responsible_type: Mapped[str | None] = principal_type_column(nullable=True)
    responsible_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
