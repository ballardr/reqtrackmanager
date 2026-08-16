"""
Module: models.organization

Defines organisations, organisation groups, and org-level role assignments.
Organisations are the top-level tenant boundary: every project belongs to an
organisation, and every project user must also be an organisation user
(C-U-02).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.encrypted_type import EncryptedString
from app.models.enums import ExternalUserPolicy, OrgRole, ProjectRole, SignupMode


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
        is_active: Whether this organisation's content is currently
            reachable at all (e.g. suspended for non-payment). Reversible,
            unlike deletion: no data is touched, just gated. Deliberately
            stronger than any per-user role — while disabled, even this
            org's own admins are locked out of every org/project-scoped
            request (`services/rbac.py`'s `_require_org_active`), not just
            ordinary members. Only a server admin can toggle it
            (`POST /orgs/{id}/disable` / `/enable`), and toggling doesn't
            itself require org membership (I-M-05's tenancy-management
            carve-out) — a suspended org's own admin, by definition, is
            exactly the caller this needs to work without.
        disabled_at / disabled_by: Set when `is_active` transitions to
            False, mirroring the `Project.archived_at`/`archived_by`
            pattern; cleared on re-enable.
        accent_color_hex: Optional per-org override of the app's UI accent
            colour (nav highlight, primary buttons, links). `None` means
            "use the platform default" (`ServerSettings.accent_color_hex`).
            Applied identically in light and dark theme — one colour, not
            two — with contrast text computed automatically rather than
            also being admin-picked (`services/branding.py::contrast_text`).
        header_title: Optional per-org override of the app-shell wordmark
            text shown next to the logo. `None` falls back to the built-in
            product name. Whether an org's branding (this + `logo_file_id`)
            actually renders on a given page depends on whether that page
            is scoped to this specific org — see
            `frontend/src/hooks/useBranding.ts` for the resolution rules.
        require_2fa: When set, every org/project-scoped request against this
            organisation from a user without `User.is_2fa_enabled` is
            blocked (`services/rbac.py::_require_org_2fa`), mirroring
            `is_active`'s "even this org's own admins" bluntness — with one
            deliberate difference: unlike a disabled org, the way out is
            self-service. `/auth/2fa/enroll`/`confirm` aren't org-scoped, so
            a blocked user can still enroll and immediately regain access,
            without needing an admin to intervene.
        allow_self_signup: Whether this org is one of the organisations a
            public signup under `ServerSettings.signup_mode ==
            ORG_SPECIFIED` can join, via a domain match against
            `auto_accept_email_domain` (`routers/auth.py::signup`).
            Deliberately mutually exclusive with `sso_only` — validated in
            `update_advanced_settings` — since self-signup is anonymous and
            un-gated by an admin, unlike every other native-account-creation
            path (`create_org_user`, an admin-sent invite), so it must never
            be allowed to hand out a native password credential to an org
            whose members are supposed to authenticate via SSO only.
        auto_accept_email_domain: The single email domain (e.g. "acme.com")
            this org auto-accepts. Serves two independent consumers: (1)
            `ORG_SPECIFIED`-mode self-signup above, and (2) the domain check
            for `external_user_policy == ORG_DOMAIN_ONLY` below — one field,
            documented as doing double duty rather than two separate
            near-identical settings.
        external_user_policy: Governs whether/how a project admin may add
            someone to a project by email who isn't already an org member
            (`ExternalUserPolicy`; see its docstring in `models/enums.py`).
            Defaults to DISABLED — an org must opt in to external users.
        email_footer_company_name / email_footer_website /
            email_footer_address: Optional per-org override of the
            outgoing HTML email footer's legal/company identity (name,
            website, postal address). `None` for any of the three falls
            back to that same field on `ServerSettings` independently —
            identical "org overrides, null means use the platform default"
            semantics to `accent_color_hex`/`header_title` above, resolved
            by `services/email_branding.py::resolve_email_branding`.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    require_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_self_signup: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_accept_email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_user_policy: Mapped[ExternalUserPolicy] = mapped_column(
        str_enum(ExternalUserPolicy), default=ExternalUserPolicy.DISABLED
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
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

    accent_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    header_title: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Organisation-level default report content (UI/UX pass): a project
    # falls back to these when its own `report_intro`/`report_chapters`/
    # `report_appendices` (models/project.py) are blank/empty — the same
    # "org sets a default, a narrower scope can override" shape as
    # accent_color_hex/header_title above, just resolved at read time
    # (`services/reports.py::resolve_report_config`) via plain truthiness
    # rather than a nullable column on `Project`, since an empty string/
    # list and "never customised" are treated as the same thing here (no
    # separate way to force "genuinely blank despite an org default" — a
    # deliberate simplification, not an oversight).
    default_report_intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_report_chapters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    default_report_appendices: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    email_footer_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_footer_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_footer_address: Mapped[str | None] = mapped_column(Text, nullable=True)


class ServerSettings(UUIDPKMixin, TimestampMixin, Base):
    """Platform-wide defaults for UI branding, lazily created as a single
    row (`services/branding.py::get_server_settings`) rather than enforced
    by a DB-level singleton constraint — the first read creates it with
    built-in defaults if no row exists yet.

    Falls back to for any org that hasn't set its own `accent_color_hex`/
    `header_title`/logo, and for pages that aren't scoped to a specific
    organisation at all (see `frontend/src/hooks/useBranding.ts`).

    Attributes:
        accent_color_hex: Platform default UI accent colour. Defaults to a
            neutral graphite (#475569) rather than a "branded" blue, per an
            explicit product decision to read as a serious business tool
            rather than draw attention to the chrome.
        default_logo_file_id: Optional platform-wide default logo, shown
            instead of an org's own logo on pages with no resolvable org
            context. Same upload mechanism as `Organization.logo_file_id`.
        default_header_title: Optional platform-wide default wordmark text.
            `None` falls back to the built-in product name, same as an
            org's own `header_title`.
        default_login_background_file_id: Optional platform-wide default
            login-page background image, shown on the plain `/login` page
            (no single org context to brand it) — same upload pattern as
            `Organization.login_background_file_id`, which only applies to
            that org's own branded `/login/{slug}` page.
        org_label_singular / org_label_plural: Optional deployment-wide
            override of the word "organisation"/"Organisations" shown
            throughout the UI (e.g. "Tenant"/"Tenants",
            "Business Group"/"Business Groups"). `None` for either falls
            back to the built-in English word — same "null means platform
            default" convention as `default_header_title`. Deliberately
            deployment-wide only, unlike `accent_color_hex`/`header_title`:
            there is no per-organisation override, since the word used to
            refer to organisations in general isn't a property of any one
            organisation.
        signup_mode: Server-wide public self-signup availability
            (`SignupMode`; see its docstring in `models/enums.py`). Defaults
            to DISABLED — public signup is opt-in at the deployment level.
        email_footer_company_name / email_footer_website /
            email_footer_address: Platform-wide default legal/company
            identity shown in the outgoing HTML email footer (name,
            website, postal address) — used whenever an org hasn't set its
            own `Organization.email_footer_*` override, and always for
            emails with no single org context (the daily digest, system
            test email, disk-usage alert — see
            `services/email_branding.py`). `email_footer_company_name`
            falls back to the built-in product name if left unset, same as
            `default_header_title`; the website/address have no built-in
            fallback and are simply omitted from the footer when unset.
    """

    __tablename__ = "server_settings"

    accent_color_hex: Mapped[str] = mapped_column(String(7), default="#475569")
    default_logo_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_server_settings_default_logo_file_id"),
        nullable=True,
    )
    default_header_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_login_background_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_server_settings_default_login_background_file_id"),
        nullable=True,
    )
    signup_mode: Mapped[SignupMode] = mapped_column(str_enum(SignupMode), default=SignupMode.DISABLED)
    email_footer_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_footer_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_footer_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_label_singular: Mapped[str | None] = mapped_column(String(50), nullable=True)
    org_label_plural: Mapped[str | None] = mapped_column(String(50), nullable=True)


class ReportTemplate(UUIDPKMixin, TimestampMixin, Base):
    """A named, reusable PDF report preset for an organisation (R-G-05):
    branding (accent colour, cover page, logo, footer) plus, optionally,
    its own introduction/body chapters/appendices.

    Org-scoped (shared across the org's projects) to match how the org logo
    already works. Selected optionally at report-generation time; when none
    is selected, `services/reports.py` produces today's plain, unbranded
    output with the project's own resolved content.

    Attributes:
        intro / chapters / appendices: Optional content this template
            supplies, taking precedence over the project's own resolved
            content (which itself falls back to the org's default) when
            this template is selected at generation time — a third,
            more-specific tier on top of `resolve_report_config`'s
            project-then-org-default resolution. Empty means "this template
            doesn't override content", not "explicitly blank" — same
            per-field independence as the project/org tiers.
        chapters_per_component: Whether a PDF generated with this template
            organises requirements into one chapter per component (each on
            its own page) with a sub-section per category, or renders
            continuously (category headings only, no per-component page
            breaks) — see `services/reports.py::generate_pdf_report`. A
            per-generation choice on the report page (`ReportRequest.
            chapters_per_component`) always overrides this when set.
    """

    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    accent_color_hex: Mapped[str] = mapped_column(String(7), default="#475569")
    include_cover_page: Mapped[bool] = mapped_column(Boolean, default=True)
    include_logo: Mapped[bool] = mapped_column(Boolean, default=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    intro: Mapped[str] = mapped_column(Text, default="")
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    appendices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    chapters_per_component: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class PendingInvite(UUIDPKMixin, TimestampMixin, Base):
    """An email-based invite into an organisation and, optionally, one of
    its projects — created when a project admin adds a user by email who
    has no existing account anywhere (`routers/projects.py`'s by-email
    add-user flow), and `Organization.external_user_policy` permits it.

    Only ever created for organisations with `sso_only=False`. For an
    `sso_only` org there is no working native-signup path to redeem a
    token against (native login is blocked outright for an account whose
    only org requires SSO — `auth_backends.native._all_orgs_sso_only`), so
    that flow instead provisions the `User` and role rows immediately,
    skipping this table entirely — see `docs/decisions.md`'s "Self-signup,
    invites, and SSO" entry.

    Consumed identically from two call sites via
    `services/invites.py::consume_pending_invites` — native signup
    (`routers/auth.py::signup`) and OIDC first-login
    (`routers/auth_oidc.py`), since an invitee to a non-`sso_only` org may
    reach either path first.

    Attributes:
        email: Lowercased invitee address; matched against a signing-up or
            SSO-logging-in user's own (lowercased/verified) email.
        organization_id: The organisation being granted (always, as
            `member` — see `services/invites.py`).
        project_id: The project being granted, if any — `None` for an
            org-only invite.
        project_role: The role to grant in `project_id`; `None` iff
            `project_id` is `None`.
        invited_by: The user who created this invite.
        token: Opaque, URL-safe random value embedded in the invite email's
            signup link (`/signup?invite=<token>`); not used by the SSO
            consumption path, which matches on email alone.
        expires_at: After this time the invite can no longer be redeemed.
        accepted_at: Set once consumed; `None` while still pending. An
            already-accepted or expired invite is never matched again.
    """

    __tablename__ = "pending_invites"

    email: Mapped[str] = mapped_column(String(255), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    project_role: Mapped[ProjectRole | None] = mapped_column(str_enum(ProjectRole), nullable=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
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
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))


class OrgGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """Membership of a user in an organisation group."""

    __tablename__ = "org_group_members"
    __table_args__ = (UniqueConstraint("org_group_id", "user_id"),)

    org_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
