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
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.code_rules import ABSOLUTE_MAX_CODE_LENGTH, DEFAULT_POLICY, default_code_for_name
from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.encrypted_type import EncryptedString
from app.models.enums import ExternalUserPolicy, ModuleEntitlementPolicy, OrgRole, ProjectRole, SignupMode

if TYPE_CHECKING:  # the relationship target names the model; importing it at run time would be circular
    from app.models.user import User


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
        smtp_*: Per-organisation SMTP override for outgoing notification email. Storage-only: like
            `AuthBackend` (C-U-06/07), a seam for a per-org mail relay that `services/email.py` does not
            use; it sends through the deployment-wide SMTP_HOST in `config.py` (docs/decisions.md).
            `smtp_password` is encrypted at rest (`EncryptedString`), as `oidc_client_secret`, because it
            is a credential.
        slug: URL-safe identifier used to resolve this organisation's
            branded login page at `/login/{slug}` (E-P-03).
        sso_enabled / sso_only: Whether this organisation's login page offers
            an OIDC "Sign in with SSO" button, and whether the native
            email/password form is hidden entirely when it does.
        oidc_issuer_url / oidc_client_id / oidc_client_secret: Per-org OIDC provider configuration.
            `oidc_client_secret` is encrypted at rest (`EncryptedString`).
        login_background_file_id: Optional uploaded background image for
            this organisation's login page (E-P-03), same upload pattern as
            `logo_file_id`.
        oidc_required_group: Optional access gate, distinct from `OrgGroup.granted_org_role`. When set, an
            authenticated SSO user whose IdP `groups`/`roles` claim lacks this exact value is refused a
            session (`oidc_provisioning.meets_required_group`). Access gating and role granting are separate
            checks, so the gating group need not grant a role.
        pat_max_lifetime_days: Optional cap, set by this org's admin, on the lifetime of a Personal Access
            Token scoped to this org. `None` uses `settings.pat_default_max_lifetime_days`. Enforced at PAT
            authentication, not only at creation (see `models.pat.PersonalAccessToken`).
        file_uploads_enabled / storage_quota_bytes / storage_warned: The operator's storage rules for this tenant
            (see the column comment below).
        is_active: Whether this organisation's content is reachable at all (for example suspended for
            non-payment). Reversible, unlike deletion: no data is touched. Stronger than any per-user
            role: while disabled, even the org's admins are locked out of every org/project-scoped request
            (`services/rbac.py`'s `_require_org_active`). Only a server admin toggles it
            (`POST /orgs/{id}/disable` / `/enable`), without needing org membership (I-M-05's
            tenancy-management carve-out), since a suspended org's admin is the caller that must not be
            required.
        disabled_at / disabled_by: Set when `is_active` becomes False, as `Project.archived_at`/`archived_by`;
            cleared on re-enable.
        accent_color_hex: Optional per-org override of the UI accent colour (nav highlight, primary buttons,
            links); `None` uses `ServerSettings.accent_color_hex`. One colour for light and dark theme, with
            contrast text computed (`services/branding.py::contrast_text`).
        header_title: Optional per-org override of the app-shell wordmark next to the logo; `None` uses the
            product name. Whether this and `logo_file_id` render on a page depends on whether the page is
            scoped to this org (see `frontend/src/hooks/useBranding.ts`).
        require_2fa: When set, every org/project-scoped request against this organisation from a user
            without `User.is_2fa_enabled` is blocked (`services/rbac.py::_require_org_2fa`), including the
            org's admins. Unlike a disabled org the way out is self-service: `/auth/2fa/enroll`/`confirm` are
            not org-scoped, so a blocked user can enrol and regain access.
        allow_self_signup: Whether this org is one that public signup under `ServerSettings.signup_mode ==
            ORG_SPECIFIED` can join, by domain match against `auto_accept_email_domain`
            (`routers/auth.py::signup`). Mutually exclusive with `sso_only` (validated in
            `update_advanced_settings`): self-signup is anonymous and not gated by an admin, so it must not
            hand a native password credential to an org whose members authenticate by SSO only.
        auto_accept_email_domain: The single email domain (for example "acme.com") this org auto-accepts,
            used by `ORG_SPECIFIED` self-signup and by the domain check for
            `external_user_policy == ORG_DOMAIN_ONLY`.
        external_user_policy: Whether and how a project admin may add someone by email who is not already
            an org member (`ExternalUserPolicy`, `models/enums.py`). Default DISABLED.
        allow_relaxed_child_project_creation: Whether a user who manages a project (without org-level
            `ORG_ADMIN`/`PROJECT_CREATOR`) may create a child project under it
            (`routers.projects.create_project`'s relaxed path; see `Project.parent_required`). Default
            `True`, as the "Add sub-project" entry point expects; an org admin can turn it off to require
            `ORG_ADMIN`/`PROJECT_CREATOR` for children too.
        email_footer_company_name / email_footer_website / email_footer_address: Optional per-org override of
            the HTML email footer's company identity. `None` for any falls back to the same `ServerSettings`
            field independently (as `accent_color_hex`/`header_title`), resolved by
            `services/email_branding.py::resolve_email_branding`.
        force_require_change_request_for_approved_links: When set, every project in the organisation behaves
            as though its `Project.require_change_request_for_approved_links` were true (adding or removing
            a traceability link on an approved requirement needs a change request), except a project marked
            `Project.exempt_from_org_link_lock`. See `services.requirements.requires_change_request_for_links`
            and `Project.require_change_request_for_approved_links`. Default `False`, an opt-in
            non-retroactive toggle like `allow_relaxed_child_project_creation`. Readable by any member (on
            `OrganizationOut`, not `OrgAdvancedSettingsOut`) because a project manager who is not an org
            admin needs it to render the project's settings (docs/decisions.md).
        project_customisation_locks: Keys (from `services.link_types.PROJECT_CUSTOMISATION_LOCK_KEYS`,
            currently `"link_types"`) of the vocabularies projects may not customise, so every project sees
            the org's own set. Empty (default) means projects may customise everything. A key list rather
            than a column per vocabulary; locking hides project-level rows and never deletes them.
        code: Short upper-case code (letters and digits, no hyphen) that qualifies
            organisation-scoped record codes (`ACME-PER-001`). Never equal to a
            project code in this organisation. Defaults to the name's initials.
        project_code_policy: How this organisation's project codes are formed:
            `kind`, `min_length`, `max_length` and `assignment` (`code_rules.CodePolicy`).
            A structured column so a later format option needs no migration. Applies
            to codes created from now on; existing codes are never rewritten.
        enforce_code_everywhere: When set, a record code is shown with its project
            code even inside its own project, overriding each user's preference.
        tag_mode: `"free"` or `"restricted"`: whether organisation-owned records may take a tag
            nobody listed in the organisation's tag vocabulary.
        requirement_aliases: `"allowed"` or `"disabled"`: whether a requirement may be placed in further components
            (`services.requirement_aliases`); a project may override it.
        nav_label_overrides: The organisation's default navigation names by stable navigation key
            (`services.nav_labels`); a project's own or inherited name takes precedence.
        overview_widgets: The organisation's default project overview layout (`services.overview_widgets`); SQL NULL
            means none (the built-in layout applies). A project's own or inherited layout takes precedence.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(
        String(ABSOLUTE_MAX_CODE_LENGTH), default=lambda ctx: default_code_for_name(ctx.get_current_parameters()["name"])
    )
    project_code_policy: Mapped[dict] = mapped_column(
        JSONB, default=lambda: DEFAULT_POLICY.as_dict(), server_default=text(
            "'{\"kind\": \"alphanumeric\", \"min_length\": 2, \"max_length\": 6, \"assignment\": \"auto\"}'::jsonb"
        ),
    )
    enforce_code_everywhere: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    tag_mode: Mapped[str] = mapped_column(String(12), default="free", server_default=text("'free'"))
    requirement_aliases: Mapped[str] = mapped_column(String(10), default="allowed", server_default=text("'allowed'"))
    nav_label_overrides: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    overview_widgets: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    require_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_self_signup: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_accept_email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_user_policy: Mapped[ExternalUserPolicy] = mapped_column(
        str_enum(ExternalUserPolicy), default=ExternalUserPolicy.DISABLED
    )
    allow_relaxed_child_project_creation: Mapped[bool] = mapped_column(Boolean, default=True)
    project_customisation_locks: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
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
    slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    sso_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sso_only: Mapped[bool] = mapped_column(Boolean, default=False)
    oidc_issuer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret: Mapped[str | None] = mapped_column(EncryptedString(1000), nullable=True)
    oidc_required_group: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # SCIM 2.0 inbound provisioning (routers/scim.py): a per-org bearer token hashed as a Personal Access
    # Token is (security.hash_pat; a fast SHA-256 lookup hash suits a high-entropy random secret).
    # `scim_token_prefix` is displayable, as PersonalAccessToken.token_prefix, so an admin can identify the
    # configured token. SCIM is enabled whenever `scim_token_hash` is set.
    scim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scim_token_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)

    login_background_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_organizations_login_background_file_id"),
        nullable=True,
    )
    pat_max_lifetime_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_output_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Age in days after which an imported person that nothing refers to is offered for removal on the organisation's
    #: People page; `None` (the default) never offers one. Nothing is deleted automatically.
    imported_person_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Default file name template (without extension) for a generated report that sets none of its own
    #: (`services.report_file_names`); `None` keeps the built-in "<scope>-<report>" names.
    report_file_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The organisation's one report look. Built-in reports (requirements PDF, module reports) apply it; a custom layout
    #: applies none of it unless the layout reads it as `{{org.*}}` (`services.report_org_values`).
    #: `report_accent_color_hex` falls back to the UI accent (`accent_color_hex`), then the platform default.
    report_accent_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    report_include_logo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    #: The organisation's report colour scheme: a list of `{name, colour}` (`services.report_colours`), up to 8, that a layout
    #: with no scheme of its own resolves colour names by. `None` is none set: only the four standard names resolve.
    report_colour_scheme: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB, nullable=True)
    report_footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_include_cover_page: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    #: Whether the requirements report organises requirements into one chapter per component, each on its own page.
    #: A per-generation choice (`ReportRequest.chapters_per_component`) overrides it.
    report_chapters_per_component: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    accent_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    #: Colour of the band drawn behind the organisation's logo on the login page, in outgoing email and (when set) on
    #: reports, so a light logo stays visible. `None` follows the platform value, then the application top bar colour
    #: (`services.branding.DEFAULT_LOGO_BAND_HEX`).
    logo_band_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    #: Colour of the title drawn on the band; `None` follows the platform value, then black or white by contrast.
    logo_band_text_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    #: Where the footer of this organisation's sign-in page sits (`services.branding.FOOTER_POSITIONS`); `None`
    #: follows the platform value.
    footer_position: Mapped[str | None] = mapped_column(String(20), nullable=True)
    header_title: Mapped[str | None] = mapped_column(String(100), nullable=True)

    email_footer_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_footer_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_footer_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    force_require_change_request_for_approved_links: Mapped[bool] = mapped_column(Boolean, default=False)

    # Whether an AI assistant acting through the MCP server (mcp-server/) may perform an approval-type
    # action (approve a requirement, decide a change request, complete a requirement) in this organisation's
    # projects. Consulted only for MCP-originated calls (`app.deps.get_request_channel`). It and the
    # project's `allow_ai_approvals` must both be true; there is no org-wide force, as this is a narrowing
    # gate. Off by default: enabling needs an org admin to acknowledge that an AI-made approval is not
    # necessarily a deliberate human decision (docs/decisions.md, "AI approval via MCP").
    allow_ai_approvals: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether this organisation's identity provider may create an account for an unregistered address. Off
    # keeps sign-in to existing accounts (created by an invitation, SCIM or an administrator), so a tenant's
    # provider cannot take an address another person would have registered. On by default.
    oidc_allow_account_creation: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Whether an imported project bundle keeps the approval state it carries (approved, decided or voted
    # records). On by default so a restore or move reproduces the project; off returns every imported record
    # to a draft (`services.bundle_approval_state`). Either way, imported approvers must be members of this
    # organisation and the import is audited with the count of records that arrived approved.
    allow_imported_approval_state: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Whether the organisation's own policies may contain links (`services.org_policies`). Off by default: a
    # link on a page every member trusts is a choice the organisation makes.
    allow_policy_links: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Storage rules the platform operator sets for this tenant (`services.storage_usage`, `services.files`);
    # operator policy, not organisation content, so not in the organisation bundle. `file_uploads_enabled`
    # off stops new files for this organisation; null `storage_quota_bytes` uses the server default limit
    # (null for none); `storage_warned` records that the 90% notice was sent for the current crossing, so
    # it is sent once and again only after usage falls below the threshold.
    file_uploads_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_warned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class ServerSettings(UUIDPKMixin, TimestampMixin, Base):
    """Platform-wide defaults for UI branding, created on demand as a single row
    (`services/branding.py::get_server_settings`).

    The singleton is enforced in the database through `singleton_guard` (always `True`, `UNIQUE`,
    `NOT NULL`). Application-level "read then insert if absent" is a TOCTOU race: two concurrent requests
    can both insert, leaving two rows with diverging values, and `db.scalar(select(ServerSettings))` (no
    `ORDER BY`) then returns a non-deterministic row. A racing second `INSERT` fails with an
    `IntegrityError`, which `get_server_settings` catches and re-reads.

    It supplies the value for any org that has not set its own `accent_color_hex`/`header_title`/logo, and
    for pages not scoped to an organisation (see `frontend/src/hooks/useBranding.ts`).

    Attributes:
        accent_color_hex: Platform default UI accent colour, a neutral graphite (#475569) so the product reads
            as a business tool without a branded colour.
        default_logo_file_id: Optional platform-wide logo, shown instead of an org's logo on pages with no
            org context. Same upload mechanism as `Organization.logo_file_id`.
        default_header_title: Optional platform-wide wordmark text; `None` uses the product name, as an
            org's `header_title`.
        default_login_background_file_id: Optional platform-wide background for the plain `/login` page
            (no org context); `Organization.login_background_file_id` applies only to that org's
            `/login/{slug}` page.
        org_label_singular / org_label_plural: Optional deployment-wide override of the word
            "organisation"/"Organisations" in the UI (for example "Tenant"/"Tenants"); `None` uses the
            built-in word. Deployment-wide only, because the general word for organisations is not a
            property of one organisation.
        signup_mode: Server-wide public self-signup availability (`SignupMode`, `models/enums.py`). Default
            DISABLED.
        email_footer_company_name / email_footer_website / email_footer_address: Platform default company
            identity in the HTML email footer, used when an org has no `Organization.email_footer_*`
            override and always for emails with no org context (daily digest, system test email, disk-usage
            alert; see `services/email_branding.py`). `email_footer_company_name` falls back to the product
            name; the website and address have no fallback and are omitted when unset.
        footer_prefix: Short text shown before the platform company name in the page footer and the email footer
            ("Hosted by", "Managed by"), so a person using the deployment for another organisation is not led to think
            the operator is their own company. Shown only with a platform company name, and in an email only when the
            organisation has not set its own company name.
        company_id_label / company_id: The company's registration identifier (label such as "ABN", and the number),
            shown after the address in the page footer and the email footer under the same rule as `footer_prefix`.
            The identifier shows only when it is set; a label without one is ignored.
        singleton_guard: Always `True` (see the class docstring); no application code reads or writes it.
        default_module_entitlement_policy: Deployment-wide default module entitlement
            (`ModuleEntitlementPolicy`, `models/enums.py`), used when an organisation has no override row.
        file_uploads_enabled: Whether the deployment accepts new user files
            at all (`services/files.py::assert_uploads_allowed`). Off stops
            new files only; existing files stay readable and deletable.
        default_storage_quota_bytes: The storage limit, in bytes, of an organisation that has none of its own
            (`Organization.storage_quota_bytes`); null means no limit.
    """

    __tablename__ = "server_settings"

    singleton_guard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    accent_color_hex: Mapped[str] = mapped_column(String(7), default="#475569")
    #: Platform value of the logo band colour (see `Organization.logo_band_color_hex`); `None` is the top bar colour.
    logo_band_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    #: Platform value of the band title colour (see `Organization.logo_band_text_color_hex`); `None` is automatic.
    logo_band_text_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    #: Where the footer of the signed-out pages sits: `after_content` (below the card) or `bottom_of_page`; one of
    #: `services.branding.FOOTER_POSITIONS`, validated by the update schema. An organisation may override it for its own
    #: sign-in page (`Organization.footer_position`).
    footer_position: Mapped[str] = mapped_column(String(20), nullable=False, default="after_content", server_default="after_content")
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
    footer_prefix: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_id_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    org_label_singular: Mapped[str | None] = mapped_column(String(50), nullable=True)
    org_label_plural: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The default an organisation's module entitlement falls back to without an
    # `organization_module_entitlements` row, resolved by the entitlement service rather than
    # `services/branding.py`. OPEN suits a self-hosted deployment with no licensing tiers; CLOSED a
    # commercial or SaaS posture.
    default_module_entitlement_policy: Mapped[ModuleEntitlementPolicy] = mapped_column(
        str_enum(ModuleEntitlementPolicy), default=ModuleEntitlementPolicy.OPEN
    )
    file_uploads_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    default_storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class PendingInvite(UUIDPKMixin, TimestampMixin, Base):
    """An email-based invite into an organisation and, optionally, one of its projects, created when a
    project admin adds a user by email who has no account (`routers/projects.py`'s by-email add-user flow)
    and `Organization.external_user_policy` permits it.

    Created only for organisations with `sso_only=False`. An `sso_only` org has no native-signup path to
    redeem a token (`auth_backends.native.all_orgs_sso_only` blocks native login), so that flow provisions
    the `User` and role rows immediately and skips this table (docs/decisions.md, "Self-signup, invites,
    and SSO").

    Consumed through `services/invites.py::consume_pending_invites` from native signup
    (`routers/auth.py::signup`) and OIDC first login (`routers/auth_oidc.py`), as an invitee may reach
    either first.

    Attributes:
        email: Lowercased invitee address; matched against a signing-up or
            SSO-logging-in user's own (lowercased/verified) email.
        organization_id: The organisation being granted (as `member` — see
            `services/invites.py`), or `None` for a server administrator's invite to an
            account that joins no organisation yet (never set together with `project_id`).
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
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
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

    user: Mapped[User] = relationship(back_populates="org_roles")


class OrgGroup(UUIDPKMixin, TimestampMixin, Base):
    """A named grouping of organisation users (C-U-08 groups requirement).

    Organisation groups can be nested inside project groups (C-U-12) so that an
    organisational team (e.g. "Development Team") can be granted a project
    role in a single step. Organisation groups can also be nested inside *other* org
    groups (`OrgGroupMember.member_org_group_id`), transitively — unlike
    org-group-in-project-group nesting, which deliberately resolves only
    one level deep (see docs/decisions.md), this nesting is fully
    transitive: a user in a sub-group counts as a member of every ancestor
    group too (`services.rbac._ancestor_org_group_ids`/
    `_descendant_org_group_ids`).
    """

    __tablename__ = "org_groups"
    __table_args__ = (
        # Partial unique index (enforced only when set): two groups in one org cannot both be the sync
        # target for the same IdP group name. `text()` because the column is not yet a Python name here.
        Index(
            "uq_org_group_idp_synced_group_name", "organization_id", "idp_synced_group_name",
            unique=True, postgresql_where=text("idp_synced_group_name IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    # When set, this group's user membership (not its admin-managed nested-group edges) is IdP-managed:
    # `services.oidc_provisioning.sync_org_groups_from_claims` grants or revokes it at every login by
    # whether this exact name is in the IdP's groups/roles claim, touching only groups with this field set
    # (as `sync_org_roles_from_claims`'s `sso_managed_roles`). Unique per org (partial index).
    idp_synced_group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # With `idp_synced_group_name`: a user whose IdP groups/roles claim matches the sync name is granted this
    # `OrgRole` at SSO login and loses it when the claim stops matching
    # (`services.oidc_provisioning.sync_org_roles_from_claims`). Meaningless without
    # `idp_synced_group_name`; the router enforces that, as for the other IdP-sync fields.
    granted_org_role: Mapped[OrgRole | None] = mapped_column(str_enum(OrgRole), nullable=True)


class OrgGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """A member of an organisation group: either a user, or another org
    group nested inside it (transitively resolved — see `OrgGroup`'s
    docstring).

    Exactly one of user_id / member_org_group_id must be set. Cycle
    prevention (a group can't contain itself, directly or transitively) is
    enforced at write time in `routers.orgs.add_org_group_member`, not by a
    database constraint.
    """

    __tablename__ = "org_group_members"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (member_org_group_id IS NOT NULL)::int = 1",
            name="ck_org_group_member_exactly_one_target",
        ),
        UniqueConstraint("org_group_id", "user_id", name="uq_org_group_member_user"),
        UniqueConstraint("org_group_id", "member_org_group_id", name="uq_org_group_member_nested_group"),
    )

    org_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    member_org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"), nullable=True
    )
