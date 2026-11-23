"""
Module: models.enums

All fixed vocabularies used by the domain model. The fixed `OrgRole`/`ProjectRole` sets are unconditional;
the customisable permission system (a core platform capability) is additive to them: see `PermissionLevel`
below and `app.models.custom_role.CustomRoleDefinition`.
"""

import enum


class OrgRole(str, enum.Enum):
    """Organisation-level permission roles (C-U-01)."""

    ORG_ADMIN = "org_admin"
    PROJECT_CREATOR = "project_creator"
    MEMBER = "member"


class ServerRole(str, enum.Enum):
    """Server-tier (cross-tenant) permission roles, additive to `User.is_server_admin`.

    SERVER_ADMIN mirrors `User.is_server_admin` for composition (`services.rbac.require_server_role`
    treats `is_server_admin` as implying every server role) but is never written as a `UserServerRole`
    row: `is_server_admin` is the sole source of truth for that tier (docs/decisions.md, "Compliance Module
    + Modular Feature System"). The other members are granted through `UserServerRole`.

    MODULE_ADMINISTRATOR: narrower than SERVER_ADMIN; manages module entitlements and enablement without
    the full cross-tenant power `is_server_admin` implies. Grantable only by a SERVER_ADMIN, so a narrower
    role can never grant itself or others a role.

    SUBSCRIPTION_MANAGER ("Platform subscription manager"): provisions and
    bounds organisations (create, import, suspend, per-organisation module
    entitlements, storage controls) and reads their names, states and
    counts. It never reads tenant content, joins an organisation as its
    administrator, or deletes one.

    SUBSCRIPTION_REMOVAL_AUTHORITY ("Subscription removal authority"):
    deletes an organisation and its data, and reads the same counts-only
    list needed to find and confirm the target. Independent of
    SUBSCRIPTION_MANAGER (neither implies the other) so provisioning never
    carries the power to destroy a tenant. Both are grantable only by a
    SERVER_ADMIN.
    """

    SERVER_ADMIN = "server_admin"
    MODULE_ADMINISTRATOR = "module_administrator"
    SUBSCRIPTION_MANAGER = "subscription_manager"
    SUBSCRIPTION_REMOVAL_AUTHORITY = "subscription_removal_authority"


class ModuleEntitlementPolicy(str, enum.Enum):
    """Deployment-wide default for whether an organisation is entitled to a module absent an explicit
    `organization_module_entitlements` row (`ServerSettings.default_module_entitlement_policy`).

    OPEN: every module is entitled by default, for a self-hosted deployment with no licensing tiers.
    CLOSED: no module is entitled by default; entitlements are granted per organisation (a commercial or
        SaaS posture).
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

    NONE: no cascade (default); the project's roles are its own direct, group and org-wide resolution.
    MIRROR_ALL: every role a user holds on the parent (by the parent's direct resolution) is mirrored onto
        this project as the same role.
    MIRROR_ROLE: only users holding the role named in `Project.role_inheritance_filter_role` on the parent
        get that role mirrored onto this project.
    MEMBER_ONLY: any user holding any role on the parent gets baseline `ProjectRole.MEMBER` here.

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

    ONLY_SPECIFIED: access comes only from direct `UserProjectRole`/`ProjectGroupMember` assignment
        (`services.rbac.get_effective_project_roles`). The default for every project, including ones
        cloned from a template.
    ORG_WIDE: every member of the project's organisation gets baseline `ProjectRole.MEMBER` (view-only)
        access without assignment; manager, administrator and stakeholder still need an explicit grant.
        It does not extend to project-broadcast notifications (`get_project_member_user_ids`) or the
        org-admin project-settings carve-out (`can_manage_project_settings`); see `services.rbac`.
    """

    ONLY_SPECIFIED = "only_specified"
    ORG_WIDE = "org_wide"


class BaselineKind(str, enum.Enum):
    """How a baseline came about.

    STAGE: written automatically when a stage enters a locked phase (it names the stage, and a component's own
        baseline names the component too).
    MANUAL: taken on request at any time; it names no stage and approves nothing.
    """

    STAGE = "stage"
    MANUAL = "manual"


class StagePhaseKind(str, enum.Enum):
    """What a stage workflow phase does, whatever it is called.

    The phase name is free text; this closed vocabulary carries the behaviour,
    so the baseline, the edit lock and completion never read a name.

    OPEN: requirements are editable and may be reordered.
    REVIEW: requirements are editable; a review deadline and stakeholder
        responses apply, and a passed deadline with no objection moves the
        stage to the workflow's locked phase.
    LOCKED: entering it writes an immutable baseline; requirement edits then
        go through change requests only. Entering or leaving it needs the
        project manager role.
    ON_HOLD: paused or archived; no gating of its own.
    CLOSED: the stage is complete; entering it records who and when and can
        cascade to the stage's approved requirements. Edits stay locked.
    """

    OPEN = "open"
    REVIEW = "review"
    LOCKED = "locked"
    ON_HOLD = "on_hold"
    CLOSED = "closed"


class RequirementLevel(str, enum.Enum):
    """How binding a requirement's content is: mandatory, advisory, or
    purely optional. Distinct from `RequirementStatus`, which tracks
    lifecycle state, not bindingness."""

    REQUIREMENT = "requirement"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class RequirementStatus(str, enum.Enum):
    """Lifecycle states for a requirement (C-G-11).

    There is no `COMPLETED` member: C-G-11 makes completion independent of lifecycle state, so it is an
    overlay marker on `Requirement.is_completed`/`completed_at`/`completed_by`, layered on `APPROVED`
    (docs/decisions.md).
    """

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ChangeRequestKind(str, enum.Enum):
    """What a change request proposes: a new requirement, a modification to an existing one, adding or
    removing an action on a locked requirement, or adding or removing a traceability link on a locked
    requirement where the project (or an org-wide force) requires it. The action and link kinds follow the
    change-request-only-once-locked rule of `MODIFY_REQUIREMENT` (`services.requirements.LOCKED_STATUSES`).
    The `ADD_ACTION`/`REMOVE_ACTION` gate applies to every project; `ADD_LINK`/`REMOVE_LINK` also need
    `services.requirements.requires_change_request_for_links` to be true for the project."""

    NEW_REQUIREMENT = "new_requirement"
    MODIFY_REQUIREMENT = "modify_requirement"
    ADD_ACTION = "add_action"
    REMOVE_ACTION = "remove_action"
    ADD_LINK = "add_link"
    REMOVE_LINK = "remove_link"


class ProposedLinkOutcome(str, enum.Enum):
    """What became of a link proposed on a change request: waiting for a decision
    (`pending`), created on approval (`merged`), left out by the approver
    (`declined`, or any link on a rejected or withdrawn request), or not valid at
    approval and so not created (`skipped`, with a reason)."""

    PENDING = "pending"
    MERGED = "merged"
    DECLINED = "declined"
    SKIPPED = "skipped"


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

    ACTION: a `RequirementAction`'s discussion thread, sharing the `ReviewComment`/`CommentFile`
    machinery of requirements and change requests (see `models.requirement_action`).
    """

    REQUIREMENT = "requirement"
    CHANGE_REQUEST = "change_request"
    ACTION = "action"


class ArtefactType(str, enum.Enum):
    """The three built-in values a polymorphic `ArtefactLink` (`models.relationship`) may hold on either end.

    An `enum.Enum` cannot gain members at runtime, so modules do not extend it (that would need a core edit
    per module). `ArtefactLink.source_type`/`target_type` are plain validated strings; a module declares its
    values on `ModuleDefinition.artefact_types` (`app.modules.registry`), and
    `get_all_registered_artefact_types` merges them with these into the set
    `services.relationships.create_link` validates against.
    """

    REQUIREMENT = "requirement"
    REQUIREMENT_ACTION = "requirement_action"
    CHANGE_REQUEST = "change_request"


CORE_ARTEFACT_TYPES: frozenset[str] = frozenset(t.value for t in ArtefactType)
"""Every core artefact type value; the base set a module's `artefact_types` extend."""


class LinkFlow(str, enum.Enum):
    """Which way a typed link points in a traceability chain
    (`RequirementLinkTypeDefinition.flow`), read from the link's source to its
    target using the type's `forward_name`.

    NONE: no direction (symmetric, e.g. "Related to"); also every type an
        organisation has not classified.
    FORWARD_IS_UPSTREAM: the target is a source/origin of the link's source
        (e.g. "Derives from").
    FORWARD_IS_DOWNSTREAM: the target depends on or follows from the link's
        source (e.g. "Is implemented by").
    """

    NONE = "none"
    FORWARD_IS_UPSTREAM = "forward_is_upstream"
    FORWARD_IS_DOWNSTREAM = "forward_is_downstream"


class LinkNestingScope(str, enum.Enum):
    """Whether, and in which direction, a link type may join artefacts of a
    project and one of its ancestors or descendants
    (`RequirementLinkTypeDefinition.nesting_scope`).

    SAME_PROJECT: both ends must be in one project (cross-level linking is off
        for this type).
    UPSTREAM_IN_ANCESTOR: the *upstream* end (per the type's `LinkFlow`) must be
        in the same project as the downstream end or one of its ancestors; a
        pain point may sit above a requirement, never below it. Needs a `flow`
        other than `NONE`.
    ANCESTOR_EITHER_WAY: either end may be in the ancestor project.
    """

    SAME_PROJECT = "same_project"
    UPSTREAM_IN_ANCESTOR = "upstream_in_ancestor"
    ANCESTOR_EITHER_WAY = "ancestor_either_way"


class PermissionLevel(str, enum.Enum):
    """The permission-level taxonomy crossed with every registered artefact type
    (`app.modules.registry.get_all_registered_artefact_types`) to derive the permission-atom vocabulary
    (`app.services.permissions.get_all_permissions`).

    VIEW is an independent atom: a role can hold `VIEW` alone (read-only) without any write tier, so read
    and write are separate.

    PROPOSE_CREATE: create or propose a new artefact of this type (drafting a Requirement, submitting a
        Change Request) without directly editing or approving an existing one.
    MANAGE: edit an existing artefact of this type, short of approving or baselining it.
    LINK: set and remove links on an existing artefact of this type, and nothing else. Link authoring
        accepts `LINK` or `MANAGE`; `MANAGE` is not rewritten to imply `LINK`, so the vocabulary stays a
        flat set of independent atoms.
    APPROVE_BASELINE: approve, baseline or otherwise finalise an artefact of this type; the tier
        Decision Management's per-Decision-Type approval scoping is expressed against.
    """

    VIEW = "view"
    PROPOSE_CREATE = "propose_create"
    MANAGE = "manage"
    LINK = "link"
    APPROVE_BASELINE = "approve_baseline"


class RequirementActionOutcome(str, enum.Enum):
    """Lifecycle/outcome state of a `RequirementAction`.

    A fixed enum, not an org/project-configurable definition table (unlike `ProjectStatusDefinition`,
    `RequirementLinkTypeDefinition`, `ActionTypeDefinition`): like `RequirementReviewOutcome` and
    `ChangeRequestStatus`, this lifecycle vocabulary does not vary per organisation or project.
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

    DISABLED: No public signup form; an organisation or server admin (`create_org_user`) or SSO provisions
        every native account.
    ALWAYS_ON: Anyone can self-register a native account. No organisation membership is granted
        automatically; an admin assigns the account afterward.
    ORG_SPECIFIED: Self-registration succeeds only when the email's domain matches exactly one organisation
        with `allow_self_signup=True` and a configured `auto_accept_email_domain`; that configuration is
        the gate. See `routers/auth.py::signup`.
    """

    DISABLED = "disabled"
    ALWAYS_ON = "always_on"
    ORG_SPECIFIED = "org_specified"


class ExternalUserPolicy(str, enum.Enum):
    """Whether and how a project admin may add someone to a project by typing an email address that is not
    already an organisation member (`Organization.external_user_policy`).

    DISABLED (default): The project user picker shows only existing org members; no email-based add and no
        invites.
    ORG_DOMAIN_ONLY: An email matching an existing account anywhere in the system can be added directly
        (granting org membership, C-U-02). A not-yet-registered email can be invited only if its domain
        matches `Organization.auto_accept_email_domain`.
    ANYONE: As ORG_DOMAIN_ONLY, and a not-yet-registered email of any domain can be invited.
    """

    DISABLED = "disabled"
    ORG_DOMAIN_ONLY = "org_domain_only"
    ANYONE = "anyone"


class PrincipalType(str, enum.Enum):
    """What a principal reference (`services.principals`) points at: a login or a group. A closed core set;
    a module declares which of its columns hold a principal (`ModuleDefinition.principal_references`) and
    never adds a value.

    ORG_GROUP is an `OrgGroup`; PROJECT_GROUP is a `ProjectGroup` and is only
    valid for a record inside that group's own project.
    """

    USER = "user"
    ORG_GROUP = "org_group"
    PROJECT_GROUP = "project_group"
