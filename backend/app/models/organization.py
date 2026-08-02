"""
Module: models.organization

Defines organisations, organisation groups, and org-level role assignments.
Organisations are the top-level tenant boundary: every project belongs to an
organisation, and every project user must also be an organisation user
(C-U-02).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import OrgRole


class Organization(UUIDPKMixin, TimestampMixin, Base):
    """A tenant boundary that owns projects, groups, and members.

    Attributes:
        logo_file_id: Optional uploaded logo image (U-C-02). Uses
            `use_alter` since `file_assets` references `organizations`
            (organization_id), which would otherwise form a FK cycle.
        default_template_project_id: The project used as the default
            template when creating a new project in this organisation
            (C-E-04). Uses `use_alter` for the same reason (`projects`
            references `organizations`).
        smtp_*: Per-organisation SMTP override for outgoing notification
            email. Storage-only: like `AuthBackend` (C-U-06/07), this is a
            seam for a future per-org mail relay, not itself wired into
            `services/email.py`, which still sends through the
            deployment-wide SMTP_HOST configured in `config.py`. Documented
            in docs/decisions.md rather than silently half-built.
        sso_group_mappings: Storage-only mapping of external SSO group names
            to a local org role or project group, for a future SSO backend
            (C-U-07, E-U-01) to consume. No SSO backend exists yet (native
            auth only — see `app/auth_backends/`), so nothing currently
            reads this column; it lets an admin prepare the mapping ahead of
            that integration shipping.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    logo_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_organizations_logo_file_id"),
        nullable=True,
    )
    default_template_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", use_alter=True, name="fk_organizations_default_template_project_id"),
        nullable=True,
    )

    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    sso_group_mappings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class UserOrgRole(UUIDPKMixin, TimestampMixin, Base):
    """Grants a user a role within an organisation (C-U-01).

    Attributes:
        user_id: The user being granted the role.
        organization_id: The organisation the role applies to.
        role: One of org_admin, project_creator, member.
    """

    __tablename__ = "user_org_roles"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    role: Mapped[OrgRole] = mapped_column(str_enum(OrgRole))

    user: Mapped[User] = relationship(back_populates="org_roles")  # noqa: F821


class OrgGroup(UUIDPKMixin, TimestampMixin, Base):
    """A named grouping of organisation users (C-U-08 groups requirement).

    Org groups can be nested inside project groups (C-U-12) so that an
    organisational team (e.g. "Development Team") can be granted a project
    role in a single step.
    """

    __tablename__ = "org_groups"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    name: Mapped[str] = mapped_column(String(255))


class OrgGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """Membership of a user in an organisation group."""

    __tablename__ = "org_group_members"
    __table_args__ = (UniqueConstraint("org_group_id", "user_id"),)

    org_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("org_groups.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
