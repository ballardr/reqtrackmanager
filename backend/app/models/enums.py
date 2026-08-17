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


class ProjectRole(str, enum.Enum):
    """Project-level permission roles (C-U-03)."""

    PROJECT_MANAGER = "project_manager"
    PROJECT_ADMINISTRATOR = "project_administrator"
    STAKEHOLDER = "stakeholder"
    MEMBER = "member"


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
    """Lifecycle states for a requirement (C-G-11)."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ChangeRequestKind(str, enum.Enum):
    """Whether a change request proposes a new requirement or a modification."""

    NEW_REQUIREMENT = "new_requirement"
    MODIFY_REQUIREMENT = "modify_requirement"


class ChangeRequestStatus(str, enum.Enum):
    """Lifecycle states for a change request (introduction, C-G-03)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ReviewTargetType(str, enum.Enum):
    """What a discussion thread comment is attached to (C-R-01)."""

    REQUIREMENT = "requirement"
    CHANGE_REQUEST = "change_request"


class RequirementLinkType(str, enum.Enum):
    """Traceability relationship types between requirements (C-G-09)."""

    RELATES_TO = "relates_to"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"


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
