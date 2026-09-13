"""
Module: schemas.project

Request/response models for projects, stages, components, categories,
project groups, and project role assignments (C-G-04, C-G-07, C-G-08,
C-U-03, C-U-11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.models.enums import (
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    StageReviewResponseChoice,
    StageStatus,
)

# Module system Phase 2's grant-marker shape is defined in `schemas.org`
# (see `ModuleRoleGrantOut`'s own docstring for why), imported here rather
# than duplicated — the reverse direction of the existing `orgs.py`
# importing `MoveDirection` from this very module.
from app.schemas.org import ModuleRoleGrantOut

# Fixed, documented set of overridable terminology keys (C-C-03). Not a
# freeform key-value store — terminology only covers these nouns.
TERMINOLOGY_KEYS = {"project", "stage", "component", "category", "requirement", "change_request"}

# MIRROR_ROLE's companion role_inheritance_filter_role must be one of these —
# MEMBER is deliberately excluded, since "any parent role -> MEMBER" is
# already covered, more broadly, by MEMBER_ONLY mode (see
# ProjectRoleInheritanceMode's docstring).
_MIRROR_ROLE_ALLOWED_FILTERS = {ProjectRole.STAKEHOLDER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.PROJECT_MANAGER}


def _validate_role_inheritance_filter(mode: ProjectRoleInheritanceMode | None, filter_role: ProjectRole | None) -> None:
    """Shared MIRROR_ROLE/role_inheritance_filter_role invariant (see
    `Project.role_inheritance_filter_role`'s docstring) for both
    `ProjectCreate` and `ProjectUpdate`."""
    if mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
        if filter_role not in _MIRROR_ROLE_ALLOWED_FILTERS:
            raise ValueError(
                "role_inheritance_filter_role must be one of stakeholder, project_administrator, "
                "project_manager when role_inheritance_mode is mirror_role."
            )
    elif filter_role is not None:
        raise ValueError("role_inheritance_filter_role must not be set unless role_inheritance_mode is mirror_role.")


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str
    summary: str = ""
    template_project_id: UUID | None = None  # C-E-05: create from an existing template project
    terminology: dict[str, str] = {}
    is_template: bool = False
    # Always explicit, never inherited from a cloned template (see
    # routers/projects.py::create_project) — a template happening to be
    # org-wide-visible shouldn't silently make every project cloned from it
    # org-wide too.
    visibility: ProjectVisibility = ProjectVisibility.ONLY_SPECIFIED
    # Hierarchical projects: see Project.parent_project_id/role_inheritance_mode's
    # docstrings and routers/projects.py::create_project for the two
    # authorization paths (org-level vs. parent-manage-only) this field enables.
    parent_project_id: UUID | None = None
    role_inheritance_mode: ProjectRoleInheritanceMode = ProjectRoleInheritanceMode.NONE
    role_inheritance_filter_role: ProjectRole | None = None
    # Whether *this new* project should itself be eligible to be selected as
    # a parent later — see Project.can_be_parent's docstring. Not surfaced
    # in the standard "New project" form (a settings-tab decision, not a
    # creation-time one); exists on this schema for API/scripted use, e.g.
    # seeding a project that's immediately meant to gain children.
    can_be_parent: bool = False

    @field_validator("terminology")
    @classmethod
    def _validate_terminology_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Rejects any terminology key outside the fixed `TERMINOLOGY_KEYS` set (C-C-03)."""
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"Unknown terminology keys: {sorted(unknown)}. Allowed: {sorted(TERMINOLOGY_KEYS)}")
        return value

    @model_validator(mode="after")
    def _validate_role_inheritance_filter(self) -> ProjectCreate:
        _validate_role_inheritance_filter(self.role_inheritance_mode, self.role_inheritance_filter_role)
        return self


class ProjectOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    summary: str
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False
    is_template: bool = False
    allow_member_change_requests: bool = True
    visibility: ProjectVisibility = ProjectVisibility.ONLY_SPECIFIED
    terminology: dict[str, str] = {}
    status_id: UUID
    # Both None unless the caller has effective view access to the parent —
    # same visibility-boundary rule as ProjectListItemOut's own
    # parent_project_id/parent_project_name (see routers/projects.py's
    # _redact_parent helper) — this endpoint is require_project_view-gated,
    # not manage-gated, so an ordinary viewer must not learn a hidden
    # parent's identity just by fetching this project directly.
    parent_project_id: UUID | None = None
    parent_project_name: str | None = None
    role_inheritance_mode: ProjectRoleInheritanceMode = ProjectRoleInheritanceMode.NONE
    role_inheritance_filter_role: ProjectRole | None = None
    # Whether *this* project may be selected as a parent for other projects
    # — see Project.can_be_parent's docstring. Unlike parent_project_id/
    # parent_project_name above, never redacted: it says nothing about any
    # other project's identity, just this one's own setting.
    can_be_parent: bool = False


class ProjectImportResult(BaseModel):
    """Outcome of importing a project bundle (`POST /projects/import`) —
    the new project plus any human-readable warnings about references
    (typically users) that couldn't be matched in the target deployment
    and were remapped/dropped instead, so data loss during import is
    visible rather than silent."""

    project: ProjectOut
    warnings: list[str] = []


class ProjectUpdate(BaseModel):
    """Project settings update (name/summary, C-U-13 toggle, C-E-05 template flag).

    `parent_project_id` uses FastAPI/Pydantic's `model_fields_set` to
    distinguish "not sent, leave unchanged" from "explicitly sent" — unlike
    every other field on this schema, `parent_project_id: None` is a
    meaningful, legal value (detach from parent), not just Pydantic's
    optional-field marker, so the router checks
    `"parent_project_id" in payload.model_fields_set` rather than
    `payload.parent_project_id is not None`. `role_inheritance_filter_role`
    doesn't need the same treatment: the router forces it to `None`
    whenever the resulting `role_inheritance_mode` isn't `MIRROR_ROLE`,
    regardless of what was sent, so an explicit clear is never required
    from the client.
    """

    name: str | None = None
    summary: str | None = None
    allow_member_change_requests: bool | None = None
    is_template: bool | None = None
    visibility: ProjectVisibility | None = None
    # Must belong to the project's own organisation (400 otherwise) — see
    # `routers/projects.py::update_project`.
    status_id: UUID | None = None
    parent_project_id: UUID | None = None
    role_inheritance_mode: ProjectRoleInheritanceMode | None = None
    role_inheritance_filter_role: ProjectRole | None = None
    can_be_parent: bool | None = None


class TerminologyUpdate(BaseModel):
    """Per-project terminology overrides (C-C-03)."""

    terminology: dict[str, str]

    @field_validator("terminology")
    @classmethod
    def _validate_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Rejects any terminology key outside the fixed `TERMINOLOGY_KEYS` set (C-C-03)."""
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"Unknown terminology keys: {sorted(unknown)}. Allowed: {sorted(TERMINOLOGY_KEYS)}")
        return value


class ProjectAncestorOut(BaseModel):
    """One entry in a project's ancestor chain (`GET /{id}/ancestors`) or a
    project's list of direct children — just enough to render a link/label,
    never more. See `list_projects`'s `parent_project_name`/`children`
    population for the visibility-boundary rule both of these share: never
    includes a project the caller can't view."""

    id: UUID
    name: str


class ProjectTreeNodeOut(BaseModel):
    """One node of `GET /projects/tree` — a project plus its accessible
    children, recursively. A node whose real parent isn't in the caller's
    accessible set is rendered as a root here rather than omitted or
    hinting at a hidden parent (see `routers/projects.py::project_tree`)."""

    id: UUID
    name: str
    organization_id: UUID
    is_archived: bool
    children: list[ProjectTreeNodeOut] = []


class ProjectMemberSourceAdd(BaseModel):
    source_project_id: UUID
    mirror_mode: ProjectRoleInheritanceMode = ProjectRoleInheritanceMode.MEMBER_ONLY
    mirror_filter_role: ProjectRole | None = None

    @model_validator(mode="after")
    def _validate_mirror_filter(self) -> ProjectMemberSourceAdd:
        # Unlike Project.role_inheritance_mode (where NONE means "don't
        # inherit," a meaningful choice for an ordinary project), NONE
        # makes no sense here — a member-source *row's own existence*
        # already means "grant something from this source"; a no-op grant
        # is just "don't create the row."
        if self.mirror_mode == ProjectRoleInheritanceMode.NONE:
            raise ValueError("mirror_mode must not be 'none' — remove the member source entirely instead.")
        _validate_role_inheritance_filter(self.mirror_mode, self.mirror_filter_role)
        return self


class ProjectMemberSourceOut(BaseModel):
    """One entry in a project's member-source list (`GET/POST/DELETE
    /{id}/member-sources`) — the other project this project consumes
    members from. See `models.project.ProjectMemberSource`'s docstring for
    why this is a receiving-side-owned list rather than a flag on the
    source, and for what `mirror_mode`/`mirror_filter_role` control."""

    source_project_id: UUID
    source_project_name: str
    mirror_mode: ProjectRoleInheritanceMode
    mirror_filter_role: ProjectRole | None = None


class MemberSourceProvenanceOut(BaseModel):
    """One reason a user has a given effective role — see
    `services.rbac.get_effective_project_members_with_provenance`'s
    docstring for exactly what `kind`/`via_project_id`/`via_mode` mean.

    `via_group_id`/`via_group_name` are populated for the `"direct_group"`/
    `"direct_org_group"`/`"direct_org_group_role"` kinds — the `ProjectGroup`
    (for `direct_group`) or `OrgGroup` (for `direct_org_group`/
    `direct_org_group_role`) that actually granted the role, so the UI can
    name it instead of only saying "via group"."""

    kind: str
    role: ProjectRole
    via_project_id: UUID | None = None
    via_project_name: str | None = None
    via_mode: ProjectRoleInheritanceMode | None = None
    via_group_id: UUID | None = None
    via_group_name: str | None = None


class EffectiveMemberOut(BaseModel):
    """One user's effective access to a project, with full provenance
    (`GET /{id}/effective-members`, decision 10) — a user can have more
    than one source simultaneously (e.g. a direct grant plus an inherited
    one), so `sources` lists all of them rather than collapsing to one."""

    user_id: UUID
    display_name: str
    email: str
    effective_role: ProjectRole
    sources: list[MemberSourceProvenanceOut]
    # Module system Phase 2: this user's project-scoped module-contributed
    # role grants, filtered to currently-enabled modules only — same
    # "filter, don't delete a since-disabled module's grant" rule
    # `OrgUserOut.module_roles` documents; see that field's docstring.
    module_roles: list[ModuleRoleGrantOut] = []


class MaterializeResultOut(BaseModel):
    """Outcome of `POST /{id}/materialize-inherited-access` (decision 9) —
    which users/roles were newly created as direct grants, and which were
    skipped because they already held an equal-or-higher direct role."""

    created: list[dict[str, str]]
    skipped: list[dict[str, str]]


class ProjectListItemOut(ProjectOut):
    """Project list view row (U-E-03): includes stage and role context."""

    current_stage_name: str | None = None
    current_stage_status: StageStatus | None = None
    my_roles: list[ProjectRole] = []
    is_favorite: bool = False
    organization_name: str = ""
    requirement_count: int = 0
    # Both None unless the caller has effective view access to the parent —
    # deliberately redacted for casual list/tile browsing, never a hint that
    # a hidden parent exists. See `list_projects`'s population logic.
    parent_project_name: str | None = None
    # Direct children only, filtered to ones the caller can view — no count
    # of hidden ones either, for the same reason.
    children: list[ProjectAncestorOut] = []


class ProjectStageCreate(BaseModel):
    name: str


class ProjectStageUpdate(BaseModel):
    name: str


class ProjectStageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    status: StageStatus
    sort_order: int
    is_current: bool
    approved_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    review_deadline: datetime | None = None


class StageReviewDeadlineSet(BaseModel):
    review_deadline: datetime | None = None


class StageReviewResponseCreate(BaseModel):
    response: StageReviewResponseChoice
    comment: str | None = None


class StageReviewResponseOut(BaseModel):
    id: UUID
    stage_id: UUID
    user_id: UUID
    response: StageReviewResponseChoice
    comment: str | None = None
    responded_at: datetime


class StageCompleteRequest(BaseModel):
    cascade_to_requirements: bool = False


class ComponentCreate(BaseModel):
    name: str
    prefix: str


class ComponentUpdate(BaseModel):
    name: str
    prefix: str


class ComponentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    prefix: str
    sort_order: int


class CategoryCreate(BaseModel):
    name: str
    prefix: str
    component_id: UUID


class CategoryUpdate(BaseModel):
    name: str
    prefix: str


class CategoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    component_id: UUID
    name: str
    prefix: str
    sort_order: int


class MoveDirection(BaseModel):
    direction: str  # "up" or "down"


class ProjectGroupCreate(BaseModel):
    """Creates a bare project group with no role at all (PR7 of the
    members/groups directory rework plan, docs/decisions.md) — a group used
    to require a `role` up front (fixed for its whole lifetime, until Phase
    5 made it editable); it's now created empty and a role is a separate,
    explicit, independently-revocable grant added afterward via `POST
    /{project_id}/groups/{group_id}/roles`, symmetric with how `OrgGroup`
    (org groups) is already created bare."""

    name: str


class ProjectGroupMemberAdd(BaseModel):
    user_id: UUID | None = None
    org_group_id: UUID | None = None
    # "This group's members = that project's own direct members" — see
    # `models.project.ProjectGroupMember.source_project_id`'s docstring.
    # Exactly one of the three fields must be set; enforced by the DB check
    # constraint and re-validated at the router (matching how the existing
    # user_id/org_group_id pair is already validated there).
    source_project_id: UUID | None = None


class ProjectGroupOut(BaseModel):
    id: UUID
    name: str
    # `roles` (PR7) replaces the old single required `role` field — computed
    # from `ProjectGroupRole`, may be empty (a freshly created group with no
    # grant yet), and is not ordered/ranked; the frontend renders it as a
    # `MultiSelectDropdown`, same pattern `ProjectMembersTable`'s own Role
    # column already uses for a user's roles.
    roles: list[ProjectRole]
    member_user_ids: list[UUID]
    member_org_group_ids: list[UUID]
    member_source_project_ids: list[UUID]


class UserProjectRoleAssign(BaseModel):
    user_id: UUID
    role: ProjectRole


class OrgGroupProjectRoleAssign(BaseModel):
    """Body for `POST /{project_id}/group-roles` — the group-level
    counterpart to `UserProjectRoleAssign`, granting an organisation group a
    project role directly (`OrgGroupProjectRole`) rather than nesting it
    inside a `ProjectGroup`."""

    org_group_id: UUID
    role: ProjectRole


class ProjectGroupRoleAssign(BaseModel):
    """Body for `POST /{project_id}/groups/{group_id}/roles` (PR7) — grants
    a project group one more role, directly, as its own independently-
    revocable `ProjectGroupRole` row. No `org_group_id`/`project_group_id`
    field needed here unlike `OrgGroupProjectRoleAssign`: the target group
    is already named by the URL's own `{group_id}` path segment, and (unlike
    an org group, which could belong to any project's organisation) a
    `ProjectGroup` already belongs to exactly one project by construction —
    no cross-tenant check is needed for this endpoint the way `assign_group_
    project_role` needs one for `org_group_id`."""

    role: ProjectRole


class UserProjectRoleAssignByEmail(BaseModel):
    """Adds a project member by email — may resolve to an existing account
    (in or outside the project's organisation) or, if
    `Organization.external_user_policy` permits, a brand-new invited
    account. See `routers/projects.py::assign_project_role_by_email`."""

    email: EmailStr
    role: ProjectRole


class AssignByEmailOut(BaseModel):
    """Outcome of `assign_project_role_by_email` — the frontend shows a
    different message for each:
      - "added": an existing account was granted the role immediately.
      - "invited": a new account has no account yet; an email with a
        signup link was sent, and the role is granted once they sign up.
      - "sso_provisioned": the target org is SSO-only, so the account and
        role were both created immediately; the invitee just needs to sign
        in via SSO to start using it.
    """

    outcome: str


class PendingInviteOut(BaseModel):
    """A project's outstanding (not-yet-accepted) `PendingInvite` — the
    "resend a stalled invite" feature's list shape (Phase 3,
    docs/decisions.md). Standard (non-SSO) `PendingInvite` flow only; an
    `sso_only` org's invitees are provisioned immediately by
    `services.invites.provision_sso_invite` and never get a row here (see
    that scope decision in docs/decisions.md).

    `status` is computed at read time (`expires_at` vs. now), not stored —
    an expired invite is still listed (and still resendable) rather than
    disappearing, since resending an expired one is the whole point of
    this endpoint.
    """

    id: UUID
    email: str
    role: ProjectRole
    status: Literal["pending", "expired"]
    created_at: datetime
    expires_at: datetime


class StageProgressOut(BaseModel):
    """A single project stage's requirement-completion progress, for the
    dashboard's per-stage progress bars."""

    stage_id: UUID
    name: str
    status: StageStatus
    requirement_count: int
    completed_percent: float


class ProjectMetricsOut(BaseModel):
    """Project overview dashboard metrics (U-P-05).

    `requirements_by_status`/`stage_progress` back the dashboard's chart
    views; they group by the project's actual status/stage model rather
    than a separate "release version" concept, since ReqTrackManager tracks
    requirement lifecycle status and project stages, not independent
    parallel release versions (see docs/decisions.md).

    `file_count` is the requirement's explicitly-listed metric ("number of
    files in project, if files are implemented") — counts distinct
    `FileAsset` rows attached to a requirement in this project, i.e.
    requirement attachments, not organisation-wide shared resources (which
    aren't scoped to a single project).
    """

    requirement_count: int
    requirement_completed_percent: float
    change_requests_proposed: int
    change_requests_approved: int
    change_requests_rejected: int
    file_count: int = 0
    requirements_by_status: dict[str, int] = {}
    stage_progress: list[StageProgressOut] = []
