"""
Module: models.enums

All fixed vocabularies used by the domain model. Ossa (v1) intentionally uses
a small, fixed set of organisation and project roles rather than a
customisable permission system (customisable roles/attributes are a Pelion
(v2) concern per docs/requirements.md).
"""

import enum


class OrgRole(str, enum.Enum):
    """Organisation-level permission roles (C-U-01)."""

    ORG_ADMIN = "org_admin"
    PROJECT_CREATOR = "project_creator"
    MEMBER = "member"


class ServerRole(str, enum.Enum):
    """Server-tier (cross-tenant) permission roles, additive to
    `User.is_server_admin` (compliance-module-plan.md Phase 0).

    SERVER_ADMIN mirrors the existing `User.is_server_admin` boolean's
    power level for composition purposes (e.g. `services.rbac.
    require_server_role`'s "is_server_admin implies every server role"
    check) but is never itself written as a `UserServerRole` row —
    `is_server_admin` remains the sole source of truth for that tier, left
    completely untouched by this enum's introduction (docs/decisions.md,
    "Compliance Module + Modular Feature System" entry). Only
    MODULE_ADMINISTRATOR is ever actually granted via `UserServerRole`.

    MODULE_ADMINISTRATOR: narrower than SERVER_ADMIN — manages module
    entitlements/enablement (the module system built out in later phases)
    without the full cross-tenant power `is_server_admin` implies. Grantable
    only by an existing SERVER_ADMIN (standard privilege-escalation-safe
    pattern: a narrower role can never grant itself or others a role).
    """

    SERVER_ADMIN = "server_admin"
    MODULE_ADMINISTRATOR = "module_administrator"


class ModuleEntitlementPolicy(str, enum.Enum):
    """Deployment-wide default for whether an organisation is entitled to a
    module absent an explicit `organization_module_entitlements` override
    row (`ServerSettings.default_module_entitlement_policy`,
    compliance-module-plan.md Phase 0/1).

    OPEN: every module is entitled by default — the right default for a
        self-hosted/open-source deployment with no licensing tiers.
    CLOSED: no module is entitled by default — a future commercial/SaaS
        posture of the same codebase can flip this and grant entitlements
        explicitly per organisation instead.
    """

    OPEN = "open"
    CLOSED = "closed"


class ProjectRole(str, enum.Enum):
    """Project-level permission roles (C-U-03)."""

    PROJECT_MANAGER = "project_manager"
    PROJECT_ADMINISTRATOR = "project_administrator"
    STAKEHOLDER = "stakeholder"
    MEMBER = "member"


class ProjectRoleInheritanceMode(str, enum.Enum):
    """How a project's effective roles are extended from its parent project
    (`Project.parent_project_id`), resolved in `services.rbac`.

    NONE: no cascade (default) — the project's roles are exactly its own
        direct/group/org-wide resolution, same as any project today.
    MIRROR_ALL: every role a user holds on the parent (via the parent's own
        direct resolution) is mirrored onto this project as that same role.
    MIRROR_ROLE: only users holding the specific role named in
        `Project.role_inheritance_filter_role` on the parent get that same
        role mirrored onto this project; everyone else on the parent gets
        nothing from this mechanism.
    MEMBER_ONLY: any user holding any role on the parent gets baseline
        `ProjectRole.MEMBER` on this project, regardless of which role they
        actually hold on the parent.

    MIRROR_ALL/MIRROR_ROLE can convey PROJECT_MANAGER/PROJECT_ADMINISTRATOR
    control and require a tier-2 UI confirmation; MEMBER_ONLY caps at
    baseline read access, the same risk profile as `ProjectVisibility.ORG_WIDE`.
    """

    NONE = "none"
    MIRROR_ALL = "mirror_all"
    MIRROR_ROLE = "mirror_role"
    MEMBER_ONLY = "member_only"


class ProjectVisibility(str, enum.Enum):
    """Who can see a project without an explicit user/group assignment.

    ONLY_SPECIFIED: today's only behaviour — access is granted purely via
        direct `UserProjectRole`/`ProjectGroupMember` assignment
        (`services.rbac.get_effective_project_roles`). The default for
        every project, including ones cloned from a template.
    ORG_WIDE: every member of the project's organisation automatically
        gets baseline `ProjectRole.MEMBER` (view-only) access, with no
        assignment needed — never manager/administrator/stakeholder,
        which still require an explicit grant. Deliberately does not
        extend to project-broadcast notifications (`get_project_member_user_ids`)
        or org-admin's project-settings carve-out
        (`can_manage_project_settings`) — see `services.rbac`'s docstring.
    """

    ONLY_SPECIFIED = "only_specified"
    ORG_WIDE = "org_wide"


class StageStatus(str, enum.Enum):
    """Lifecycle states for a project stage (introduction, C-G-08).

    ARCHIVED is a terminal state a stage can be moved to manually (e.g. via
    `transition_stage`); it carries no special gating logic of its own —
    unlike APPROVED it doesn't write a baseline or require the project
    manager role, it's purely a display/filtering state.
    """

    SCOPING = "scoping"
    REVIEW = "review"
    APPROVED = "approved"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RequirementLevel(str, enum.Enum):
    """How binding a requirement's content is: mandatory, advisory, or
    purely optional. Distinct from `RequirementStatus`, which tracks
    lifecycle state, not bindingness."""

    REQUIREMENT = "requirement"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class RequirementStatus(str, enum.Enum):
    """Lifecycle states for a requirement (C-G-11).

    `COMPLETED` deliberately does not exist here (removed; see migration
    0018 and docs/decisions.md) — C-G-11 is explicit that completion is
    "independently of lifecycle state," an overlay marker rather than a
    lifecycle status, so it lives on `Requirement.is_completed`/
    `completed_at`/`completed_by` instead, layered on top of `APPROVED`
    rather than replacing it.
    """

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ChangeRequestKind(str, enum.Enum):
    """What a change request proposes: a new requirement, a modification to
    an existing one, or (2026-08 UX audit roadmap item 514) adding an
    action to a requirement once it's locked — mirrors the same
    change-request-only-once-locked rule `MODIFY_REQUIREMENT` already
    enforces (`services.requirements.LOCKED_STATUSES`), extended to actions
    rather than inventing a separate mechanism."""

    NEW_REQUIREMENT = "new_requirement"
    MODIFY_REQUIREMENT = "modify_requirement"
    ADD_ACTION = "add_action"


class ChangeRequestStatus(str, enum.Enum):
    """Lifecycle states for a change request (introduction, C-G-03)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ReviewTargetType(str, enum.Enum):
    """What a discussion thread comment is attached to (C-R-01).

    ACTION: a `RequirementAction`'s own discussion thread, reusing the same
    generic `ReviewComment`/`CommentFile` machinery as requirements and
    change requests rather than a fourth parallel comment model (see
    `models.requirement_action`'s module docstring).
    """

    REQUIREMENT = "requirement"
    CHANGE_REQUEST = "change_request"
    ACTION = "action"


class RequirementActionOutcome(str, enum.Enum):
    """Lifecycle/outcome state of a `RequirementAction`.

    Kept as a small fixed enum rather than a fourth org/project-configurable
    definition table (unlike `ProjectStatusDefinition`,
    `RequirementLinkTypeDefinition`, `ActionTypeDefinition`): nothing in the
    feature request asks this vocabulary to vary per org/project, and every
    comparable lifecycle vocabulary already in this codebase
    (`RequirementReviewOutcome`, `ChangeRequestStatus`) is a fixed enum too.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class RequirementReviewOutcome(str, enum.Enum):
    """Outcome recorded when a requirement's scheduled review is performed (C-R-07)."""

    MET = "met"
    FAILED = "failed"


class ChangeRequestVoteChoice(str, enum.Enum):
    """A stakeholder's advisory vote on a change request (C-R-03)."""

    APPROVE = "approve"
    REJECT = "reject"


class StageReviewResponseChoice(str, enum.Enum):
    """A stakeholder's response to a project stage's review deadline (C-R-05)."""

    APPROVED = "approved"
    REJECTED = "rejected"


class SignupMode(str, enum.Enum):
    """Server-wide public self-signup availability (`ServerSettings.signup_mode`).

    DISABLED: No public signup form; every native account is provisioned by
        an org/server admin (`create_org_user`) or via SSO.
    ALWAYS_ON: Anyone can self-register a native account. No organisation
        membership is granted automatically, regardless of email domain — an
        admin assigns the new account to an organisation afterward.
    ORG_SPECIFIED: Self-registration succeeds only when the typed email's
        domain matches exactly one organisation that has both
        `allow_self_signup=True` and a configured `auto_accept_email_domain`
        — that organisation's domain configuration *is* the gate, not a
        separate open-signup mode. See `routers/auth.py::signup`.
    """

    DISABLED = "disabled"
    ALWAYS_ON = "always_on"
    ORG_SPECIFIED = "org_specified"


class ExternalUserPolicy(str, enum.Enum):
    """Whether/how a project admin may add someone to a project by typing an
    email address that isn't already an organisation member
    (`Organization.external_user_policy`).

    DISABLED: The project user picker only shows existing org members — no
        email-based add, no invites. Equivalent to "don't allow external
        users" (the default).
    ORG_DOMAIN_ONLY: An email matching an *existing* account anywhere in the
        system can always be added directly (granting org membership as a
        side effect, C-U-02). A not-yet-registered email can only be
        invited if its domain matches `Organization.auto_accept_email_domain`.
    ANYONE: Same as ORG_DOMAIN_ONLY, but a not-yet-registered email of any
        domain can be invited.
    """

    DISABLED = "disabled"
    ORG_DOMAIN_ONLY = "org_domain_only"
    ANYONE = "anyone"
