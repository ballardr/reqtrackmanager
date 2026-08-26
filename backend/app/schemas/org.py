"""
Module: schemas.org

Request/response models for organisations, organisation users, and
organisation groups (C-U-01, C-U-04, C-U-05, C-U-08).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import ExternalUserPolicy, OrgRole, ProjectRole
from app.schemas.report import ReportChapter


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Rejects a whitespace-only name (`min_length` alone only blocks a
        literal empty string). A blank organisation name isn't just a
        display nit: `DELETE /orgs/{id}`'s "type the exact name to confirm"
        safety gate (`OrganizationDeleteConfirm`) degenerates to comparing
        two empty strings for such an org — the "must not be a stray click"
        guarantee that gate exists for would otherwise hold for every other
        organisation but this one (a hardening-review finding)."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Organisation name cannot be blank.")
        return stripped


class OrganizationRename(BaseModel):
    """Renames an organisation (`PUT /orgs/{id}/name`) — the org's display
    name is otherwise only ever set once, at creation (`OrganizationCreate`)."""

    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Same non-blank guard as `OrganizationCreate.name` — see that
        validator's docstring for why a blank name specifically breaks the
        `DELETE /orgs/{id}` confirmation gate."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Organisation name cannot be blank.")
        return stripped


class OrganizationDeleteConfirm(BaseModel):
    """Safety gate for `DELETE /orgs/{id}`: the caller must type the
    organisation's exact current name, the same "type the name to confirm"
    pattern used by other tools for irreversible actions — this one
    permanently destroys every project/requirement/change request/file the
    organisation owns, with no archive or undo, so a stray click alone must
    never be enough."""

    confirm_name: str


class OrganizationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    created_at: datetime
    logo_file_id: UUID | None = None
    default_template_project_id: UUID | None = None
    login_background_file_id: UUID | None = None
    slug: str | None = None
    is_active: bool = True
    disabled_at: datetime | None = None
    accent_color_hex: str | None = None
    header_title: str | None = None
    email_footer_company_name: str | None = None
    email_footer_website: str | None = None
    email_footer_address: str | None = None


class OrgImportResult(BaseModel):
    """Outcome of importing an organisation bundle (`POST /orgs/import`) —
    the new organisation plus any human-readable warnings (unmatched user
    references remapped/invited instead, an sso_only source config that
    wasn't carried over, etc.), so nothing lost during import is silent."""

    organization: OrganizationOut
    warnings: list[str] = []


class MergeConflictOut(BaseModel):
    """One project or report template in an org bundle whose name collides
    with something the target organisation already has
    (`services.org_export.detect_merge_conflicts`). `id` is the exact key
    `OrgMergeRequest.resolutions` must supply a resolution for."""

    id: str
    kind: str
    name: str
    existing_id: UUID


class OrgMergePreviewResult(BaseModel):
    """Response of `POST /orgs/{id}/import/preview`: every conflict this
    bundle has against this organisation. An empty list means the bundle
    can be merged in with no resolutions needed."""

    conflicts: list[MergeConflictOut] = []


class OrgMergeResult(BaseModel):
    """Outcome of `POST /orgs/{id}/import/merge` — human-readable warnings
    (same shape as `OrgImportResult`'s) plus counts of what happened to
    each conflicting/non-conflicting project and report template."""

    warnings: list[str] = []
    projects_imported: int
    projects_skipped: int
    report_templates_imported: int
    report_templates_overwritten: int


_HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class OrgBrandingUpdate(BaseModel):
    """Sets (or clears, with a null value) this organisation's UI accent
    colour, header wordmark override, and outgoing-email footer identity
    (`email_footer_*`). All fall back to the platform default
    (`ServerSettings`) when null."""

    accent_color_hex: str | None = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    header_title: str | None = Field(default=None, max_length=100)
    email_footer_company_name: str | None = Field(default=None, max_length=255)
    email_footer_website: str | None = Field(default=None, max_length=500)
    email_footer_address: str | None = Field(default=None, max_length=2000)

    @field_validator("header_title", "email_footer_company_name", "email_footer_website", "email_footer_address")
    @classmethod
    def _blank_means_unset(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value


class DefaultTemplateUpdate(BaseModel):
    """Sets or clears the organisation's default template project (C-E-04)."""

    project_id: UUID | None


class OrgAdvancedSettingsOut(BaseModel):
    """Per-organisation SMTP override, Personal Access Token lifetime-cap,
    self-signup, and external-user settings — see `Organization` model
    docstring and docs/decisions.md. SSO group→role mapping used to live
    here too (`sso_group_mappings`); it's now a per-`OrgGroup` property
    (`OrgGroup.granted_org_role`, alongside `idp_synced_group_name`) —
    2026-08 UX audit roadmap item 522 — managed via the org groups
    endpoints, not this one."""

    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_use_tls: bool = True
    pat_max_lifetime_days: int | None = None
    require_2fa: bool = False
    allow_self_signup: bool = False
    auto_accept_email_domain: str | None = None
    external_user_policy: ExternalUserPolicy = ExternalUserPolicy.DISABLED
    allow_relaxed_child_project_creation: bool = True


class OrgAdvancedSettingsUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    pat_max_lifetime_days: int | None = Field(default=None, ge=1, le=3650)
    require_2fa: bool = False
    allow_self_signup: bool = False
    auto_accept_email_domain: str | None = Field(default=None, max_length=255)
    external_user_policy: ExternalUserPolicy = ExternalUserPolicy.DISABLED
    allow_relaxed_child_project_creation: bool = True


class OrgUserCreate(BaseModel):
    """Creates a brand-new user directly within an organisation."""

    email: EmailStr
    display_name: str
    password: str
    role: OrgRole = OrgRole.MEMBER


class OrgUserOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    is_active: bool
    is_archived: bool
    roles: list[OrgRole]
    display_name_locked: bool = False
    last_login_at: datetime | None = None
    is_2fa_enabled: bool = False


class ExternalUserMatch(BaseModel):
    """A search result for an email that isn't (yet) a member of the
    searched organisation — surfaced only when `Organization.
    external_user_policy` allows it (`routers/orgs.py::search_org_users`).
    """

    email: str
    exists: bool = Field(description="Whether a User account with this email already exists anywhere in the system.")


class OrgUserSearchResult(BaseModel):
    """Response for the project user picker's org-scoped-by-default search
    (`routers/orgs.py::search_org_users`)."""

    members: list[OrgUserOut] = []
    external: ExternalUserMatch | None = None


class OutsideDomainUserOut(BaseModel):
    """A user matching the organisation's configured `auto_accept_email_domain`
    who is not currently a member (`routers/orgs.py::list_outside_domain_users`)."""

    user_id: UUID
    email: str
    display_name: str


class OrgSsoConfigUpdate(BaseModel):
    """Per-organisation SSO/OIDC configuration (E-U-01, E-P-03)."""

    slug: str | None = None
    sso_enabled: bool = False
    sso_only: bool = False
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_required_group: str | None = None


class OrgSsoConfigOut(BaseModel):
    slug: str | None = None
    sso_enabled: bool
    sso_only: bool
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_required_group: str | None = None


class ScimTokenStatusOut(BaseModel):
    """Whether SCIM provisioning is enabled for this org, and (if so) the
    non-secret prefix of its current token — never the token itself."""

    enabled: bool
    token_prefix: str | None = None


class ScimTokenCreatedOut(BaseModel):
    """Returned exactly once, immediately after (re)generating a SCIM
    token — the raw secret is never retrievable again afterward."""

    token: str
    token_prefix: str


class OrgLoginInfoOut(BaseModel):
    """Public, unauthenticated org-branded login page info (E-P-03) — no
    secrets, just enough to render the page and offer an SSO button."""

    name: str
    slug: str
    logo_file_id: UUID | None = None
    login_background_file_id: UUID | None = None
    sso_enabled: bool
    sso_only: bool


class ReportTemplateCreate(BaseModel):
    name: str
    accent_color_hex: str = Field(default="#475569", pattern=_HEX_COLOR_PATTERN)
    include_cover_page: bool = True
    include_logo: bool = True
    footer_text: str | None = None
    intro: str = ""
    chapters: list[ReportChapter] = []
    appendices: list[ReportChapter] = []
    chapters_per_component: bool = True


class ReportTemplateOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    accent_color_hex: str
    include_cover_page: bool
    include_logo: bool
    footer_text: str | None = None
    intro: str = ""
    chapters: list[ReportChapter] = []
    appendices: list[ReportChapter] = []
    chapters_per_component: bool = True


class OrgProjectSummaryOut(BaseModel):
    """A minimal, name-only view of a project for the org-admin project
    directory (`GET /orgs/{id}/projects`) — deliberately excludes anything
    that would count as project *content* (summary, requirement counts,
    stage status, ...), since this endpoint exists to let an org admin
    reach a project's user/role management without content access."""

    id: UUID
    name: str
    is_archived: bool


class DisplayNameLockUpdate(BaseModel):
    """Locks or unlocks a user's ability to change their own display name (C-U-16)."""

    display_name_locked: bool


class OrgRoleAssign(BaseModel):
    user_id: UUID
    role: OrgRole


class OrgGroupCreate(BaseModel):
    name: str
    idp_synced_group_name: str | None = None
    # Only meaningful alongside `idp_synced_group_name` — see `OrgGroup.
    # granted_org_role`'s model docstring. Validated together at the router
    # layer, not here: a create payload can legitimately set `idp_synced_
    # group_name` without `granted_org_role` (sync membership only, no
    # role), but not the other way around.
    granted_org_role: OrgRole | None = None


class OrgGroupUpdate(BaseModel):
    """Currently only the IdP-sync target and its granted role can be
    changed after creation — renaming isn't supported (matching this
    codebase's existing scope for `OrgGroup`/`ProjectGroup`, neither of
    which have a rename endpoint)."""

    idp_synced_group_name: str | None = None
    granted_org_role: OrgRole | None = None


class OrgGroupMemberAdd(BaseModel):
    """Exactly one of `user_id` / `member_org_group_id` must be set — mirrors
    `ProjectGroupMemberAdd`'s user-or-org-group shape one level up; the
    router checks this explicitly (same convention as
    `add_project_group_member`), not a pydantic validator."""

    user_id: UUID | None = None
    member_org_group_id: UUID | None = None


class OrgGroupOut(BaseModel):
    id: UUID
    name: str
    member_user_ids: list[UUID]
    member_org_group_ids: list[UUID] = []
    idp_synced_group_name: str | None = None
    granted_org_role: OrgRole | None = None


class UserAccessGroupRef(BaseModel):
    """A group name/id pair, used by `UserAccessOut` for both org groups
    and (nested inside each project entry) project groups — deliberately
    minimal, since this is a read-only summary, not the full `OrgGroupOut`/
    `ProjectGroupOut` shape a management screen needs."""

    id: UUID
    name: str


class UserAccessProject(BaseModel):
    project_id: UUID
    project_name: str
    roles: list[ProjectRole]
    project_groups: list[UserAccessGroupRef]


class UserAccessOut(BaseModel):
    """One user's access within a single organisation (2026-08 UX audit,
    sixth pass: "No way to view a user's access") — every project in the
    org where the user holds at least one effective role (direct
    assignment, direct/nested project-group membership, or org-wide
    project visibility — see `rbac.get_effective_project_roles`), each
    with that role set and which of the project's own groups the user is a
    *direct* member of, plus the org groups the user directly belongs to.

    Deliberately omits projects where the user has no access at all
    (rather than listing every org project with an empty role set) — this
    is "what can they reach," not a roster of every project that exists."""

    org_groups: list[UserAccessGroupRef]
    projects: list[UserAccessProject]
