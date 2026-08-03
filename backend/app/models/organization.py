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

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.encrypted_type import EncryptedString
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
            `smtp_password` is encrypted at rest at the application layer
            (`EncryptedString`, SOC 2 hardening pass) — same treatment as
            `oidc_client_secret`, since it's a genuine credential even
            though the feature it belongs to isn't wired in yet.
        sso_group_mappings: Mapping of external SSO/OIDC claim values to a
            local `OrgRole`, e.g. `[{"claim_value": "reqtrack-admins",
            "org_role": "org_admin"}]` (C-U-07, E-U-01). Was storage-only
            until Massif (v3)'s `OIDCAuthBackend`
            (`app/services/oidc_provisioning.py`) started actually reading
            it to provision org roles on first SSO login.
        slug: URL-safe identifier used to resolve this organisation's
            branded login page at `/login/{slug}` (E-P-03).
        sso_enabled / sso_only: Whether this organisation's login page offers
            an OIDC "Sign in with SSO" button, and whether the native
            email/password form is hidden entirely when it does.
        oidc_issuer_url / oidc_client_id / oidc_client_secret: Per-org OIDC
            provider configuration. `oidc_client_secret` is encrypted at
            rest at the application layer (`EncryptedString`, SOC 2
            hardening pass) — previously plaintext, see
            docs/enterprise-integration.md's history of that follow-up.
        login_background_file_id: Optional uploaded background image for
            this organisation's login page (E-P-03), same upload pattern as
            `logo_file_id`.
        oidc_required_group: Optional access gate, distinct from
            `sso_group_mappings`. When set, a successfully-authenticated SSO
            user whose IdP `groups`/`roles` claim doesn't contain this exact
            value is refused a session entirely (`oidc_provisioning.
            meets_required_group`) — "in the org" and "let in at all" are
            deliberately separate checks, so an admin can gate access to a
            specific provisioning group without that group needing to also
            be one of the role-granting entries in `sso_group_mappings`.
        pat_max_lifetime_days: Optional cap, set by this org's own admin, on
            how long a Personal Access Token scoped to this org may live.
            `None` means "use the deployment-wide default"
            (`settings.pat_default_max_lifetime_days`). Enforced dynamically
            at PAT auth time, not just at creation — see
            `models.pat.PersonalAccessToken`'s docstring.
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
    smtp_password: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    sso_group_mappings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    sso_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sso_only: Mapped[bool] = mapped_column(Boolean, default=False)
    oidc_issuer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret: Mapped[str | None] = mapped_column(EncryptedString(1000), nullable=True)
    oidc_required_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    login_background_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_organizations_login_background_file_id"),
        nullable=True,
    )
    pat_max_lifetime_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ReportTemplate(UUIDPKMixin, TimestampMixin, Base):
    """A named, reusable PDF report branding preset for an organisation (R-G-05).

    Org-scoped (shared across the org's projects) to match how the org logo
    already works. Selected optionally at report-generation time; when none
    is selected, `services/reports.py` produces today's plain, unbranded
    output.
    """

    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(255))
    accent_color_hex: Mapped[str] = mapped_column(String(7), default="#2563eb")
    include_cover_page: Mapped[bool] = mapped_column(Boolean, default=True)
    include_logo: Mapped[bool] = mapped_column(Boolean, default=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


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
