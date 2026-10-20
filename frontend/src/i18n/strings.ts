/**
 * Centralised UI string table (U-U-02): the UI must be designed to allow
 * ease of language translation. Ossa (v1) ships English only, but every
 * screen looks strings up through `t()` instead of hardcoding text inline,
 * so adding a translated locale later is a matter of adding another table
 * here (or loading one from a file) rather than touching every component.
 */

const en = {
  appName: "ReqTrackManager",
  notifications: {
    title: "Notifications",
    empty: "No notifications yet.",
    markAllRead: "Mark all read",
    viewAll: "View all notifications",
    search: "Search notifications",
    unreadOnly: "Unread only",
    markAllReadToast: "All notifications marked as read",
    preferencesTitle: "Notification preferences",
    ui: "In-app",
    email: "Email",
    toggleAll: "Toggle all",
    types: {
      project_joined: "Added to a {project}",
      stage_scoping: "{Stage} entered scoping",
      stage_review: "{Stage} entered review",
      stage_approved: "{Stage} approved",
      stage_completed: "{Stage} completed",
      change_request_submitted: "{ChangeRequest} submitted",
      stakeholder_input_requested: "Stakeholder input requested",
      change_request_approved: "{ChangeRequest} approved",
      change_request_rejected: "{ChangeRequest} rejected",
      requirements_updated: "{Requirements} updated",
      password_changed: "Password changed",
      permission_granted: "Permission granted",
      permission_revoked: "Permission revoked",
      comment_added: "New comment on a followed item",
      requirement_review_due: "{Requirement} review due",
      stage_review_auto_approved: "{Stage} review deadline passed — auto-approved",
      project_members_changed_by_org: "Project members changed by someone who is not a project manager",
      system_storage_alert: "File storage alert (server admins)",
      compliance_required_action_due_soon: "Compliance required action due soon",
      compliance_required_action_overdue: "Compliance required action overdue",
      compliance_target_date_approaching: "Compliance target date approaching",
      compliance_target_date_exceeded: "Compliance target date exceeded",
      compliance_approval_requested: "Compliance approval requested",
      compliance_assessment_rejected: "Compliance assessment rejected",
      compliance_approval_invalidated: "Compliance approval invalidated",
      compliance_review_due: "Compliance review due",
      compliance_review_overdue: "Compliance review overdue",
      compliance_evidence_expiring_soon: "Compliance evidence expiring soon",
      compliance_evidence_expired: "Compliance evidence expired",
      compliance_requirement_non_compliant: "Compliance requirement is Non-Compliant",
      compliance_standard_update_review_needed: "Compliance standard updated — review needed",
      compliance_assignment_created: "New compliance assignment",
    },
  },
  login: {
    title: "Sign in",
    email: "Email",
    password: "Password",
    submit: "Sign in",
    error: "Invalid email or password.",
    reauthRequired: "For your security, you've been signed out. Please sign in again.",
    twoFactorTitle: "Two-factor verification",
    twoFactorPrompt: "Enter the code from your authenticator app.",
    twoFactorCode: "Authentication code",
    signInWithSso: "Sign in with SSO",
    orDivider: "or",
    notProvisioned: (org: string) => `Your ${org} has not provisioned you access.`,
    signUpLink: "Sign up",
    signUpPrompt: "New here?",
  },
  userAutocomplete: {
    addExisting: (email: string, org: string) => `Add ${email} (existing account, not yet in this ${org})`,
    inviteNew: "Invite {email}",
    canInviteHint: "Not a member yet? Type their email to invite them.",
    // the members/groups directory rework — the visible badge
    // distinguishing an org-group match from a user match in the same
    // dropdown. Tightened from the original bare "Group" to "Org group"
    // when a second, similarly-named match kind was added below — bare
    // "Group" would read as ambiguous next to "Project group".
    groupBadge: "Org group",
    // the members/groups directory rework — the visible badge
    // distinguishing a project-group match (local to this one project)
    // from an org-group match (org-wide) in the same dropdown.
    projectGroupBadge: "Project group",
  },
  signup: {
    title: "Create an account",
    displayName: "Display name",
    email: "Email",
    password: "Password",
    submit: "Create account",
    error: "Could not create your account.",
    backToLogin: "Back to sign in",
    unavailable: "Public sign-up is not available for this deployment.",
    orgSpecifiedHint: (orgPlural: string) => `Sign-up is open to email addresses from participating ${orgPlural.toLowerCase()} only.`,
    invitePrompt: "You've been invited — complete your account below.",
  },
  nav: {
    projects: "{Projects}",
    overview: "Overview",
    requirements: "{Requirements}",
    changeRequests: "{ChangeRequests}",
    actions: "Actions",
    admin: "{Project} admin",
    reports: "Reports",
    projectSectionLabel: "{Project}",
    preferences: "Preferences",
    signOut: "Sign out",
    myReviews: "My reviews due",
    myOrganizations: (orgPlural: string) => `My ${orgPlural.toLowerCase()}`,
    orgOverview: (orgCap: string) => `${orgCap} overview`,
    favourites: "Favourites",
    serverManagement: "Server management",
    help: "Help",
    helpNewTab: "Help (opens in a new tab)",
    collapseNav: "Collapse navigation",
    expandNav: "Expand navigation",
    frontendVersion: (version: string) => `App v${version}`,
    frontendBuildDetail: (sha: string, date: string) => `Commit ${sha} · built ${date}`,
    backendVersion: (version: string) => `API v${version}`,
    backendBuildDetail: (sha: string, date: string) => `Commit ${sha} · built ${date}`,
    backendVersionLoading: "API v…",
    more: "More",
    customise: {
      title: "Customise navigation",
      intro: "Choose the order of the {project} navigation and which items sit under More. Overview and {Project} admin always stay visible.",
      scopeLegend: "Apply to",
      scopeAll: "All {projects}",
      scopeProject: "Only this {project}",
      scopeReplacesOverride: "Saving for all {projects} also replaces this {project}'s own layout.",
      navigationHeading: "Navigation",
      moreHeading: "More",
      emptyMore: "Nothing here. Move rarely used items to More to tidy the rail.",
      pinned: "Always visible",
      moveUp: (label: string) => `Move ${label} up`,
      moveDown: (label: string) => `Move ${label} down`,
      moveToMore: (label: string) => `Move ${label} to More`,
      moveToNavigation: (label: string) => `Move ${label} to navigation`,
      resetToDefault: "Reset to default",
      removeOverride: "Remove this {project}'s own layout",
      save: "Save",
      saved: "Navigation saved",
      overrideRemoved: "This {project}'s own layout removed",
      saveFailed: "Couldn't save your navigation layout.",
    },
  },
  projects: {
    title: "{Projects}",
    active: "Active",
    archived: "Archived",
    search: "Search {projects}",
    newProject: "New {project}",
    useTemplate: "Create from template",
    noTemplate: "None (blank {project})",
    name: "Name",
    code: "Code",
    codeHint: (rule: string) => `Qualifies record codes, for example ${"ACME"}-REQ-001. ${rule}.`,
    codeEditHint: (rule: string) => `${rule}. Changing it breaks references that quote the old code.`,
    codeFixedHint: "Assigned automatically; your organisation administrator can change how codes are assigned.",
    codeAutomatic: "The code is assigned automatically from the name.",
    summary: "Summary",
    stage: "Current {stage}",
    roles: "Your roles",
    updated: "Last updated",
    empty: "No {projects} to show.",
    favorite: "Favourite",
    unfavorite: "Remove from favourites",
    favouritesOnly: "Favourites only",
    allRoles: "All roles",
    stageStatusLabel: "{Stage} status",
    allStages: "All {stage} statuses",
    allOrganisations: (orgPlural: string) => `All ${orgPlural.toLowerCase()}`,
    requirementCount: "{Requirements}",
    organisation: (orgCap: string) => orgCap,
    importFromBundle: "Or import from an exported {project} bundle (.zip)",
    importWarnings: "Imported with warnings",
    created: "{Project} created",
    // Small usability fix: picking an import file used to silently hide the
    // template picker with no explanation — this note replaces it instead.
    importIgnoresTemplate: "A bundle brings its own structure, so template selection doesn't apply once a file is chosen above.",
    // Hierarchical projects (docs/decisions.md).
    childOf: "Child of:",
    parentOf: "Parent of:",
    viewAll: "view all",
    parentProject: "Parent {project}",
    noParent: "None (top-level {project})",
    inheritFromParent: "Inherit access from parent",
    inheritModeFilterRole: "Role to mirror",
    addSubProject: "Add sub-{project}",
    treeView: "Tree view",
    inheritConfirmTitle: "Enable access inheritance?",
    inheritConfirmMirrorAll: (parentName: string) =>
      `Anyone who holds any role on '${parentName}' will also hold that same role on this {project}. Managers of this {project} will also be able to see who those people are and which role they hold on '${parentName}'.`,
    inheritConfirmMirrorRole: (parentName: string, role: string) =>
      `Anyone who is '${role}' on '${parentName}' will also be '${role}' on this {project}. Managers of this {project} will also be able to see who those people are.`,
    inheritConfirmButton: "Enable inheritance",
  },
  overview: {
    title: "{Project} overview",
    requirementCount: "{Requirements}",
    percentComplete: "% Completed",
    crProposed: "{ChangeRequests} proposed",
    crApproved: "{ChangeRequests} approved",
    crRejected: "{ChangeRequests} rejected",
    fileCount: "Files",
    requirementsByStatus: "{Requirements} by status",
    changeRequestsChart: "{ChangeRequests}",
    stageProgress: "{Stage} progress",
    projectActivity: "{Project} activity",
  },
  requirements: {
    title: "{Requirements}",
    recordLabel: "{Requirement}",
    newRequirement: "New {requirement}",
    importFromCsv: "Import from CSV",
    search: "Search by name or ID",
    name: "Name",
    reasoning: "Reasoning",
    description: "Description",
    clarification: "Clarification",
    component: "{Component}",
    category: "{Category}",
    allCategories: "All {categories}",
    status: "Status",
    owner: "Owner",
    ownerDefaultsToYou: "Defaults to you",
    keywords: "Keywords",
    locked: "Locked (approved)",
    lockedNotice: "use a {changeRequest} to modify",
    archive: "Archive",
    archiveTitle: "Archive this {requirement}?",
    archiveConfirm: "It moves out of the active list, but its history and links are kept.",
    archived: "{Requirement} archived",
    archivedBadge: "Archived",
    includeArchived: "Include archived",
    // No `ConfirmDialog` here, unlike Archive: mirrors `ProjectAdminPage.tsx`'s
    // existing unarchive button, which also fires immediately — restoring is
    // reversible again (archive it right back), unlike the Tier-1-confirmed
    // archive action itself.
    restore: "Restore",
    restored: "{Requirement} restored",
    save: "Save",
    changeNote: "Reason for change",
    when: "When",
    // The requirement's own version ledger (a body section); what happened to it is the aside's
    // Activity tab (`strings.recordActivity`).
    versions: "Versions",
    discussion: "Discussion",
    addComment: "Add comment",
    actionsSection: "Actions",
    linkExistingAction: "Link existing action",
    selectAnActionToLink: "Select an action…",
    createAndLinkAction: "Create and link a new action",
    unlinkAction: "Unlink",
    unlinkActionTitle: "Unlink this action?",
    unlinkActionConfirm: "The action itself isn't affected — it just stops appearing on this {requirement}'s Actions card.",
    // `unlink_action` previously had no
    // lock check at all, an asymmetry with the already-gated add side;
    // unconditional across every {project}, unlike the
    // traceability-link strings above.
    unlinkActionViaChangeRequestTitle: "Unlink this action via change request?",
    unlinkActionViaChangeRequestConfirm:
      "This {requirement} is approved — unlinking an action requires a change request. The action itself isn't affected either way; it just stops appearing on this {requirement}'s Actions card once approved.",
    noLinkedActions: "No actions linked yet.",
    attachments: "Attachments",
    subscribe: "Subscribe",
    unsubscribe: "Unsubscribe",
    subscribed: "Subscribed",
    reactionToggle: "Like this comment",
    editedLabel: "(edited)",
    editComment: "Edit",
    saveComment: "Save",
    cancelEdit: "Cancel",
    attachFile: "Attach a file",
    removeAttachment: "Remove attachment",
    approve: "Approve",
    approved: "{Requirement} approved",
    markCompleted: "Mark completed",
    unmarkCompleted: "Revert completion",
    completed: "{Requirement} marked completed",
    completionReverted: "Completion reverted",
    // C-G-11 overlay-marker badge, distinct from the lifecycle status badge
    // (which stays "Approved" for a completed {requirement}).
    completedBadge: "Completed",
    completedFilter: "Completed",
    reviewSection: "Review scheduling",
    reviewDate: "Review date",
    reviewLeadDays: "Reminder lead time (days)",
    reviewer: "Assigned reviewer",
    reviewNone: "No review scheduled",
    reviewDue: "Review due",
    recordReviewOutcome: "Record review outcome",
    reviewOutcomeMet: "Met",
    reviewOutcomeFailed: "Failed",
    reviewComment: "Comment",
    reviewCommentRequiredOnFail: "A comment is required when the outcome is Failed.",
    submitReview: "Submit review",
    empty: "No {requirements} to show.",
    noComponentsOrCategories: "This {project} has no {components} or {categories} yet.",
    configureComponentsFirst: "Add one in {Project} Admin before creating {requirements}.",
    noCategoriesForComponent: "No {categories} under this {component} yet — add one in {Project} Admin.",
    makeChangeRequest: "Make {changeRequest}",
    changedBy: "Changed by",
    targetVersion: "Target version",
    level: "Level",
    attachmentsLockedNotice: "This {requirement} is approved — new attachments must be added via a {changeRequest}.",
    created: "{Requirement} created",
    // Create-modal step 2 (UX review: attach files during creation, not only
    // afterwards from the detail page). Links are chosen in step 1.
    attachFilesAndLinks: "Attach files",
    createAndAttach: "Create & attach files",
    finish: "Finish",
    // Bulk operations (list/table view only) — style guide "Pattern: bulk
    // operations on a list". `bulkSelectRow`/`bulkSelectAll` label the
    // checkbox column (accessible-name parity with the reorder buttons'
    // existing aria-label convention); the `bulk*Title`/`bulk*Confirm`
    // pairs follow the same split as the single-row `archiveTitle`/
    // `archiveConfirm` above, just pluralised and count-bearing.
    bulkSelectAll: "Select all",
    bulkSelectRow: (label: string) => `Select ${label}`,
    bulkSelectedCount: (n: number) => `${n} selected`,
    bulkClearSelection: "Clear selection",
    bulkArchiveSelected: "Archive selected",
    bulkArchiveTitle: (n: number) => `Archive ${n} {requirements}?`,
    bulkArchiveConfirm: "They move out of the active list, but their history and links are kept.",
    bulkMoveToStage: "Move to stage",
    bulkTagSelected: "Tag selected",
    bulkTagTitle: (count: number) => `Tag ${count} selected ${count === 1 ? "requirement" : "requirements"}`,
    bulkMoveApply: "Move",
    bulkMoveTitle: (n: number, stageName: string) => `Move ${n} {requirements} to "${stageName}"?`,
    bulkMoveConfirm: "Their target {stage} changes immediately.",
    bulkResultSuccess: (n: number) => `${n} updated`,
    bulkResultPartial: (n: number, failed: number) => `${n} updated, ${failed} failed`,
  },
  watchers: {
    title: "Watching groups",
    explanation: "Everyone in these groups who can view this project is told about new comments.",
    none: "No group is watching.",
    add: "Add a group…",
    added: "Watching group added.",
    removed: "Watching group removed.",
    addFailed: "Could not add the group.",
    removeFailed: "Could not remove the group.",
    stopWatching: "Stop watching",
  },
  reviews: {
    projectTitle: "{Requirements} due for review",
    myTitle: "My reviews due",
    empty: "Nothing due for review.",
    reviewDate: "Review date",
    reviewer: "Reviewer",
    unassigned: "Unassigned",
    allComponents: "All {components}",
    allReviewers: "All reviewers",
    assignedToMe: "Assigned to me or my groups",
  },
  changeRequests: {
    title: "{ChangeRequests}",
    // Matches proposed name, reason, and the target requirement's name/ID.
    search: "Search by name, reason or {requirement} ID",
    newChangeRequest: "New {changeRequest}",
    kindNew: "New {requirement}",
    kindModify: "Modify {requirement}",
    kindAddAction: "Add action",
    proposedAddAction: "Proposed action",
    proposedLinkAction: "Linking existing action",
    // REMOVE_ACTION/ADD_LINK/REMOVE_LINK
    // change requests, rendered in `ChangeRequestDetailPage.tsx` the same
    // way ADD_ACTION's two labels above are.
    proposedRemoveAction: "Removing this action",
    proposedAddLink: "Proposed link",
    proposedRemoveLink: "Removing this link",
    // Links proposed on a request, merged on approval.
    proposedLinks: "Proposed links",
    proposedLinksHelp: "Created only when this {changeRequest} is approved; the approver chooses which to merge.",
    proposedLinksEditorHelp: "Optionally propose links for this {requirement}. They are created only if the approver merges them.",
    noProposedLinks: "No links proposed.",
    addProposedLink: "Add a link",
    removeProposedLinkLabel: (phrase: string, target: string) => `Remove proposed link: ${phrase} ${target}`,
    hiddenRecord: "A record you cannot see",
    approveDialogTitle: "Approve {changeRequest}",
    approveDialogIntro:
      "Choose which of the proposed links to merge. A link that cannot be merged now is shown with the reason and is left out.",
    previewLoading: "Checking the proposed links…",
    previewFailed: "Could not check the proposed links.",
    selectAllLinks: "Select all",
    selectNoLinks: "Select none",
    alreadyLinked: "Already linked, will be skipped",
    mergeLinkLabel: (phrase: string, target: string) => `Merge link: ${phrase} ${target}`,
    approveMergeLinks: (count: number) => `Approve and merge ${count} link${count === 1 ? "" : "s"}`,
    approveWithoutLinks: "Approve without links",
    appliesNothingNotice:
      "No links are selected, and this {changeRequest} proposes nothing else, so approving it changes nothing. Use Reject to decline it.",
    linksChangedNotice: "The list was updated. Review it and approve again.",
    reason: "Reason for change",
    submit: "Submit",
    withdraw: "Withdraw",
    approve: "Approve",
    // C-G-11: shown alongside plain "Approve" only when the target
    // {requirement} is currently completed — an explicit, opt-in second
    // action for the approver, distinct from the default carry-forward
    // behaviour a plain Approve keeps.
    approveAndClearCompletion: "Approve and clear completion",
    reject: "Reject",
    decisionNote: "Decision note",
    status: "Status",
    proposedName: "Proposed name",
    proposedReasoning: "Proposed reasoning",
    tasks: "Tasks",
    newTask: "New task",
    taskDescription: "Description",
    taskAssignee: "Assignee",
    taskDueDate: "Due date",
    taskDone: "Done",
    votes: "Stakeholder votes",
    voteApprove: "Vote to approve",
    voteReject: "Vote to reject",
    yourVote: "Your vote",
    voteComment: "Comment",
    voteApproveCount: "approve",
    voteRejectCount: "reject",
    votingAdvisoryNotice: "Advisory only — does not change the manager's decision.",
    empty: "No {changeRequests} to show.",
    fieldsToChange: "Fields to change",
    fieldsToChangeHint: "Select which fields this {changeRequest} proposes to change — values are pre-filled from the {requirement}'s current content. Unselected fields are left untouched when approved.",
    selectARequirement: "Select a {requirement}",
    // A modify {changeRequest} can only target an already-approved
    // {requirement} — a
    // still-draft/reviewed one is edited directly instead.
    noLockableRequirements: "No {requirements} are approved yet — approve one first, or edit a draft {requirement} directly.",
    selectAtLeastOneField: "Select at least one field to change.",
    attachments: "Attachments",
    selectAttachment: (org: string) => `Select from ${org} resources`,
    noAttachmentsAvailable: (org: string, orgCap: string) =>
      `No ${org} resources uploaded yet — upload one from ${orgCap} Admin first.`,
    viewComments: "View comments",
    voteComments: "Vote comments",
    noVoteComments: "No comments were left with any vote.",
    defaultTarget: "Default (first {stage})",
    created: "{ChangeRequest} created",
    submittedToast: "{ChangeRequest} submitted",
    withdrawnToast: "{ChangeRequest} withdrawn",
    approvedToast: "{ChangeRequest} approved",
    rejectedToast: "{ChangeRequest} rejected",
  },
  admin: {
    settings: "{Project} settings",
    // Resource-menu aria-label, matching Org Admin's `orgAdmin.sectionsNav`
    // — Project Admin converted from Tabs to ResourceMenu for cross-page
    // consistency with the other admin-tier pages (docs/decisions.md).
    sectionsNav: "{Project} admin sections",
    name: "Name",
    summary: "Summary",
    allowMemberChangeRequests: "Allow members to submit {changeRequests}",
    // When the organisation's own
    // `force_require_change_request_for_approved_links` is active and this
    // {project} isn't exempt, this checkbox renders checked-and-disabled
    // (the `disabled`+`title` "why is this checked and I can't touch it"
    // convention `ProjectMembersTable.tsx` already establishes) with the
    // Forced hint below explaining why, rather than silently ignoring the
    // {project}'s own (irrelevant, in that case) stored value.
    requireChangeRequestForApprovedLinks: "Require a change request to add/remove links on approved {requirements}",
    requireChangeRequestForApprovedLinksHint:
      "Once a {requirement} is approved, adding or removing a traceability link requires a change request instead of the direct action. Off by default — turn on for {projects} where links themselves need review once a {requirement} is locked.",
    requireChangeRequestForApprovedLinksForcedByOrg:
      "Required by this organisation's policy — see Org Admin's Advanced settings. Mark this {project} exempt below to opt it out.",
    exemptFromOrgLinkLock: "Exempt this {project} from the organisation's change-request-for-links policy",
    exemptFromOrgLinkLockHint:
      "This organisation requires every {project} to gate link changes on an approved {requirement} behind a change request. Checking this opts this {project} out, falling back to its own setting above.",
    // AI approval via MCP (docs/decisions.md). Both this AND the
    // organisation's own toggle (Org Admin's Advanced settings) must be on
    // for an AI assistant acting through the MCP server to approve,
    // decide, or complete anything in this {project} — see
    // orgAdmin.allowAiApprovals's own comment for the org-level half.
    allowAiApprovals: "Allow AI approval via MCP for this {project}",
    allowAiApprovalsHint:
      "Also requires AI approval to be enabled for this {project}'s organisation (Org Admin's Advanced settings). Off by default.",
    allowAiApprovalsAckTitle: "Allow AI approval for this {project}?",
    allowAiApprovalsAckBody:
      "Approvals made by an AI assistant through the MCP server are not necessarily a deliberate, in-the-moment decision by a human reviewer, and may weaken the accountability this approval workflow is meant to represent.",
    allowAiApprovalsAckCheckbox: "I understand this and want to allow it for this {project} anyway.",
    allowAiApprovalsAckConfirm: "Allow AI approval",
    isTemplate: "Usable as a {project} template",
    // Hierarchical projects (docs/decisions.md): opt-in eligibility gate —
    // other {projects}' managers can only select this one as a parent once
    // this is enabled.
    canBeParent: "Allow this {project} to be a parent",
    canBeParentHint: "Other {projects} can only be nested under this one once this is enabled.",
    visibility: "Visibility",
    visibilityOnlySpecified: "Only specified",
    visibilityOrgWide: "Org-wide visibility",
    visibilityHint: (org: string) =>
      `"Org-wide visibility" gives every ${org} member automatic view access to this {project}, without an explicit assignment — manager/administrator/stakeholder roles still require one.`,
    projectStatus: "Status",
    saveSettings: "Save settings",
    // Hierarchical projects (docs/decisions.md).
    memberSources: "Member sources",
    memberSourcesHint: "Other {projects} in this organisation this {project} consumes members from — anyone with a role there gets access here, per the mode chosen for each source.",
    addMemberSource: "Add",
    removeMemberSource: "Remove",
    noChildrenToAdd: "No other {projects} available to add.",
    memberSourceModeRole: (role: string) => `Mirrors ${role}`,
    memberSourceProjectSelect: "Source {project}",
    memberSourceModeSelect: "Mirror mode",
    memberSourceFilterRoleSelect: "Mirrored role",
    projectReferenceSelect: "Referenced {project}",
    // Effective-members-derived "Members" section heading/hint — since default project groups no
    // longer exist, no title collision risk remains with a
    // group literally named "Members" the way there once was.
    effectiveMembers: "Members",
    effectiveMembersHint: "Everyone with access to this {project}, direct or inherited — add, edit, and invite from this one table.",
    materializeAll: "Convert all inherited access to direct roles",
    materializedCount: (n: number) => (n === 0 ? "Nothing to convert — no inherited access to make direct." : `Converted ${n} ${n === 1 ? "user" : "users"} to direct roles.`),
    email: "Email",
    terminology: "Terminology",
    terminologyHint: "Override how these terms are labelled in this {project}'s UI. Leave blank to use the default.",
    // Row labels for the terminology-override list above — one per
    // `TERMINOLOGY_KEYS` entry (`ProjectAdminPage.tsx`). Previously derived
    // from the raw key via CSS `text-transform: capitalize` + a manual
    // `.replace("_", " ")` rather than a real label map — exactly the
    // pattern this repo's own rule on rendering enum/derived-string values
    // forbids (a sibling element two lines away already does this
    // correctly for role/status values). A plain literal label map, not
    // run through the `{project}`-style terminology-substitution system:
    // these rows *are* the canonical default term names being configured,
    // so substituting them through the not-yet-applied override they name
    // would be circular.
    terminologyKeyLabel: {
      project: "Project",
      stage: "Stage",
      component: "Component",
      category: "Category",
      requirement: "Requirement",
      change_request: "Change Request",
    } as Record<"project" | "stage" | "component" | "category" | "requirement" | "change_request", string>,
    // Distinct from `saveSettings` only because Terminology's Save button
    // now shares a screen with Overview's own "Save settings" button
    // — two identically-labelled
    // buttons on one view is an accessible-naming collision (style guide
    // Principle 8), not just a test-locator inconvenience.
    saveTerminology: "Save terminology",
    archiveProject: "Archive {project}",
    unarchiveProject: "Unarchive {project}",
    exportProject: "Export {project} bundle",
    exportProjectHint: (org: string) =>
      `Downloads a self-contained .zip with this {project}'s structure, full {requirement}/{changeRequest} history, and attachments — re-importable as a new {project} from the {Projects} page, in this ${org} or a different one.`,
    customFields: "Custom fields",
    newCustomField: "New field",
    reportSetup: "Report Setup",
    reportContent: "Report content",
    // Distinct wording from `defaultReportTemplate` (the field's own
    // label, kept as-is for accessibility) deliberately — an identical
    // CollapsibleSection title would make its own aria-label ("Default
    // report template section") a substring match for `getByLabel`
    // queries targeting the field itself, a real ambiguity, not just an
    // accessible-naming nicety.
    defaultTemplateSection: "Default template",
    // Project Admin's own
    // "Modules" tab: a project's whole-module enablement override and,
    // for a module with sub-components, its own per-sub-component
    // override — one level below Org Admin's `orgAdmin.modules*` (which
    // sets the organisation's own default rather than one project's
    // override of it).
    modulesNav: "Modules",
    tagsNav: "Tags",
    modulesDescription:
      "Turn modules on or off for this {project}. New {project}s start with the organisation's defaults; later changes to those defaults don't affect existing {project}s.",
    modulesEmpty: "No modules are registered on this deployment yet.",
    moduleToggleLabel: (name: string) => `Enable ${name} for this {project}`,
    moduleEnabledToast: (name: string) => `${name} enabled for this {project}`,
    moduleDisabledToast: (name: string) => `${name} disabled for this {project}`,
    moduleOrgDefaultHint: (on: boolean) => `Organisation default for new {project}s: ${on ? "on" : "off"}`,
    moduleSubComponentToggleLabel: (moduleName: string, subComponentName: string) =>
      `Enable ${subComponentName} (${moduleName}) for this {project}`,
    moduleSubComponentEnabledToast: (name: string) => `${name} enabled for this {project}`,
    moduleSubComponentDisabledToast: (name: string) => `${name} disabled for this {project}`,
    moduleSubComponentsSummary: (count: number, onCount: number) =>
      `${count} component${count === 1 ? "" : "s"} · ${onCount === count ? "all on" : `${onCount} on`}`,
    structure: "Structure",
    fieldsAndActions: "Fields & actions",
    stages: "{Project} stages",
    startReview: "Start review",
    approveStage: "Approve {stage}",
    completeStage: "Mark {stage} completed",
    cascadeToRequirements: "Also mark this {stage}'s approved {requirements} as completed",
    setReviewDeadline: "Set review deadline",
    reviewDeadline: "Review deadline",
    clearDeadline: "Clear deadline",
    respondApprove: "Approve",
    respondReject: "Reject",
    stageCompletedAt: "Completed",
    reportTemplates: "Report templates",
    newReportTemplate: "New template",
    editReportTemplate: "Edit template",
    templateName: "Name",
    accentColor: "Accent colour",
    includeCoverPage: "Include cover page",
    includeLogo: (org: string) => `Include ${org} logo`,
    footerText: "Footer text",
    templateContentHint: (org: string) =>
      `Optional. When set for a report type, this overrides the {project}'s own (or ${org} default) introduction, chapters and appendices for any report of that type generated using this template — leave a report type blank to keep using the {project}'s own content.`,
    templateContent: "Report content",
    reportDefaults: "Report Defaults",
    reportDefaultsHint: (org: string) =>
      `Used as the default introduction, chapters and appendices, per report type, for any {project} in this ${org} that — and whose parent {projects} — haven't set their own. See each {project}'s Report Setup tab.`,
    reportSetupHint:
      "The introduction, chapters and appendices below are used as the default for each report type generated for this {project}, unless overridden when generating. A report type with nothing here uses its parent {project}'s, then the organisation's.",
    templateChaptersPerComponent: "Chapter per {component} by default",
    defaultReportTemplate: "Default report template",
    defaultReportTemplateHint: "Pre-selected on this {project}'s report generation page — a user can still pick a different template, or none, for a specific report.",
    components: "{Components}",
    componentsAndCategories: "{Components} & {categories}",
    componentTreeHint: "{Categories} are nested under one {component} each. A {requirement}'s identifier combines its {component}'s and {category}'s prefixes, e.g. SW-PERF-014.",
    categories: "{Categories}",
    groups: "{Project} groups",
    searchGroups: "Search by name",
    noGroupsFound: "No groups match this search.",
    newGroup: "New group",
    groupNamePlaceholder: "e.g. Reviewers",
    groupRole: "Role",
    // the members/groups directory rework — the Groups tab's
    // per-row `MultiSelectDropdown` and the group's own `SidePanel` role
    // editor share these two: the dropdown's accessible name/title, and its
    // closed-state summary when the group holds no role at all yet.
    groupRolesFor: (name: string) => `${name}'s roles`,
    noRolesAssigned: "No roles assigned",
    // Column header for the `DirectoryTable` row-count column — distinct from `memberCount(n)`
    // below, which renders the actual "N member(s)" cell content.
    groupMembersColumn: "Members",
    groupCreated: "Group created",
    // the members/groups directory rework — the Groups tab's
    // `DirectoryTable` now mixes two row kinds (a real `ProjectGroup` and a
    // `ProjectMemberSource`, moved here from the Overview tab); this column
    // and its two badge values are what tells them apart. "Project" (not
    // "Org group") for a member-source row is deliberate — it names another
    // whole {project} this one mirrors members *from*, not an org group —
    // see docs/ux-style-guide.md's "Pattern: type-badged mixed rows in a
    // single directory".
    groupTypeColumn: "Type",
    groupTypeBadgeGroup: "{Project} group",
    groupTypeBadgeMemberSource: "{Project}",
    addMember: "Add member",
    addMemberPlaceholder: "Type a name or email to add…",
    addOrInviteMemberPlaceholder: "Type a name to add, or an email to invite…",
    // the members/groups directory rework: the "Add member"
    // modal's autocomplete also matches this project's own groups
    // (`UserAutocomplete`'s `projectGroups` prop) — picking one switches
    // the same modal into this second step instead of granting a role
    // directly, since a project group's roles are separate, possibly-zero,
    // possibly-multiple grants unaffected by who joins it.
    addMemberToGroupTitle: (groupName: string) => `Add to "${groupName}"`,
    addMemberToGroupHint: (groupName: string) =>
      `Adding someone here makes them a member of "${groupName}" — it does not grant a role by itself. The group's own role(s), if any, apply to everyone in it.`,
    // `AddMembersModal` (staged multi-add, replacing the old immediate-
    // submit-per-selection flow both `OrgAdminPage.tsx` and
    // `ProjectAdminPage.tsx` used to hand-roll) — the empty-staged-list
    // hint and the per-row controls' accessible names.
    addMembersStagedEmpty: 'Search above to add people — nothing is granted until you press "Add member(s)".',
    roleForStagedMember: (label: string) => `Role for ${label}`,
    removeStagedMember: (label: string) => `Remove ${label}`,
    addSelectedMembers: (n: number) => (n === 0 ? "Add member(s)" : `Add ${n} member${n === 1 ? "" : "s"}`),
    externalAddedDirectly: (email: string, role: string, org: string) =>
      `${email} was added directly to the {project} with the '${role}' role (not to this specific group, since they weren't already an ${org} member).`,
    externalInvited: (email: string, role: string) =>
      `An invite email was sent to ${email}. They'll get the '${role}' role once they sign up.`,
    externalSsoProvisioned: (email: string, role: string) =>
      `${email} was added and will get the '${role}' role next time they sign in via SSO.`,
    externalAddError: "Could not add this user.",
    memberCount: (n: number) => `${n} member(s)`,
    // Pending invites (docs/decisions.md): originally their own
    // small, self-contained section (`components/PendingInvitesSection.tsx`)
    // — folded into the unified `ProjectMembersTable` as a per-row status
    // instead — these four
    // "Resend" strings are still shared with Org Admin's own org-level
    // resend flow, so they stay here rather than
    // moving into `membersTable`'s own namespace.
    resendInvite: "Resend",
    resendInviteAria: (email: string) => `Resend invite to ${email}`,
    resendInviteSuccess: (email: string) => `Invite resent to ${email}.`,
    resendInviteError: "Could not resend this invite.",
    viaOrgGroup: (name: string, org: string) => `${name} (${org} group)`,
    addOrgGroupToProjectGroup: (org: string) => `Nest an ${org} group…`,
    viaProjectMembers: (name: string) => `${name}'s members`,
    addProjectReferenceToProjectGroup: "Reference another {project}'s members…",
    newComponent: "New {component}",
    newCategory: "New {category}",
    newStage: "New {stage}",
    prefix: "Prefix",
    userId: "User ID",
    optionsCommaSeparated: "Options (comma separated)",
    fieldName: "Field name",
    fieldAppliesTo: "Applies to",
    fieldTypeLabel: "Field type",
    required: "required",
    entityKindRequirement: "{Requirement}",
    entityKindChangeRequest: "{ChangeRequest}",
    fieldTypeShortText: "Short text",
    fieldTypeLongText: "Long text",
    fieldTypeCheckbox: "Checkbox",
    fieldTypeList: "List",
    rename: "Rename",
    delete: "Delete",
    deleteStage: "Delete this {stage}",
    deleteComponent: "Delete this {component}",
    deleteCategory: "Delete this {category}",
    deleteLastOneHint: "This is the only one — create another first so there's something to reassign to.",
    deleteMinItemsHint: (n: number) => `At least ${n} are required — add another before deleting this one.`,
    deleteComponentHasCategoriesHint: "Delete or reassign this {component}'s {categories} first.",
    reassignExistingTo: "Reassign existing items to",
    confirmDelete: "Confirm delete",
    deleteComponentConfirm: (name: string) => `Delete the component "${name}"? This cannot be undone.`,
    deleteInUseTitle: (name: string) => `Delete “${name}”?`,
    deleteStageReassignSummary: "Every {requirement} and pending {changeRequest} targeting this {stage} moves to the one you choose, with its full history.",
    deleteCategoryReassignSummary: "Every {requirement} in this {category} moves to the one you choose.",
    deleteInUseMoveHeading: "Move what uses it to another one",
    deleteInUseMoveHint: "Everything that uses it is switched to the one you choose, then it is deleted.",
    deleteInUseNoCandidates: "There is nothing to move them to — create another first.",
    deleteInUseCandidateBlocked: (label: string, reason: string) => `${label} (cannot be used: ${reason})`,
    deleteInUseRemoveHeading: "Or delete what uses it too",
    deleteInUseRemoveButton: "Delete the links too…",
    deleteInUseRemoveBlockedPrefix: "Not available: ",
    deleteInUseKeepButton: "Delete and keep it for the other projects",
    actionTypes: "Action types",
    newActionType: "New action type",
    deleteActionType: "Delete this action type",
    removeMember: (name: string) => `Remove ${name}`,
    removeNestedGroup: (label: string) => `Remove ${label}`,
    deleteCustomField: (name: string) => `Delete ${name}`,
    deleteCustomFieldConfirm: (name: string) => `This removes the "${name}" field and its values from every {requirement}/{changeRequest} that has it set. This cannot be undone.`,
    // (docs/decisions.md): "Members" split out of the old combined
    // "Project groups" tab into its own resource-menu section. Rebuilt
    // again: the editable
    // users+groups table, the effective-members audit table, and pending
    // invites — three sections doing one job — became the single unified
    // `ProjectMembersTable` (`components/ProjectMembersTable.tsx`).
    membersNav: "Members",
    // "Groups" keeps `groups`/`newGroup`/`searchGroups`/`groupCreated`
    // above for its own heading/create-modal copy — these are its
    // SidePanel-specific additions.
    groupDetails: (name: string) => `${name} details`,
    groupRoleAtTop: "Group role",
    deleteGroup: "Delete group",
    deleteGroupTitle: (name: string) => `Delete "${name}"?`,
    deleteGroupMessage: "This removes the group and every membership under it. Direct roles and other groups' memberships are unaffected. This cannot be undone.",
    groupDeleted: "Group deleted",
    groupInUseSummary: (name: string, listing: string) => `“${name}” is still named on ${listing}.`,
    groupInUseMoveHeading: "Hand them to someone else",
    groupInUseMoveHint: "Everything that names this group moves to the person or group you choose, then the group is deleted.",
    groupInUseReplacement: "New owner",
    groupInUseClear: "Clear",
    groupInUseClearHeading: "Or leave them empty",
    groupInUseClearButton: "Clear them and delete…",
    groupInUseClearDescription: "Optional fields that name this group are left empty. Required fields cannot be cleared.",
    groupInUseClearBlocked: "Some of these fields are required, so a replacement is needed.",
    groupInUseClearConfirm: (name: string) => `Type the group's name to delete “${name}” and leave the optional fields empty.`,
    // member_source_project_ids groups — extends the existing
    // `viaProjectMembers` line with a link to the referenced {project}'s
    // own new Members page and a clarifying sentence that this isn't a
    // fixed list (`docs/ux-style-guide.md`'s addendum).
    viaProjectMembersLinkLabel: "View members",
    viaProjectMembersHint: "Live — always mirrors that {project}'s own current direct members, not a fixed list captured at the time it was added.",
  },
  membersTable: {
    // frontend/src/components/ProjectMembersTable.tsx — the unified
    // "effective members, editable, with pending invites folded in" table
    // (docs/decisions.md) that
    // replaced `MemberRoleTable`/`PendingInvitesSection`: one call site on
    // Project Admin's own "Members" section (`ProjectAdminPage.tsx`), one
    // inside Org Admin's "Manage users" modal (`OrgAdminPage.tsx`).
    // Deliberately its own top-level namespace, not nested under `admin`/
    // `orgAdmin`, since both pages share this exact copy verbatim — the
    // same reasoning `MemberRoleTable`'s own now-retired namespace had.
    name: "Name",
    email: "Email",
    role: "Role",
    source: "Source",
    search: "Search by name or email",
    noResults: "No members or invites match this search/filter.",
    empty: "No members yet.",
    rolesFor: (name: string) => `${name}'s roles`,
    noRoles: "No roles",
    grantRole: (role: string, name: string) => `Grant ${role} to ${name}`,
    revokeRole: (role: string, name: string) => `Revoke ${role} from ${name}`,
    // Client-side hint only — a fast approximation of C-U-08 ("a project
    // must always have at least one manager"), sourced from `direct_role`-
    // kind entries only (the `kind` split — see `MemberSourceProvenanceKind`'s
    // own doc comment), not the old collapsed `direct` bucket, since a
    // manager whose role actually comes from a group or org-wide
    // visibility would otherwise misreport here. The backend guard
    // (`DELETE .../roles/{user_id}/{role}`) is authoritative either way,
    // so this can be wrong in edge cases (e.g. a manager inherited from a
    // parent {project}) without being unsafe.
    cannotRemoveLastManager: "This is the {project}'s only manager source — add another manager first.",
    // Shown (checked, disabled) for a role option whose *only* source is
    // not a genuine direct grant — a group, nested org group, project
    // reference, or org-wide visibility. `DELETE .../roles/{user_id}/{role}`
    // only ever deletes a `UserProjectRole` row, so this role isn't
    // togglable from here at all; it must be changed at its actual source
    // (the group's own membership/role, the project's visibility setting).
    roleNotDirectlyRevocable: "This role isn't a direct grant on this {project} — it comes from a group, nested org group, project reference, or org-wide visibility. Change it at that source instead.",
    // Appended inline to a checked-but-disabled role option's own label (not
    // just its hover `title` above) so the reason it's greyed out is
    // visible without hovering — platform review 2026-09 follow-up.
    // Deliberately one generic suffix covering every non-`direct_role`
    // kind (group, nested org group, project reference, org-wide,
    // inherited), same simplification the Source-column summary below
    // makes; the precise mechanism stays one hover away via
    // `roleNotDirectlyRevocable` above, unchanged.
    roleByGroupSuffix: "(by group)",
    // Same inline-suffix treatment for the other disabled reason (see
    // `cannotRemoveLastManager` below) — a purely-direct
    // `project_manager` role that can't be revoked because it's the
    // {project}'s last manager, not because it's group-sourced.
    roleOnlyManagerSuffix: "(only manager)",
    add: "Add",
    // Whole-row Source-column summary (platform review 2026-09 follow-up)
    // — replaces the old always-visible per-role provenance lines below
    // with one plain-language word/phrase per row, since the Role column
    // already names which roles a member holds (repeating that per source
    // line was redundant): "Direct" (reused from `sourceDirectRole` below
    // when every source is `direct_role`), "Group" when every source is
    // some other (non-`direct_role`) kind, or this — a mix of both. Full
    // per-source detail (which group, which project, which mode) is not
    // lost, just moved behind the summary's own click-to-open `Popover`
    // (`sourceSummaryDetailTitle` below), reusing `sourceLine` for its
    // contents unchanged.
    sourceSummaryDirectAndGroup: "Direct and group",
    // See `sourceSummaryDirectAndGroup` above — shown when every source is
    // some non-`direct_role` kind (group, nested org group, project
    // reference, org-wide, inherited). Deliberately one umbrella word
    // rather than naming each of those five kinds at the row level; the
    // detail popover still distinguishes them.
    sourceSummaryGroup: "Group",
    sourceSummaryDetailTitle: (name: string) => `${name}'s access sources`,
    // Per-role provenance text (now shown inside the Source column's
    // detail popover rather than always-visible in the cell itself) — one
    // line per source a user holds a given role through; see
    // `MemberSourceProvenanceKind`'s own doc comment for what each of the
    // five direct kinds means.
    sourceDirectRole: "Direct",
    // Parameterized on the granting group's name (`via_group_name`) so the
    // Source column can say *which* group, not just "Via group" — see
    // `ProjectMembersTable.tsx`'s `sourceLine` for the fallback used when a
    // name is ever missing.
    sourceDirectGroup: (groupName: string) => `Via group '${groupName}'`,
    sourceDirectOrgGroup: (groupName: string) => `Via nested org group '${groupName}'`,
    // `direct_org_group_role` (the members/groups directory rework) — a genuinely different mechanism from
    // `sourceDirectOrgGroup` above (nested inside a `ProjectGroup`): the
    // org group holds this role directly, granted from the Members
    // section's own "Add member" autocomplete. Distinct wording so
    // the two don't read as the same thing.
    sourceDirectOrgGroupRole: (groupName: string) => `Via group '${groupName}' (direct)`,
    sourceDirectProjectRef: "Via project reference",
    sourceDirectOrgWide: "Org-wide visibility",
    sourceForwardInherited: (parentName: string, mode: string) => `Inherited from '${parentName}' (${mode.toLowerCase()})`,
    sourceMemberSourceInherited: (sourceName: string, mode: string) => `Via member source '${sourceName}' (${mode.toLowerCase()})`,
    // Role filter (`FilterField`, matching every other directory's own
    // role filter, e.g. Org Admin's Users table) — only show members
    // holding a given role; doesn't affect invited rows' own role.
    roleFilterLabel: "Role",
    allRoles: "All roles",
    showInvited: "Show invited",
    // Invited-row treatment, folded in from the retired
    // `PendingInvitesSection.tsx` — status badge + Resend button replace
    // the MultiSelectDropdown a real member row's Role cell would show.
    invitedSentOn: (date: string) => `Sent ${date}`,
    // Per-row Actions column (docs/decisions.md) — `ActionMenu` trigger name and its two
    // conditionally-offered items; see `ProjectMembersTable.tsx`'s own
    // eligibility rules for when each is shown.
    actionsFor: (name: string) => `${name}'s actions`,
    removeAllAccess: "Remove all access",
    removeAllAccessConfirmTitle: (name: string) => `Remove all access for ${name}?`,
    removeAllAccessConfirmMessage: (name: string) =>
      `This revokes every direct role ${name} holds on this {project}. They'll need to be re-added to regain access.`,
    removeAllAccessConfirmButton: "Remove access",
    removeAllAccessSuccess: (name: string) => `Removed all access for ${name}.`,
    convertToDirect: "Convert inherited access to direct roles",
    // Mirrors the bulk `materializedCount` messaging (`strings.admin`),
    // scoped to this one row's own outcome instead of a count.
    convertToDirectSuccess: (name: string) => `Converted ${name}'s inherited access to a direct role.`,
    convertToDirectNoOp: (name: string) => `${name} already holds an equal or higher direct role — nothing to convert.`,
    // An org group holding a
    // direct `OrgGroupProjectRole` grant on this project now gets its own
    // `kind: "group"` row instead of being visible only through a member's
    // own `direct_org_group_role` Source line. `rolesFor`/`grantRole`/
    // `revokeRole`/`actionsFor` above are already name-generic and reused
    // verbatim for a group's own name — no group-specific duplicates needed.
    groupRowBadge: "Group",
    removeGroup: "Remove group",
    removeGroupConfirmTitle: (name: string) => `Remove ${name} from this {project}?`,
    removeGroupConfirmMessage: (name: string) =>
      `This revokes every role ${name} holds on this {project}. Its members will need another way to regain access.`,
    removeGroupConfirmButton: "Remove group",
    removeGroupSuccess: (name: string) => `Removed ${name}'s access.`,
  },
  serverSettings: {
    title: "Platform branding",
    hint: (org: string) =>
      `The default accent colour, logo, and header title used on any page without a single ${org} to brand it, and as the fallback for any ${org} that hasn't set its own.`,
    accentColor: "Default accent colour",
    logo: "Default logo",
    headerTitle: "Default header title",
    headerTitleHint: "Leave blank to use the built-in product name.",
    orgLabelSingular: "Organisation label (singular)",
    orgLabelSingularHint: "Deployment-wide word used in place of \"organisation\" throughout the UI, e.g. \"Tenant\". Leave blank to use \"organisation\".",
    orgLabelPlural: "Organisation label (plural)",
    orgLabelPluralHint: "e.g. \"Tenants\". Leave blank to use \"Organisations\".",
    save: "Save platform branding",
    saved: "Saved.",
    logoUploaded: "Logo uploaded.",
    loginBackground: "Default login page background image",
    loginBackgroundUploaded: "Background image uploaded.",
    emailFooterTitle: "Outgoing email footer",
    emailFooterHint: (org: string) => `Shown in the footer of every outgoing email, and as the fallback for any ${org} that hasn't set its own.`,
    emailFooterCompanyName: "Company name",
    emailFooterCompanyNameHint: "Leave blank to use the built-in product name.",
    emailFooterWebsite: "Website",
    emailFooterAddress: "Postal address",
  },
  serverModules: {
    title: "Modules",
    policyTitle: "Entitlement policy",
    policyHint: (orgPlural: string) => `Whether ${orgPlural} may use modules unless an override says otherwise. Withdrawing a module from one is done under "Availability per organisation" below.`,
    policyLabel: "Default entitlement policy",
    policySaved: "Entitlement policy saved.",
    defaultsTitle: "Module defaults",
    defaultsHint: (orgPlural: string) => `What ${orgPlural} get for a module they have not chosen for themselves. A fresh install starts with every module on. Changing a default never changes an organisation's own choice or an existing project.`,
    defaultsToastSaved: (name: string) => `${name} default saved.`,
    availabilityLabel: (name: string) => `${name} default`,
    builtInDefault: "Built-in default, not yet set on this server.",
    serverDefault: "Set on this server.",
    applyButton: (orgPlural: string) => `Apply to all ${orgPlural}`,
    applyHint: (orgPlural: string) => `Replaces each of the ${orgPlural}' own choices with these defaults, for the modules it is entitled to. Existing projects keep their state.`,
    applyTitle: (orgPlural: string) => `Apply the defaults to all ${orgPlural}?`,
    applyMessage: (orgPlural: string, typed: string) => `This replaces each of the ${orgPlural}' own module choices with the defaults above, across the whole server. Existing projects keep their current state. Type "${typed}" to confirm.`,
    applyTyped: "Apply",
    applyConfirm: "Apply to all",
    applyDone: (orgs: number, rows: number) => `Applied: ${rows} setting(s) changed across ${orgs}.`,
    orgTitle: (org: string) => `Availability per ${org}`,
    orgHint: (org: string) => `Choose ${org === "organisation" ? "an" : "a"} ${org} to grant or withdraw a module. A module that is withdrawn is hidden from its administrators and projects.`,
    orgPickerPlaceholder: (org: string) => `Select ${org === "organisation" ? "an" : "a"} ${org}…`,
    entitledLabel: (name: string) => `${name} available`,
    entitledToast: (name: string, entitled: boolean) => `${name} ${entitled ? "granted" : "withdrawn"}.`,
    stateSummary: (enabled: boolean, source: string) => `${enabled ? "Enabled" : "Not enabled"} (${source})`,
    followsPolicy: "following the entitlement policy",
    overridden: "overridden here",
    loadError: "Could not load the module settings.",
  },
  signupSettings: {
    title: "Public sign-up",
    hint: "Controls whether anyone can create their own account without an admin or invite.",
    mode: "Sign-up mode",
    modeDisabled: "Disabled — accounts are created by an admin or invite only",
    modeAlwaysOn: (org: string) => `Always on — anyone can sign up (no ${org} is joined automatically)`,
    modeOrgSpecified: (org: string) => `Org specified — sign-up is allowed only for email domains an ${org} has opted in`,
    modeOrgSpecifiedHint: (orgPlural: string) =>
      `${orgPlural} opt in and set their accepted domain from their own Advanced Settings page.`,
    save: "Save sign-up mode",
    saved: "Saved.",
  },
  serverOrgs: {
    active: "Active",
    disabled: "Disabled",
    disable: "Disable",
    enable: "Enable",
    disableTitle: "Disable \"{name}\"?",
    disableConfirm: "Every member, including its own admins, will immediately lose access to all of its projects and content until you re-enable it. No data will be touched.",
    createdToast: (orgCap: string) => `${orgCap} created`,
    disabledToast: (org: string) => `${org} disabled`,
    enabledToast: (org: string) => `${org} enabled`,
    deletedToast: (orgCap: string) => `${orgCap} permanently deleted`,
    delete: "Delete",
    deleteTitle: (org: string) => `Permanently delete this ${org}`,
    deleteHint: (name: string, org: string) =>
      `This permanently deletes "${name}" and everything it owns — every {project}, {requirement}, {changeRequest}, and uploaded file. This cannot be undone. Type the ${org}'s name to confirm.`,
    deleteConfirmButton: "Permanently delete",
    search: (orgPlural: string) => `Search ${orgPlural.toLowerCase()}`,
    filterAll: "All",
    empty: (orgPlural: string) => `No ${orgPlural.toLowerCase()} match these filters.`,
    // Style guide "Pattern: action menu" — the row-level `ActionMenu`
    // (Edit/Disable-Enable/Delete) replacing three standalone buttons;
    // named after the row's own organisation, per Principle 8 (every
    // `ActionMenu` trigger needs a real, disambiguating accessible name
    // once more than one can appear on the same page).
    actionsFor: (name: string) => `${name} actions`,
  },
  orgAdmin: {
    projectCodes: "Project codes",
    organizationCode: "Organisation code",
    organizationCodeHint: "Goes in front of the codes of records the organisation itself owns (shared Personas, Stakeholders, Strategies...), for example ACME-PER-001. Letters and digits only, and different from every project code.",
    organizationCodeLabel: "Code",
    organizationCodeSaved: "Organisation code saved",
    organizationCodeConfirmTitle: "Change the organisation code?",
    organizationCodeConfirmBody: (from: string, to: string) => `${from} becomes ${to}. Codes already written down as ${from}-PER-001 and similar will no longer find their record; the records themselves keep their own codes.`,
    organizationCodeConfirm: "Change code",
    codePolicyHint: "A project's code goes in front of its record codes where records from several {projects} appear together, for example ACME-REQ-001. Changes apply to codes created from now on; existing codes are never rewritten.",
    codeKind: "Characters",
    codeMinLength: "Shortest",
    codeMaxLength: "Longest",
    codeAssignment: "Assignment",
    codePolicyPreview: (rule: string) => `Codes are ${rule}.`,
    codePolicySaved: "Project code policy saved",
    enforceCodeEverywhere: "Always show the project code",
    enforceCodeEverywhereHint: "Shows ACME-REQ-001 instead of REQ-001 inside a {project} too, for everyone. Otherwise each person chooses in Preferences.",
    // Resource-menu group labels — Org Admin's 15 flat accordions regrouped into
    // 6 route-addressable groups. Static text, not org-dependent, matching
    // the style guide's own "after" diagram exactly.
    //
    // "People" was later split into its own two top-level groups, "Users"
    // and "Groups" (style guide "Pattern: settings hierarchy" addendum,
    // 2026-08-24 — a flat regroup, no new navigation capability) — new
    // strings rather than reusing `groupPeople` for one of the two.
    groupOverview: "Overview",
    groupUsers: "Users",
    groupGroups: "Groups",
    groupProjectsWorkflow: "Projects & workflow",
    groupBrandingDefaults: "Branding & defaults",
    groupTemplatesReports: "Templates & reports",
    // "Integrations & security" was later split into its own three
    // top-level groups — SSO/OIDC + SCIM (both identity-provisioning
    // integrations) grouped as "OAuth/SSO", SMTP as its own "Email", and
    // 2FA/self-signup/external-user-policy/PATs as "Security" — a flat
    // regroup per the style guide's settings-hierarchy addendum, same
    // reasoning as the earlier Users/Groups split above.
    groupOauthSso: "OAuth/SSO",
    groupEmail: "Email",
    groupSecurity: "Security",
    // A new top-level
    // group rather than folded into "Security", since it's a distinct
    // day-to-day admin surface (enabling/disabling optional feature
    // modules) rather than an authentication/access-policy setting.
    groupModules: "Modules",
    groupTags: "Tags",
    // Fine-Grained Access Control (core) — a new top-level group covering
    // both custom-role definition (org-admin-only) and the broader
    // grant_roles-based assignment surface for fixed/module/custom roles
    // together (named "Role Management," not "Custom
    // Roles," since it spans more than custom roles alone).
    groupRoleManagement: "Role management",
    customRolesTitle: "Custom roles",
    customRolesHint: "A custom role is a named set of permissions, additive to the fixed and module roles above — it never replaces them.",
    newCustomRole: "New custom role",
    customRolePreset: "Start from a preset",
    customRolePresetNone: "Blank role",
    editCustomRoleModalTitle: "Edit custom role",
    editCustomRole: (name: string) => `Edit ${name}`,
    noCustomRoles: "No custom roles defined yet.",
    customRoleName: "Name",
    customRoleDescription: "Description",
    customRoleScope: "Scope",
    customRoleScopeOrg: "Organisation-wide",
    customRoleScopeProject: "Per-project",
    customRolePermissionsLabel: "Permissions",
    customRolePermissionsCount: (n: number) => `${n} permission${n === 1 ? "" : "s"}`,
    customRoleCreated: "Custom role created",
    customRoleUpdated: "Custom role updated",
    customRoleDeleted: "Custom role deleted",
    deleteCustomRole: (name: string) => `Delete ${name}`,
    confirmDeleteCustomRoleTitle: "Delete custom role?",
    confirmDeleteCustomRoleMessage: (name: string) =>
      `This removes "${name}" and every grant of it to a user or group. This cannot be undone.`,
    customRoleAssignmentTitle: "Grant roles to users or groups",
    customRoleAssignmentHint:
      "Fixed and module roles are granted from the Users table above. A custom role can also be granted here, to a user or an organisation group — there is no roster of who currently holds a role shown here, so granting/revoking acts immediately rather than toggling a checked state.",
    customRoleSelectProjectFirst: "Select a {project} first",
    customRoleSelectScopeFirst: (scopeLabel: string) => `Select a ${scopeLabel} first`,
    customRoleGrantToUserOrGroup: (role: string) => `Grant ${role} — search a user or group`,
    customRoleRevokeFromUserOrGroup: (role: string) => `Revoke ${role} — search a user or group`,
    customRoleGrantFieldLabel: "Grant to user or group",
    customRoleRevokeFieldLabel: "Revoke from user or group",
    customRoleGrantedTo: (target: string) => `Granted to ${target}`,
    customRoleRevokedFrom: (target: string) => `Revoked from ${target}`,
    // The org-
    // level Compliance Manager surface (standards/versions/requirements/
    // required actions/mapping vocabulary), a new top-level group rather
    // than nested under "Modules" (that group is the generic enable/
    // disable toggle table any module gets, not a home for a specific
    // module's own content).
    groupCompliance: "Compliance",
    // The org-
    // wide compliance dashboard/reporting surface (§22/§23), separate flat
    // top-level groups from "Compliance" above (standards management)
    // rather than a fourth tab on that group's panel — the style guide's
    // own "split into more flat groups, don't nest" addendum, since these
    // are different jobs for a different (if overlapping) audience.
    // Originally one combined "Compliance overview" group with its own
    // internal `Tabs` (Dashboard / Compliance by standard / Outstanding);
    // The same addendum applies a second time, one level deeper —
    // that inner `Tabs` was itself a second, redundant navigation
    // mechanism nested inside the `ResourceMenu` group's own left-hand
    // menu, so the three tabs became three flat top-level
    // `orgOverviewSections` entries instead (`ResourceMenu → Tabs →
    // content`, three deep, collapsed to `ResourceMenu → content`, two).
    groupComplianceDashboard: "Compliance dashboard",
    groupComplianceByStandard: "Compliance by standard",
    groupComplianceOutstanding: "Outstanding compliance items",
    sectionsNav: "Organisation admin sections",
    adminSubtitle: (orgCap: string) => `${orgCap} admin`,
    organizations: (orgPlural: string) => orgPlural,
    rename: "Rename",
    renameHint: (org: string) => `The new name is used everywhere this ${org} is displayed, including its own delete-confirmation prompt.`,
    renamed: "Renamed",
    // Style guide "Pattern: action menu" — the kebab trigger combining
    // Rename and Export on the Overview group.
    orgActions: (orgCap: string) => `${orgCap} actions`,
    backToOrganizations: (orgPlural: string) => `Back to ${orgPlural.toLowerCase()}`,
    notAMemberTitle: (org: string) => `You're not a member of this ${org}`,
    notAMemberHint: "As a server admin you can still set it up: become its admin yourself, or create an admin user for someone else to log in as.",
    joinAsAdmin: (org: string) => `Become admin of this ${org}`,
    createInitialAdmin: "Create an admin user",
    initialAdminCreated: (org: string) => `User created — they can now log in and manage this ${org}.`,
    noOrganizations: (orgPlural: string) => `You don't belong to any ${orgPlural.toLowerCase()} yet.`,
    logo: (org: string) => `${org.charAt(0).toUpperCase()}${org.slice(1)} logo`,
    branding: "Branding",
    headerTitle: "Header title",
    headerTitleHint: "Shown next to the logo in the top bar. Leave blank to use the default.",
    useOwnAccentColor: (org: string) => `Override the platform default accent colour for this ${org}`,
    saveBranding: "Save branding",
    brandingSaved: "Branding saved",
    emailFooterTitle: "Outgoing email footer",
    emailFooterHint: (org: string) => `Overrides the platform default footer identity for this ${org}'s outgoing emails. Leave blank to use the platform default.`,
    emailFooterCompanyName: "Company name",
    emailFooterWebsite: "Website",
    emailFooterAddress: "Postal address",
    defaultTemplate: "Default {project} template",
    projects: "{Projects}",
    projectsHint: (org: string) => `Every {project} in this ${org}, including ones you don't otherwise have a role on — lets you manage a {project}'s users without needing its own admin access.`,
    manageUsers: "Manage users",
    // (docs/decisions.md): the inline "Manage users" expand-in-place
    // became a `Modal` wrapping the same `ProjectMembersTable`
    // `ProjectAdminPage.tsx`'s own Members section uses (rebuilt onto that
    // component) — literally the
    // same component, not a parallel reimplementation.
    manageUsersModalTitle: (projectName: string) => `Manage users — ${projectName}`,
    users: (orgCap: string) => `${orgCap} users`,
    email: "Email",
    name: "Name",
    password: "Password",
    roles: "Roles",
    rolesFor: (name: string) => `${name}'s roles`,
    noRoles: "No roles",
    cannotChangeOwnRole: "You cannot change your own organisation role here.",
    status: "Status",
    statusActive: "Active",
    statusArchived: "Archived",
    statusDeactivated: "Deactivated",
    // 2026-08-31 clarity pass : "Active" means
    // "not deactivated", not "has ever logged in" — a freshly created user
    // (or an invite the moment it's accepted) shows Active immediately,
    // which read as surprising until this tooltip spelled out why.
    statusActiveHint: "This account is not deactivated. It doesn't necessarily mean the person has logged in yet.",
    newUser: "New user",
    userCreated: "User created",
    // "Invite user" : a second, distinct way
    // to add a user, alongside "New user" — an email link the invitee
    // completes themselves, rather than an admin-set password. The hint
    // below sits next to both buttons so the difference is obvious rather
    // than discovered by trial.
    inviteUser: "Invite user",
    newUserModalHint: "You set their password now. To let them choose their own, use Invite user instead.",
    inviteUserModalHint: "They'll get an email with a link to choose their own password and display name.",
    sendInvite: "Send invite",
    inviteSent: "Invite sent",
    passwordRuleHint: "At least 8 characters.",
    invitedBy: (name: string) => `Invited by ${name}`,
    invitedSentOn: (date: string) => `Sent ${date}`,
    noUsersFound: "No users match this search/filter.",
    role: "Role",
    allRoles: "All roles",
    grantRole: (role: string, name: string) => `Grant ${role} to ${name}`,
    revokeRole: (role: string, name: string) => `Revoke ${role} from ${name}`,
    roleGranted: "Role granted",
    roleRevoked: "Role revoked",
    searchUsers: "Search by name or email",
    groups: (orgCap: string) => `${orgCap} groups`,
    searchGroups: "Search by name",
    noGroupsFound: "No groups match this search.",
    newGroup: "New group",
    groupNamePlaceholder: "e.g. Engineering",
    groupCreated: "Group created",
    // Org group delete (2026-10-05). Title/button/toast reuse the Project
    // Groups' own `admin.deleteGroup*`/`groupDeleted`; only the consequence
    // differs, since an org group can carry roles across many projects.
    deleteGroupMessage:
      "Members lose every role and project access this group gave them, and it is removed from any group it's nested in. Access they hold some other way is unaffected. This cannot be undone.",
    // `DirectoryTable`'s row-detail panel — same "{name} details" shape `admin.groupDetails` already
    // established for Project Groups.
    groupDetails: (name: string) => `${name} details`,
    // Column header text for the row-count column both Org and Project
    // Groups tables share — distinct from `admin.memberCount(n)`, which
    // renders the actual "N member(s)" cell content, not the header.
    groupMembersColumn: "Members",
    addNestedGroup: "Nest a group…",
    nestedGroupLabel: (name: string) => `${name} (nested group)`,
    // Renamed from "IdP-synced group name" (2026-08-31) to match this app's existing "SSO group"
    // terminology (`oidcRequiredGroup`'s "Required SSO group" label below)
    // rather than the more technical "IdP" term, which appears nowhere else
    // in this org's own SSO copy. Key name kept as-is to avoid touching
    // every existing call site for a copy-only change.
    idpSyncedGroupName: "SSO group name",
    idpSyncedGroupNamePlaceholder: "e.g. eng-team",
    // The explicit enable/disable toggle wrapping the sync name +
    // granted-role fields — checked by default only when the group already
    // has a sync name set; unchecking clears both fields via the same PATCH
    // the Save button already uses.
    syncFromSso: "Sync membership and role from an SSO/IdP group",
    // Role-granting is surfaced right
    // next to the sync name and saved together via one button — replaces
    // the old, disconnected "SSO group mappings" list this org's Advanced/
    // OAuth-SSO settings used to carry (`ssoMappings` etc., retired).
    grantedOrgRole: "Grants role on sync",
    grantedOrgRoleNone: "No role granted",
    grantedOrgRoleHint: "A user whose IdP group claim matches the sync name above is granted this role — requires a sync name to also be set.",
    // This hint used to
    // sit next to a granted-role select that was the *only* gated field —
    // the sync-name input and Save button rendered unconditionally above it
    // even with no SSO configured at all. Now the whole sync sub-section
    // (name, role, toggle, save) is gated on the same check, and this is
    // the sole thing shown when it isn't configured.
    ssoNotConfiguredHint: (org: string) => `Set up SSO/OIDC for this ${org} first to grant a role here.`,
    saveIdpSync: "Save sync settings",
    groupSyncUpdated: "Sync settings updated",
    resources: "Shared resources",
    resourcesHint: (org: string) => `Uploaded resources can be linked to {requirements} in any {project} in this ${org}.`,
    // Users table Actions column (docs/decisions.md) — the two existing bare buttons
    // (View access, lock/unlock display name) consolidated into one
    // `ActionMenu`, plus two new actions: "Remove from {org}" (a genuinely
    // new, access-mutating endpoint) and "Add to group" (pure UI
    // reachability fix, `AddToGroupControl` — kept as its own small
    // popover-triggering control next to the menu rather than folded into
    // it, since it needs an anchored `Popover` of its own, not a single
    // `onSelect` the kebab menu's plain-button items can express).
    usersActionsFor: (name: string) => `${name}'s actions`,
    removeFromOrg: (org: string) => `Remove from ${org}`,
    removeFromOrgConfirmTitle: (name: string) => `Remove ${name} from this organisation?`,
    removeFromOrgConfirmMessage: (name: string, org: string) =>
      `This revokes ${name}'s role(s) and access to every project in this ${org}. They can be re-invited later.`,
    removeFromOrgConfirmButton: "Remove",
    removedFromOrgToast: (name: string) => `Removed ${name} from this organisation.`,
    addToGroupFor: (name: string) => `Add ${name} to a group`,
    addToGroupSelectLabel: "Group",
    addToGroupSelectPlaceholder: "Choose a group…",
    lockDisplayName: "Lock display name",
    unlockDisplayName: "Unlock display name",
    displayNameLockSaved: (name: string, locked: boolean) => `${name}'s display name ${locked ? "locked" : "unlocked"}.`,
    viewAccess: (name: string) => `View ${name}'s access`,
    userAccessTitle: (name: string) => `${name}'s access`,
    userAccessOrgGroups: (orgCap: string) => `${orgCap} groups`,
    userAccessNoOrgGroups: (org: string) => `Not a member of any ${org} group.`,
    userAccessProjects: "Projects",
    userAccessNoProjects: "No access to any project in this organisation.",
    userAccessProjectGroups: "Via project group(s)",
    // Reversal (docs/decisions.md, docs/ux-style-guide.md
    // "Pattern: role display"): this panel now shows the collapsed summary
    // by default per project row, with this pair of toggle labels revealing/
    // hiding the full, uncollapsed role set on demand.
    userAccessShowAllRoles: (count: number) => `Show all ${count} roles`,
    userAccessShowFewerRoles: "Show fewer",
    // The old "Advanced settings" catch-all doesn't survive the resource-
    // menu regrouping as one item — its settings domains split by what
    // they actually govern (style guide "Pattern: settings hierarchy"):
    // SMTP/email gets its own card, and 2FA/self-signup/external-user-
    // policy becomes "Security". PAT lifetime joins the existing PAT list
    // (see `pats` below) rather than getting a heading of its own.
    smtpEmailTitle: "SMTP & email",
    securityTitle: "Security",
    // The org admin's "Modules" section (enable/
    // disable a feature module among those the org is entitled to).
    modulesTitle: "Modules",
    modulesDescription:
      "Choose which modules this organisation uses. A default only applies to projects created after you change it; Off removes the module from every project.",
    modulesEmpty: "No modules are registered on this deployment yet.",
    moduleNotEntitledHint: "Not available on this organisation's current plan. Contact your server administrator to request access.",
    moduleNotImplementedHint: "Not yet available in this version of the application.",
    moduleAvailabilityLabel: (name: string) => `${name} availability`,
    moduleAvailabilityToast: (name: string, availability: string) => `${name}: ${availability}`,
    moduleSubComponentAvailabilityLabel: (moduleName: string, subComponentName: string) =>
      `${subComponentName} (${moduleName}) availability`,
    moduleSubComponentsSummary: (count: number, offCount: number) =>
      `${count} component${count === 1 ? "" : "s"} · ${offCount === 0 ? "all on" : `${offCount} off`}`,
    smtpHost: "SMTP host",
    smtpPort: "SMTP port",
    smtpUsername: "SMTP username",
    smtpPassword: "SMTP password",
    smtpUseTls: "Use TLS",
    testEmail: "Send test email",
    testEmailHint: (org: string) => `Sends a test email using this ${org}'s SMTP settings above, so you can confirm they actually work before relying on them.`,
    testEmailRecipient: "Recipient email",
    testEmailRecipientHint: "Defaults to your own account when left blank.",
    testEmailNoSmtp: "Set an SMTP host above first.",
    testEmailSending: "Sending…",
    testEmailSent: "Test email sent — check the inbox (and spam folder) for delivery.",
    orgRole: (orgCap: string) => `${orgCap} role`,
    // SSO group→role mapping moved from here (a flat, disconnected list)
    // onto the group being synced into instead — see `grantedOrgRole` etc. above, managed from Groups.
    ssoMappingsMovedHint: "Granting a role via an SSO group claim is now set on the group itself — see the Groups section.",
    // `saveAdvanced` submits the whole `OrgAdvancedSettings` object — one
    // shared PUT behind three separate resource-menu groups now, each with
    // its own button calling it. Labelled per the group it's actually on,
    // not the retired "Advanced" concept the object's own backend name
    // still carries.
    saveAdvanced: "Save security settings",
    saveEmailSettings: "Save email settings",
    accessReview: "Access review",
    filterStale: "Stale (180+ days)",
    filterNo2fa: "No 2FA",
    filterNoProjectAccess: "No {project} access",
    filterClear: "Clear filters",
    // "Show invited" : pending, not-yet-
    // accepted invites are a new row kind merged into this table — this
    // checkbox lets an admin hide them again, defaulting on since they're
    // new and otherwise invisible.
    filterShowInvited: "Show invited",
    lastLogin: "Last login",
    never: "Never",
    twoFactor: "2FA",
    ssoConfig: "Single sign-on (SSO)",
    slug: "Login page slug",
    slugHint: (org: string) => `This ${org}'s branded login page will be at /login/{slug}.`,
    ssoEnabled: "Enable SSO",
    ssoOnly: "Hide the native email/password form (SSO only)",
    oidcIssuerUrl: "OIDC issuer URL",
    oidcClientId: "OIDC client ID",
    oidcClientSecret: "OIDC client secret",
    oidcRequiredGroup: "Required SSO group",
    oidcRequiredGroupHint: "If set, only users whose identity provider group/role claim includes this exact name are let in — everyone else sees a \"not provisioned\" message instead of signing in, even if they authenticate successfully.",
    saveSso: "Save SSO settings",
    scimProvisioning: "SCIM provisioning",
    scimHint: "Lets an identity provider push user and group membership changes directly (no login required), for prompt deprovisioning — the alternative to the group-claim sync above, which only runs when a user actually signs in.",
    scimEnabledWithPrefix: (prefix: string) => `Enabled — current token starts with ${prefix}…`,
    scimDisabled: "Not enabled.",
    scimGenerate: "Generate SCIM token",
    scimRegenerate: "Regenerate SCIM token",
    scimRevoke: "Revoke",
    scimTokenLabel: "SCIM token",
    scimTokenShownOnce: "Copy this token now — it won't be shown again. Configure it as the bearer token in your identity provider's SCIM app settings.",
    loginBackground: "Login page background image",
    loginBackgroundUploaded: "Background image uploaded.",
    loginBackgroundRemoved: "Background image reset to the platform default.",
    logoUploaded: "Logo uploaded.",
    logoRemoved: "Logo reset to the platform default.",
    pats: "Personal Access Tokens",
    patMaxLifetime: "Maximum Personal Access Token lifetime (days)",
    patMaxLifetimeHint: (org: string) => `Leave blank to use the deployment default. Lowering this immediately shortens the effective lifetime of tokens already issued for this ${org}, not just new ones.`,
    require2fa: "Require two-factor authentication",
    require2faHint: (org: string) => `Blocks every member of this ${org}, including its own admins, from any of its projects or settings until they enable 2FA in Preferences. They can still enrol themselves at any time to regain access immediately — no admin action needed.`,
    allowSelfSignup: "Allow self-signup",
    allowSelfSignupHint: (org: string) => `When the deployment's sign-up mode is "org specified", anyone with a matching email domain (below) can create their own account and join this ${org} as a member. Cannot be enabled for an SSO-only ${org}.`,
    allowRelaxedChildProjectCreation: "Allow {project} managers to create sub-{project}s",
    allowRelaxedChildProjectCreationHint:
      "When enabled, anyone who manages a {project} can create a new {project} nested under it without needing Project creator or Organisation admin rights. Turning this off means only an Organisation admin or Project creator can create any {project}, including sub-{project}s.",
    selfSignupSsoConflict: (org: string) => `Self-signup can't be enabled while this ${org} is SSO-only — turn off "SSO only" in the SSO configuration below first, or turn off self-signup here.`,
    // Org-wide force of
    // `Project.require_change_request_for_approved_links`, minus a
    // per-project `exempt_from_org_link_lock` opt-out. See `Organization`'s
    // own field docstring (`frontend/src/api/types.ts`) for the full
    // resolution.
    forceRequireChangeRequestForApprovedLinks: "Require a change request for link changes on approved {requirements}, org-wide",
    forceRequireChangeRequestForApprovedLinksHint:
      "Applies to every {project} in this organisation, even one whose own setting is off — unless that {project} is individually marked exempt in its own Project Admin settings.",
    // AI approval via MCP (docs/decisions.md). Both this AND a given
    // {project}'s own toggle (Project Admin's settings) must be on before
    // an AI assistant acting through the MCP server can approve, decide,
    // or complete anything in that {project} — this flag alone is not
    // sufficient. Readable by any org member (see OrganizationOut.
    // allow_ai_approvals's docstring) since a {project} manager needs to
    // know whether their own toggle can even take effect.
    allowAiApprovals: "Allow AI approval via MCP",
    allowAiApprovalsHint:
      "Lets an AI assistant acting through the MCP server approve/decide/complete things — but only in a {project} whose own manager or administrator has also explicitly enabled it. Off by default.",
    allowAiApprovalsAckTitle: "Allow AI approval for this organisation?",
    allowAiApprovalsAckBody:
      "Approvals made by an AI assistant through the MCP server are not necessarily a deliberate, in-the-moment decision by a human reviewer, and may weaken the accountability this approval workflow is meant to represent.",
    allowAiApprovalsAckCheckbox: "I understand this and want to allow it for this organisation anyway.",
    allowAiApprovalsAckConfirm: "Allow AI approval",
    autoAcceptEmailDomain: "Accepted email domain",
    autoAcceptEmailDomainHint: "e.g. acme.com — used both for self-signup above and for domain-restricted external users below.",
    externalUserPolicy: "External users on projects",
    externalUserPolicyDisabled: (org: string) => `Disabled — {project} members must already belong to this ${org}`,
    externalUserPolicyDomainOnly: "Domain only — existing accounts anywhere can be added; new accounts only if their email matches the accepted domain above",
    externalUserPolicyAnyone: "Anyone — any email address can be added or invited",
    outsideDomainUsers: (org: string) => `Users outside this ${org}`,
    outsideDomainUsersHint: (org: string) => `Existing accounts elsewhere in the system whose email matches this ${org}'s accepted domain but aren't members yet.`,
    showOutsideDomainUsers: "Show users outside this org",
    noOutsideDomainUsers: (org: string) => `No matching users found outside this ${org}.`,
    patUser: "User",
    patName: "Name",
    patExpires: "Expires",
    patLastUsed: "Last used",
    patOtherOrgs: (n: number, orgPlural: string) => `Also scoped to ${n} other ${orgPlural.toLowerCase().replace(/s$/, "")}(s)`,
    patRevoke: "Revoke",
    patDescope: "Descope",
    patDescopeTitle: (org: string) => `Remove this ${org} from the token's scope?`,
    patDescopeConfirm: (orgPlural: string) =>
      `It will remain valid for the member's other ${orgPlural.toLowerCase()}.`,
    patRevokeOneTitle: "Revoke this token outright?",
    patRevokeOneConfirm: "This cannot be undone.",
    patRevokeAll: (org: string) => `Revoke all Personal Access Tokens for this ${org}`,
    patRevokeAllTitle: (org: string) => `Revoke every Personal Access Token that touches this ${org}?`,
    patRevokeAllConfirm: (orgPlural: string) =>
      `This fully revokes each matching token — including any other ${orgPlural.toLowerCase()} it's also scoped to, not just this one — and cannot be undone.`,
    patRevokeAllResult: "Revoked {n} token(s).",
    patNone: (org: string) => `No tokens currently reach this ${org}.`,
    projectStatuses: "{Project} statuses",
    projectStatusesHint: "The statuses available to every {project} in this organisation — shown on each {project}'s settings tab.",
    newProjectStatus: "New status",
    deleteProjectStatus: "Delete this status",
    linkTypes: "Link types",
    linkTypesHint: "Relationship types available when linking two {requirements} together — each needs a name for both directions so a link reads correctly from either {requirement}.",
    newLinkType: "New link type",
    forwardName: "Forward name",
    reverseName: "Reverse name",
    linkTypeFlowHint:
      "Direction tells a {requirement}'s link graph where the target sits when read with the forward name: “Target is upstream” for “Derives from” (the target is where this one comes from), “Target is downstream” for “Is implemented by” (the target depends on this one), “No direction” for “Related to”. Unclassified types still show, as related.",
    linkTypeFlowLabel: (name: string) => `Direction: ${name}`,
    linkTypeNestingHint:
      "“Across nested projects” says whether a link type may join a record to one in a parent or child project, and which end may sit higher. “Same project only” turns it off for the type. “Upstream end may be in a parent project” follows the type's direction: a Pain point can sit in a parent project above the Decision that addresses it, never below. “Either end may be in a parent project” allows both. Siblings and unrelated projects can never be linked. Applies when a link is made; existing links are kept and flagged, never deleted.",
    linkTypeNestingLabel: (name: string) => `Across nested projects: ${name}`,
    linkTypeNesting: "Across nested projects",
    linkTypeNestingExample: {
      same_project: "Both records must be in one project.",
      upstream_in_ancestor: "The upstream record (for example a Pain point) may be in a parent project, never below.",
      ancestor_either_way: "Either record may be in a parent project.",
    },
    linkTypeNestingNeedsFlow: "Needs a direction: choose a direction for this link type to use this option.",
    linkTypeNestingUpdated: "Link type nesting updated.",
    linkTypeNestingFailed: "Could not update the link type nesting.",
    linkTypeNestingNarrowTitle: "Narrow where this link type can be used?",
    linkTypeNestingNarrowMessage: (flagged: number) =>
      `${flagged} existing link(s) between a project and its parent or child will be flagged as no longer permitted by this link type. They are kept and still shown; nothing is deleted.`,
    linkTypeNestingNarrowConfirm: "Narrow",
    linkTypeFlowUpdated: "Link type direction updated.",
    linkTypeFlowFailed: "Could not update the link type direction.",
    deleteLinkType: "Delete this link type",
    linkTypeRestrictionHint:
      "Any two kinds of record can be linked unless a link type is restricted. “Can link from” and “Can link to” limit which kinds of record a link type may join, read from the forward name (for example “Addresses” from Decision to Pain point). Leave both on “Any artefact” for no restriction. Restrictions apply when a link is made; existing links are never changed.",
    anyArtefact: "Any artefact",
    linkTypeCanLinkFrom: "Can link from",
    linkTypeCanLinkTo: "Can link to",
    linkTypeCanLinkFromLabel: (name: string) => `Can link from: ${name}`,
    linkTypeCanLinkToLabel: (name: string) => `Can link to: ${name}`,
    linkTypeRestrictionUpdated: "Link type restriction updated.",
    linkTypeRestrictionFailed: "Could not update the link type restriction.",
    linkTypeDedicatedNote: "Made with its own action (for example superseding), not as a general link.",
    linkTypeAdded: "Link type added.",
    linkTypeRenamed: "Link type renamed.",
    linkTypeDeleted: "Link type deleted.",
    linkTypesTab: "Link types",
    linkTypesByArtefactTab: "By artefact type",
    artefactRulesHint:
      "Limit which link types an artefact type may use, for example a Requirement may only be linked with “Derives from” and “Implements”. A link must satisfy its link type's restriction and the rule of both artefact types it joins. Artefact types with no rule can use any link type. Rules apply when a link is made; existing links are never changed.",
    artefactRuleLabel: (label: string) => `Link types allowed for ${label}`,
    artefactRuleAny: "Any link type",
    artefactRuleUpdated: "Link rule updated.",
    artefactRuleRemoved: "Link rule removed.",
    artefactRuleFailed: "Could not update the link rule.",
    artefactRuleLastTypeHint: "A rule must allow at least one link type. Remove the rule to allow any.",
    artefactRuleCustom: "Limited",
    artefactRuleReset: "Allow any link type",
    artefactRuleRemoveTitle: (label: string) => `Allow any link type for ${label}?`,
    artefactRuleRemoveMessage: (label: string) =>
      `${label} will be able to use any link type again. Existing links are not changed.`,
    artefactRuleRemoveConfirm: "Remove rule",
    linkTypeUsageLinks: (links: number, projects: number | null) =>
      projects === null
        ? `${links} link(s) use this link type.`
        : `${links} link(s) in ${projects} project(s) use this link type.`,
    linkTypeUsagePending: (n: number) =>
      `${n} pending change request(s) propose this link type. Moving the links updates them; deleting the links is blocked until they are resolved.`,
    linkTypeUsageApproved: (n: number) =>
      `${n} of the links involve an approved requirement in a project that normally requires a change request for link changes.`,
    linkTypeUsageRules: (labels: string) => `It is named in the link rule of: ${labels}.`,
    linkTypeUsageEmptied: (labels: string) =>
      `Deleting the links is blocked because it is the only link type allowed for: ${labels}.`,
    linkTypeFlowDiffers: "Its direction differs, so this changes what the moved links mean.",
    linkTypeRemoveDescription: (links: number) => `Permanently deletes ${links} link(s), then the link type.`,
    linkTypeRemoveConfirmMessage: (name: string, links: number) =>
      `This permanently deletes the “${name}” link type and its ${links} link(s). This cannot be undone.`,
    linkTypeRemoveConfirmLabel: "Delete links and link type",
    linkTypeKeepLabel: (projects: number) => `Keep this link type in the ${projects} other {project}(s) that use it`,
    linkTypeKeepDescription:
      "Each of those {projects} keeps its own copy, so their links read exactly as before. Only the links here are moved or removed.",
    linkTypeKeepUnmanageable: (projects: number) =>
      `${projects} other {project}(s) hold links of this type that you cannot manage. Keep the link type for them to delete it.`,
    linkTypeDeleteOutcome: (outcome: { moved: number; merged: number; removed: number; copies_created: number; copies_renamed: string[] }) => {
      const parts: string[] = [];
      if (outcome.moved > 0) parts.push(`${outcome.moved} link(s) moved${outcome.merged > 0 ? `, ${outcome.merged} merged` : ""}`);
      else if (outcome.merged > 0) parts.push(`${outcome.merged} link(s) merged`);
      if (outcome.removed > 0) parts.push(`${outcome.removed} link(s) deleted`);
      if (outcome.copies_created > 0) parts.push(`kept in ${outcome.copies_created} {project}(s)`);
      if (outcome.copies_renamed.length > 0) parts.push(`renamed to avoid a clash: ${outcome.copies_renamed.join(", ")}`);
      return parts.length > 0 ? `Link type deleted: ${parts.join("; ")}.` : "Link type deleted.";
    },
    linkTypeScopeOrganization: "Organisation",
    linkTypeScopeProject: "This {project}",
    linkTypeScopeInherited: "Parent {project}",
    linkTypeInheritedFrom: (name: string) => `Inherited from ${name}`,
    linkTypeHidden: "Hidden",
    linkTypeHiddenByParent: "Hidden by a parent {project}",
    linkTypeShadowed: (name: string) => `Not offered: “${name}” takes precedence`,
    linkTypeHideLabel: (name: string) => `Hide ${name} in this {project}`,
    linkTypeShowLabel: (name: string) => `Show ${name} in this {project}`,
    linkTypeHide: "Hide",
    linkTypeShow: "Show",
    linkTypeVisibilityUpdated: "Link type visibility updated.",
    linkTypeVisibilityFailed: "Could not update the link type visibility.",
    projectLinkTypesHint:
      "Organisation link types are shared by every {project}; hide the ones you never use. Link types you add here are available in this {project} and every {project} nested under it. Hiding removes a type from pickers only; existing links keep showing.",
    projectLinkTypesAvailableHeading: "Available to this {project}",
    projectLinkTypesOwnHeading: "Link types of this {project}",
    projectLinkTypesLocked: "Your organisation uses one shared set of link types, so they cannot be changed here.",
    projectLinkTypesRulesLocked: "Your organisation uses one shared set of link types, so these rules cannot be changed here.",
    artefactRuleSourceOrganization: "Organisation rule",
    artefactRuleSourceProject: "Set on this {project}",
    artefactRuleSourceInherited: (name: string | null) => (name ? `Inherited from ${name}` : "Inherited from a parent {project}"),
    artefactRuleUseInherited: "Use inherited rule",
    artefactRuleUseInheritedTitle: (label: string) => `Use the inherited rule for ${label}?`,
    artefactRuleUseInheritedMessage: (label: string) =>
      `This {project}'s own rule for ${label} is removed, so the rule inherited from a parent {project} or the organisation applies again. Existing links are not changed.`,
    artefactRuleProjectHint:
      "Limit which link types an artefact type may use in this {project} and the {projects} nested under it. A rule set here replaces the inherited one entirely, so it can allow more as well as less.",
    projectCustomisationHeading: "{Project} customisation",
    projectCustomisationLinkTypes: "Let {projects} add their own link types and hide the organisation's",
    projectCustomisationHint:
      "Switch this off for one shared set of link types across the organisation. Nothing is deleted: link types, hiding and rules that {projects} have set are switched off and come back if you switch it on again.",
    projectCustomisationAffected: (types: number, projects: number) =>
      types === 0 ? "No {project} has its own link types yet." : `${types} {project}-level link type(s) in ${projects} {project}(s) are affected.`,
    projectCustomisationLockTitle: "Switch off {project} link types?",
    projectCustomisationLockMessage: (types: number, projects: number) =>
      `Every {project} will use only the organisation's link types. ${types} {project}-level link type(s) in ${projects} {project}(s), and any hiding or rules set per {project}, stop applying (existing links keep showing). Nothing is deleted.`,
    projectCustomisationLockConfirm: "Switch off",
    projectCustomisationUpdated: "{Project} customisation updated.",
    projectCustomisationFailed: "Could not update {project} customisation.",
    deleteReportTemplate: (name: string) => `Delete ${name}`,
    deleteResource: (name: string) => `Delete ${name}`,
  },
  importMerge: {
    action: (org: string) => `Import into this ${org}`,
    hint: (org: string) =>
      `Adds an exported bundle's users, groups, projects, and report templates into this ${org} — its own branding, SMTP, and SSO settings are never changed by this. Choose a bundle exported from another organisation (.zip).`,
    chooseFile: "Choose bundle file",
    preview: "Preview import",
    previewing: "Checking for conflicts…",
    noConflicts: "No conflicts — ready to import.",
    conflictsTitle: (n: number) => `${n} conflict(s) to resolve before importing`,
    projectsSection: "{Projects}",
    reportTemplatesSection: "Report templates",
    projectSkip: "Skip (keep the existing {project})",
    projectImportAsCopy: "Import as a new copy",
    templateKeepExisting: "Keep the existing template",
    templateUseImport: "Use the imported version",
    confirmImport: "Import",
    cancel: "Cancel",
    importing: "Importing…",
    resultTitle: "Import complete",
    projectsImported: (n: number) => `${n} {project}(s) imported`,
    projectsSkipped: (n: number) => `${n} {project}(s) skipped`,
    reportTemplatesImported: (n: number) => `${n} report template(s) imported`,
    reportTemplatesOverwritten: (n: number) => `${n} report template(s) overwritten`,
  },
  system: {
    users: "Users",
    // Server Management → Users → "Add user".
    addUser: "Add user",
    addUserNoOrg: (org: string) => `No ${org}`,
    addUserNoOrgHint: (org: string) => `The account belongs to no ${org} yet; add it to one later.`,
    addUserInviteHint: "They get an email link to choose their own name and password. In an organisation they join as a member; change their role once they have signed up.",
    addUserPasswordHint: "You will know this password until the person changes it. Share it securely.",
    addUserCreated: (email: string) => `Created ${email}`,
    addUserInvited: (email: string) => `Invite sent to ${email}`,
    usersHint: (org: string) => `Every user on the deployment. Filter to orphaned accounts (no ${org} membership — the one category a server admin can act on directly) or server administrators below.`,
    organizations: (orgPlural: string) => orgPlural,
    organizationCount: (n: number, org: string) => `Member of ${n} ${org}(s)`,
    noOrganizations: "None",
    // Organisations column "show more"
    // toggle past 2 orgs, mirroring `orgAdmin.userAccessShowAllRoles`/
    // `userAccessShowFewerRoles`'s copy shape.
    showAllOrganizations: (n: number) => `Show all ${n}`,
    showFewerOrganizations: "Show fewer",
    groups: "Groups",
    // Groups column compact summary +
    // "View groups" modal (replacing the old unconditional joined string).
    groupsMore: (n: number) => `+${n} more`,
    viewGroups: "View groups",
    groupsModalTitle: (name: string) => `${name}'s groups`,
    noGroups: "No groups",
    email: "Email",
    name: "Name",
    lastLogin: "Last login",
    never: "Never",
    created: "Created",
    view: "Show",
    viewOrphaned: "Orphaned accounts",
    viewServerAdmins: "Server administrators",
    viewAll: "All users",
    // FilterPanel search box and
    // DirectoryTable empty state, added alongside the FilterPanel/
    // DirectoryTable rebuild — matches Org Admin's own `searchUsers`/
    // `noUsersFound` copy style.
    searchUsers: "Search by name or email",
    noUsersFound: "No users match this search/filter.",
    includeDeactivated: "Include deactivated accounts",
    deactivated: "Deactivated",
    bannedBadge: "Banned",
    usersActionsFor: (name: string) => `${name}'s actions`,
    deactivate: "Deactivate",
    reactivate: "Reactivate",
    deactivateTitle: "Deactivate this account?",
    deactivateConfirm: "They will be unable to log in until reactivated.",
    deactivatedToast: "Account deactivated",
    reactivatedToast: "Account reactivated",
    ban: "Ban",
    unban: "Unban",
    banTitle: "Ban this account?",
    banConfirm: (org: string) => `They will be deactivated immediately, and no ${org} admin will be able to grant them a role again until you unban them.`,
    bannedToast: "Account banned",
    unbannedToast: "Account unbanned",
    grantServerAdmin: "Grant server admin",
    revokeServerAdmin: "Revoke server admin",
    grantServerAdminTitle: "Grant server admin to this user?",
    grantServerAdminConfirm: (orgPlural: string) => `They will be able to manage ${orgPlural.toLowerCase()} and other server admins.`,
    grantedServerAdminToast: "Server admin granted",
    revokeServerAdminTitle: "Revoke server admin from this user?",
    revokeServerAdminConfirm: "They will lose access to server-wide management immediately.",
    revokedServerAdminToast: "Server admin revoked",
    // Server-tier
    // role strings, mirroring Org Admin's own roles column string shapes
    // (rolesFor/noRoles/grantRole/revokeRole). Originally an always-visible
    // "Server roles" MultiSelectDropdown column; moved behind an ActionMenu
    // modal (see `assignServerRoles`/
    // `assignServerRolesModalTitle` below) — these per-role strings are
    // still used there.
    serverRolesFor: (name: string) => `${name}'s server roles`,
    noServerRoles: "No server roles",
    grantServerRole: (role: string, name: string) => `Grant ${role} to ${name}`,
    revokeServerRole: (role: string, name: string) => `Revoke ${role} from ${name}`,
    assignServerRoles: "Assign server roles",
    assignServerRolesModalTitle: (name: string) => `${name}'s server roles`,
    grantModuleAdministrator: "Grant module administrator",
    revokeModuleAdministrator: "Revoke module administrator",
    grantModuleAdministratorTitle: "Grant module administrator to this user?",
    grantModuleAdministratorConfirm: "They will be able to manage module entitlements and enablement across the deployment.",
    grantedModuleAdministratorToast: "Module administrator granted",
    revokeModuleAdministratorTitle: "Revoke module administrator from this user?",
    revokeModuleAdministratorConfirm: "They will lose access to module management immediately.",
    revokedModuleAdministratorToast: "Module administrator revoked",
    patRevokeAll: "Revoke all Personal Access Tokens platform-wide",
    patRevokeAllHint: (orgPlural: string) => `Incident-response action: revokes every non-revoked Personal Access Token in the deployment, regardless of who owns it or which ${orgPlural.toLowerCase()}(s) it's scoped to.`,
    patRevokeAllTitle: "Revoke every Personal Access Token on the entire platform?",
    patRevokeAllConfirm: "This cannot be undone.",
    patRevokeAllResult: "Revoked {n} token(s) platform-wide.",
    emailTab: "Email",
    testEmail: "Send test email",
    testEmailHint: "Sends a test email using the deployment's configured SMTP settings, so you can confirm outgoing mail actually works.",
    testEmailRecipient: "Recipient email",
    testEmailRecipientHint: "Defaults to your own account when left blank.",
    testEmailSending: "Sending…",
    testEmailSent: "Test email sent — check the inbox (and spam folder) for delivery.",
    // Resource-menu aria-label, matching Org Admin's `orgAdmin.sectionsNav`
    // — Server Admin converted from Tabs to ResourceMenu for cross-page
    // consistency with the other admin-tier pages (docs/decisions.md).
    sectionsNav: "Server management sections",
  },
  reports: {
    title: "Reports",
    generatePdf: "Generate PDF",
    moreFormats: "More formats",
    templateAndLayout: "Template & layout",
    reportTemplate: "Report template",
    noTemplate: "None (plain)",
    chapterLayout: "Chapter layout",
    chapterLayoutAuto: "Auto (recommended)",
    chapterLayoutChaptered: "Chapter per {component}",
    chapterLayoutContinuous: "Continuous",
    filters: "Filters",
    allComponents: "All {components}",
    allCategories: "All {categories}",
    allStatuses: "All statuses",
    keywordFilter: "Keyword",
    includeArchived: "Include archived {requirements}",
    introduction: "Introduction",
    bodyChapters: "Body chapters",
    appendices: "Appendices",
    resourceSections: "Resource sections",
    // Per-report-type content editor (`ReportContentEditor`).
    contentTypes: "Report type",
    typeWithContent: (title: string) => `${title} (has content)`,
    allReports: "All reports",
    allReportsHint:
      "Used by any report type that has no content of its own at this level. A report type's own content always wins over this.",
    typeHint: (title: string) => `Content for the ${title} only.`,
    contentSetFor: (titles: string) => `Content set for: ${titles}.`,
    noContentSet: "No content set at this level.",
    useInherited: "Use inherited",
    nothingInherited: "Nothing is inherited, so the report prints none.",
    inheritedFrom: (name: string) => `Inherited from ${name}`,
    inheritedOrganisation: (name: string) => `Organisation default (${name})`,
    inheritedTemplate: (name: string) => `Template ${name}`,
    inheritedDescription: (name: string) => `${name} description`,
    inheritedPreview: "Inherited content",
    placeholdersTitle: "Placeholders",
    placeholdersHint: "Type these in any text above; they are replaced when the report is generated.",
    placeholderProjectName: "the {project}'s name (the organisation's for organisation-wide reports)",
    placeholderReportTitle: "the title printed on the report",
    placeholderGeneratedOn: "the date it is generated (YYYY-MM-DD)",
    placeholderOrganisation: "the organisation's name",
    reportSetupSaved: "Report setup saved.",
    reportDefaultsSaved: "Report defaults saved.",
    effectiveLoading: "Loading inherited content…",
  },
  files: {
    title: "Files",
    empty: "No files in this {project} yet.",
    columnFilename: "Filename",
    columnOrigin: "Origin",
    columnUploadedBy: "Uploaded by",
    columnUploadedAt: "Uploaded",
    columnSize: "Size",
    sourceRequirementAttachment: "{Requirement} attachment",
    sourceActionAttachment: "Action attachment",
    sourceCommentAttachment: "Comment attachment",
  },
  history: {
    title: "{Project} history",
    since: "Since",
    until: "Until",
    entityType: "Type",
    allEntityTypes: "All types",
    includeComments: "Include discussion comments",
    empty: "No changes in this range.",
  },
  preferences: {
    title: "Preferences",
    searchGroup: "Search",
    searchResetDefault: "Use the built-in default",
    searchIncludeOrgRecords: "Include organisation records when searching a project",
    searchFieldsHint: "Applies to the header search box and to a new search. You can still choose other fields for any one search.",
    // Resource-menu aria-label, matching Org Admin's `orgAdmin.sectionsNav`
    // — Preferences converted from Tabs to ResourceMenu for cross-page
    // consistency with the other admin-tier pages (docs/decisions.md).
    sectionsNav: "Preferences sections",
    theme: "Theme",
    light: "Light",
    dark: "Dark",
    system: "System",
    landing: "Landing page after login",
    landingAuto: "Automatic",
    landingOverview: "{Project} overview list",
    landingProject: "A specific {project}",
    landingProjectSelect: "Which {project}",
    showProjectCode: "Show the project code on record codes",
    defaultProjectScope: "Default list scope",
    defaultProjectScopeHint: "Which {projects} a list covers when you open it in a {project} with parent or child {projects}. You can change it on each list; the choice is remembered per {project}.",
    showProjectCodeHint: "Shows ACME-REQ-001 instead of REQ-001 inside a {project}. Records from another {project} always show it, and so does everything when your organisation requires it.",
    contentWidth: "Content width",
    contentWidthFull: "Full width",
    contentWidthBoxed: "Boxed (centred, capped)",
    save: "Save preferences",
    saved: "Preferences saved.",
    profile: "Profile",
    avatar: "Avatar",
    displayName: "Display name",
    displayNameLocked: (org: string) => `Your display name has been locked by an ${org} admin.`,
    pronouns: "Pronouns",
    emailDigest: "Email notifications",
    digestInstant: "Instant",
    digestDaily: "Daily digest",
    digestNone: "None",
    security: "Security",
    access: "Your access",
    accessHint: (org: string) => `Every ${org} you belong to, your role(s) there, and the projects within it you can see.`,
    myGroups: "Groups",
    inheritedGroup: "via a nested group",
    manageOrganisation: (org: string) => `Manage ${org}`,
    // "Leave organisation" moved here from Org Admin — it's about the current user's own membership,
    // not an org-level setting, so it belongs alongside the rest of "your
    // access" rather than Org Admin's danger-zone-adjacent controls.
    leaveOrg: "Leave",
    // Short, per-row accessible name (distinguishes each org's "Leave"
    // button from every other row's) — the longer explanation is the
    // hover `title` only, not repeated into the accessible name.
    leaveOrgAriaLabel: (orgName: string) => `Leave ${orgName}`,
    leaveOrgTooltip: (orgName: string) => `Remove your own membership in ${orgName}`,
    leaveOrgTitle: (orgName: string) => `Leave ${orgName}?`,
    leaveOrgConfirm: (org: string) =>
      `You'll lose access to every {project} in this ${org} unless an admin adds you back — this can be undone by re-inviting you.`,
    leftOrgToast: (orgCap: string) => `Left ${orgCap.toLowerCase()}`,
    changePassword: "Change password",
    currentPassword: "Current password",
    newPassword: "New password",
    twoFactor: "Two-factor authentication",
    twoFactorEnabled: "Enabled",
    twoFactorDisabled: "Not enabled",
    enable2fa: "Enable 2FA",
    disable2fa: "Disable 2FA",
    scanQrCode: "Scan this QR code with an authenticator app, then enter a code to confirm.",
    confirmCode: "Confirm code",
    authenticatorCode: "Authenticator code",
    enterCodeToDisable: "Enter a current code to disable 2FA.",
    pats: "Personal Access Tokens",
    patsHint: (org: string) => `Long-lived tokens for non-interactive tools (e.g. an MCP server) that shouldn't need re-authenticating every 12 hours. Scoped to the ${org}(s) you choose, and never grant more access than your own account already has.`,
    patName: "Name",
    patNamePlaceholder: "e.g. \"MCP server\"",
    patOrgs: (orgPlural: string) => `${orgPlural} this token can access`,
    patProjects: "Projects",
    patNoProjectsInOrgs: (org: string) => `No projects in the selected ${org}(s).`,
    patProjectsHint: (orgPlural: string) =>
      `Leave all unchecked to allow every {project} in the selected ${orgPlural.toLowerCase()}. Checking any narrows this token to only those {projects}.`,
    patAllProjects: "All {projects}",
    patExpiry: "Expiry",
    patExpiryTooLong: (orgPlural: string) =>
      `Can't be extended past {date} — the longest lifetime the selected ${orgPlural.toLowerCase()}' policies currently allow.`,
    patNew: "New personal access token",
    patCreate: "Create token",
    patCreatedTitle: "Token created",
    patCreatedHint: "Copy this token now — it won't be shown again.",
    patExpires: "Expires",
    patLastUsed: "Last used",
    patNever: "Never used",
    patRevoke: "Revoke",
    patRevokeTitle: "Revoke this token?",
    patRevokeConfirm: "Anything using it will stop working immediately. This cannot be undone.",
    patRevokedToast: "Token revoked",
    patRevokeAll: "Revoke all",
    patRevokeAllTitle: "Revoke every one of your Personal Access Tokens?",
    patRevokeAllConfirm: "This cannot be undone.",
    patRevokedAllToast: "All tokens revoked",
    patNone: "You haven't created any Personal Access Tokens yet.",
    patNoOrgsSelected: (org: string) => `Select at least one ${org}.`,
  },
  actions: {
    title: "Actions",
    recordLabel: "Action",
    newAction: "New action",
    uniqueCode: "ID",
    name: "Title",
    description: "Description",
    actionType: "Type",
    outcome: "Outcome",
    assignee: "Assignee",
    dueDate: "Due date",
    allTypes: "All types",
    allOutcomes: "All outcomes",
    includeArchived: "Include archived",
    empty: "No actions to show.",
    archiveAction: "Archive",
    archived: "Archived",
    archivedToast: "Action archived",
    archiveTitle: "Archive this action?",
    archiveConfirm: "It can no longer be edited afterwards, but stays visible on every {requirement} it's linked to.",
    // No `ConfirmDialog` here, matching `ProjectAdminPage.tsx`'s existing
    // unarchive button (also fires immediately) — reversible again, unlike
    // the Tier-1-confirmed archive action itself.
    restoreAction: "Restore",
    restoredToast: "Action restored",
    completedAt: "Completed",
    created: "Action created",
  },
  // The Compliance module's own strings that live inside core's shared
  // `ResourcePickerModal` — a two-pane dialog for picking a
  // shared file from a source (today just org shared resources) and
  // attaching it to whatever opened the dialog.
  resourcePicker: {
    orgResourcesSource: (orgLabelCap: string) => `${orgLabelCap} shared resources`,
    noFiles: "No files available in this source.",
    attachSelected: (n: number) => (n === 0 ? "Attach selected" : `Attach ${n} selected`),
    linkFromSharedResources: "Link from shared resources",
    attachedToast: (n: number) => (n === 1 ? "1 file linked" : `${n} files linked`),
  },
  recordActivity: {
    title: "Activity",
    loading: "Loading activity…",
    loadError: "Could not load activity.",
    none: "No activity yet.",
    showMore: "Show more",
  },
  artefactLinks: {
    title: "Links",
    asideToggleHide: "Hide links panel",
    asideToggleShow: "Show links panel",
    loading: "Loading links…",
    loadError: "Could not load links.",
    none: "No links yet.",
    untyped: "Linked",
    addLink: "Add link",
    addLinkTitle: "Add a link",
    projectLabel: "{Project}",
    thisProject: "This {project}",
    otherTypeLabel: "Link to",
    otherTypePlaceholder: "Any record type",
    linkTypeLabel: "Relationship",
    searchLabel: "Search",
    searchPlaceholder: "Search by code, name or standard…",
    searchPrompt: "Type at least two characters to search every record type, or choose a record type to list its records.",
    levelAny: (level: string) => `Any ${level.toLowerCase()}`,
    levelFilterLabel: (level: string) => `Filter ${level.toLowerCase()} options`,
    levelTruncated: "Only the first options are shown. Type to filter.",
    targetLabel: "Record",
    targetPlaceholder: "Select a record…",
    noTypes: "No link types are available for this record here.",
    noCandidates: "No matching records.",
    candidatesTruncated: "Only the first matches are shown. Narrow the search to find others.",
    reasonLabel: "Reason for change",
    changeRequestAddNotice:
      "This record is approved and its {project} requires link changes to go through a change request. Submitting creates one for review.",
    submitAdd: "Add link",
    submitAddViaChangeRequest: "Propose link",
    submitCollect: "Add to the request",
    added: "Link added.",
    removed: "Link removed.",
    addFailed: "Could not add this link.",
    removeFailed: "Could not remove this link.",
    removeLabel: (phrase: string, target: string) => `Remove link: ${phrase} ${target}`,
    quick: {
      label: "Link to",
      placeholder: "Search any record by code or title…",
      hint: "Links are added when the record is saved.",
      noMatches: "No matching records.",
      listLabel: "Matching records",
      chosenLabel: "Records to link",
      relationshipLabel: (target: string) => `Relationship to ${target}`,
      removeLabel: (target: string) => `Do not link ${target}`,
      added: (count: number) => `Linked to ${count} ${count === 1 ? "record" : "records"}.`,
      failed: (message: string) =>
        `The record was saved, but its links were not added: ${message} Add them from its Links panel.`,
    },
    groupCount: (count: number) => `${count} ${count === 1 ? "link" : "links"}`,
    removeTitle: "Remove this link?",
    removeConfirm: "The link is removed from both records; the records themselves are unaffected.",
    removeConfirmViaChangeRequest:
      "This record is approved, so removing a link needs a change request. Submitting creates one for review.",
    removeAction: "Remove link",
    removeActionViaChangeRequest: "Request removal",
    archivedBadge: "Archived",
    otherProjectBadge: (name: string) => `In ${name}`,
    notPermitted: "No longer permitted by its link type",
    notPermittedExplanation:
      "This link crosses {projects}, which its link type no longer allows. It is kept; remove it or change the link type's setting.",
    hiddenNote: (count: number) =>
      `${count} linked record${count === 1 ? " is" : "s are"} not shown (no access, in another {project}, or in a module that is off here).`,
    unavailableNote: (count: number) =>
      `${count} linked record${count === 1 ? " cannot" : "s cannot"} be displayed (its module is not installed, or the link is dormant).`,
    truncatedNote: "Some links are not shown because there are too many to list.",
    orgScopedNote: "Links are managed from within a {project}. Open this record from a {project} to add or remove links.",
    supersedeButton: (label: string) => `Supersede another ${label}`,
    supersedeTitle: (label: string) => `Supersede another ${label}`,
    supersedeHelp: (label: string) =>
      `Pick the ${label} this one replaces. It is marked Superseded and linked to this one.`,
    supersedeConfirm: "Supersede",
    supersedeNone: "Nothing to supersede.",
    superseded: "Supersession recorded.",
    supersedeFailed: "Could not record this supersession.",
    traceButton: "Trace",
    viewOptions: "View options",
    viewCompact: "Compact view",
    viewRelationships: "Show relationships",
    viewRelationshipsHint: "Name how each record is linked (Has participant, Raised). The trace always shows them.",
    traceTitle: (label: string) => `Trace: ${label}`,
    traceViewsLabel: "Trace view",
    traceTabTree: "Tree",
    traceTabMap: "Map",
    traceUpstream: "Upstream",
    traceUpstreamHelp: "Where it comes from",
    traceDownstream: "Downstream",
    traceDownstreamHelp: "What depends on it",
    traceRelated: "Related",
    traceRelatedHelp: "Linked without a direction",
    traceFocus: "This record",
    traceEmptyGroup: "None",
    traceLoading: "Loading…",
    traceLoadFailed: "Could not load this branch.",
    traceNothingFurther: "Nothing further in this direction.",
    traceNothingFurtherFor: (label: string) => `Nothing further from ${label} in this direction.`,
    traceMapLoadMoreFailed: "Could not load more links.",
    traceExpand: (label: string) => `Show what is linked beyond ${label}`,
    traceCollapse: (label: string) => `Hide what is linked beyond ${label}`,
    traceHiddenNote:
      "Some linked records are not shown (no access, in another {project}, or in a module that is off here), and are never traced through.",
    traceTruncatedNote: "Some links are not shown because there are too many to list.",
    traceTreeHint: "Open a record's arrow to follow its links further, as deep as you like. Each branch keeps its direction.",
    traceMapHint:
      "Click a record to open it. Hover to light up its links; \"Show more\" follows them further.",
    traceMapLabel: (label: string) => `Map of the records linked to ${label}`,
    traceMapDescription:
      "A layered diagram of linked records: upstream on the left, this record in the centre, downstream on the right, related below. The Tree tab lists the same records.",
    traceMapShowMore: (label: string) => `Show more links of ${label}`,
    traceMapShowMoreChip: "Show more",
    traceMapShowMoreTip: "Read this record's own links and add them to the map",
    traceMapLoadingMore: "Loading…",
    traceMapNoMore: "No more links",
    traceMapEmpty: "This record has no links to draw yet. Add one from the Links panel.",
    traceHideInactive: "Hide inactive records",
    traceHideInactiveHelp:
      "Skips superseded, archived, retired, rejected and withdrawn records, and joins what they link to the record in front of them.",
    traceVia: (labels: string) => `via ${labels}`,
    traceViaDashedEdge: (labels: string) => `Joined through hidden ${labels}`,
    traceLegendJoined: "Joined through a hidden record",
    traceLegendLabel: "Key",
    traceLegendFocus: "This record",
    traceLegendUpstream: "Upstream",
    traceLegendDownstream: "Downstream",
    traceLegendRelated: "Related (no direction)",
    traceLegendArrow: "Arrow points downstream",
    traceLegendElsewhere: "In another {project}",
    traceLegendArchived: "Archived",
    traceMapCapNote: (shown: number, total: number) =>
      `Showing ${shown} of ${total} records. Use the Tree tab, or open a record and trace from there, to reach the rest.`,
    traceMapEdgeLabel: (phrase: string, from: string, to: string) => `${from} ${phrase} ${to}`,
    traceUnclassifiedHint:
      "Most of these links have no direction, so they all appear under Related. An organisation administrator can give a link type a direction (Organisation admin, Projects and workflow, Link types) to fill the Upstream and Downstream views.",
  },
  /** The list scope filter: widening a list to the parent and/or child {projects}. */
  projectScope: {
    label: "Show records from",
    options: {
      this: "This {project}",
      parents: "This + parent {projects}",
      children: "This + child {projects}",
      both: "This + parent and child {projects}",
    },
    widenedHint: "Includes records from related {projects} you can open. Counts cover all of them.",
    fromProject: (name: string) => `From ${name}`,
    coversProjects: (count: number) => `Counts cover ${count} ${count === 1 ? "project" : "projects"}; stage progress is this project's own.`,
  },
  /** Feedback for a mutation run through `useMutation`: "Stage added." / "Could not add the stage." from a verb and a noun. */
  tags: {
    label: "Tags",
    none: "No tags",
    inputPlaceholder: "Add a tag…",
    inputPlaceholderRestricted: "Choose a tag…",
    listLabel: "Matching tags",
    noMatches: "No matching tags.",
    notListed: "That tag is not in the list. Ask a project administrator to add it.",
    createOption: (name: string) => `Add tag "${name}"`,
    removeLabel: (name: string) => `Remove tag ${name}`,
    empty: "Type a tag name.",
    tooLong: (max: number) => `A tag name can be at most ${max} characters.`,
    invalidCharacters: "A tag name cannot contain a comma or semicolon.",
    saveFailed: (message: string) => `Could not save the tags: ${message}`,
    saved: "Tags updated.",
    create: {
      hint: "Optional. Tags are added when the record is saved.",
      failed: (message: string) => `The record was saved, but its tags were not added: ${message} Add them from the record.`,
    },
    filter: {
      label: "Tags",
      any: "Any of these",
      all: "All of these",
      matchLabel: "Match",
      choose: "Choose tags…",
      clear: "Clear tag filter",
      selected: (count: number) => `${count} ${count === 1 ? "tag" : "tags"}`,
      none: "No tags yet.",
    },
    admin: {
      title: "Tags",
      description: "Short labels for any record: a theme, a release, a regulation. Anyone who may edit a record can tag it.",
      orgDescription: "Tags for records the organisation owns (personas, stakeholders, strategies and so on). A project's own records use that project's tags.",
      modeLabel: "Who can add a new tag",
      modeFree: "Anyone who can tag a record",
      modeRestricted: "Only tags listed here",
      modeInherit: "Follow the parent project",
      modeInheritedHint: (mode: string) => `Following the parent project: ${mode}.`,
      inheritedNotice: "These tags belong to a parent project, which manages them. Adding a tag here gives this project a list of its own.",
      addLabel: "New tag",
      addPlaceholder: "Tag name",
      addButton: "Add tag",
      colourLabel: (name: string) => `Colour of ${name}`,
      noColour: "No colour",
      changeColour: (name: string) => `Change colour of ${name}`,
      colourSave: "Save colour",
      colourSaved: "Colour saved.",
      colourHeading: "Colour",
      reclassifyButton: "Reclassify",
      nameHeading: "Tag",
      usedHeading: "Used on",
      lastUsedHeading: "Last used",
      recordsCount: (count: number) => `${count} ${count === 1 ? "record" : "records"}`,
      rename: (name: string) => `Rename ${name}`,
      renameSave: "Save name",
      merge: (name: string) => `Merge ${name} into another tag`,
      mergeTitle: (name: string) => `Merge "${name}"`,
      mergeTarget: "Merge into",
      mergeConfirm: "Merge",
      mergeBody: (name: string, count: number) =>
        `Every record tagged "${name}" (${count}) gets the other tag instead, and "${name}" is deleted.`,
      reclassify: (name: string) => `Reclassify records tagged ${name}`,
      reclassifyTitle: (name: string) => `Reclassify records tagged "${name}"`,
      reclassifyAdd: "Add these tags",
      reclassifyRemove: "Remove these tags",
      reclassifyTypes: "Only these record types",
      reclassifyAllTypes: "All record types",
      reclassifyPreview: "Preview",
      reclassifyApply: "Apply",
      reclassifyForecast: (matched: number, added: number, removed: number) =>
        `${matched} ${matched === 1 ? "record" : "records"} matched: ${added} tag ${added === 1 ? "addition" : "additions"} and ${removed} ${removed === 1 ? "removal" : "removals"}.`,
      reclassifyDone: (matched: number) => `Reclassified ${matched} ${matched === 1 ? "record" : "records"}.`,
      reclassifyNothing: "Choose a tag to add or remove.",
      delete: (name: string) => `Delete ${name}`,
      deleteTitle: (name: string) => `Delete tag "${name}"?`,
      deleteBody: (name: string, count: number) =>
        count === 0
          ? `"${name}" is not used on any record.`
          : `"${name}" is removed from ${count} ${count === 1 ? "record" : "records"}. This cannot be undone.`,
      deleteConfirm: "Delete tag",
      created: "Tag added.",
      renamed: "Tag renamed.",
      merged: (count: number) => `Merged. ${count} ${count === 1 ? "record" : "records"} moved.`,
      deleted: (count: number) => `Tag deleted. It was removed from ${count} ${count === 1 ? "record" : "records"}.`,
      modeSaved: "Tag setting saved.",
      usageHeading: "Where tags are used",
      usageDescription: "One table per kind of record. Tick a tag to hide it from the tables while you review the others.",
      usageEmpty: "No tagged records yet.",
      usageFilter: "Filter tags",
      usageHide: (name: string) => `Hide ${name} from the tables`,
      usageHiddenCount: (count: number) => `${count} hidden`,
      usageShowAll: "Show all",
      unusedHeading: "Not used anywhere",
      loadFailed: "Could not load the tags.",
      inheritedBadge: "Inherited",
    },
  },
  // Field help (`FieldHelp`, style guide "Pattern: field help"): one or two sentences per non-obvious
  // form field saying what it is, what it affects and typical values. A field that explains itself
  // passes `helpNotNeeded` instead. Terminology tokens ({requirement}, {project}) are filled in per
  // organisation like the rest of this table.
  search: {
    // Header box
    boxLabel: "Search",
    placeholder: "Search…",
    submit: "Search",
    openSearch: "Open search",
    closeSearch: "Close search",
    dropdownLabel: "Search results",
    // The live dropdown never says "scope": the footer names the place, in the scope's own label.
    seeAll: (query: string, place: string) => `See all results for ‘${query}’ in ${place}`,
    resultsAnnouncement: (count: number) => (count === 1 ? "1 result" : `${count} results`),
    noResults: "No results",
    tooShort: "Type at least 2 characters to search.",
    timeout: "The search took too long. Narrow the search and try again.",
    rateLimited: "You are searching too fast. Wait a moment and try again.",
    failed: "The search failed. Try again.",
    searching: "Searching…",
    // Scopes
    scopeThisProject: "This project",
    scopeAllProjects: "All projects",
    scopeThisStandard: "This standard",
    // Page
    pageTitle: "Search",
    pageHeading: (query: string) => `Results for ‘${query}’`,
    queryLabel: "Search text",
    filters: "Filters",
    scope: "Scope",
    organisation: "Organisation",
    allOrganisations: "All organisations",
    recordType: "Record type",
    allTypes: "All types",
    project: "Project",
    allProjects: "All projects",
    status: "Status",
    anyStatus: "Any status",
    includeArchived: "Include archived and retired",
    includeOrgRecords: "Include organisation records",
    updatedFrom: "Updated from",
    updatedTo: "Updated to",
    searchIn: "Search in",
    match: "Match",
    matchContains: "Contains all the words",
    matchPhrase: "Exact phrase",
    sort: "Sort by",
    sortRelevance: "Relevance",
    sortUpdated: "Most recently updated",
    clearFilters: "Clear filters",
    total: (count: number, capped: boolean) => (capped ? `${count}+ results` : count === 1 ? "1 result" : `${count} results`),
    showing: (from: number, to: number) => `Showing ${from}–${to}`,
    previousPage: "Previous page",
    nextPage: "Next page",
    depthLimit: "Only the first 500 results can be shown. Refine the search to narrow them.",
    notSearched: (labels: string) => `Not searched: ${labels} (no selected field)`,
    projectsTruncated: "You can open more projects than one search covers; narrow the search to a project to reach the rest.",
    emptyTitle: "Nothing found",
    emptyHint: "Try other words, widen the scope, clear filters, or search more fields.",
    startHint: "Type at least 2 characters to search records across your projects.",
    updated: (when: string) => `Updated ${when}`,
    archivedBadge: "Archived",
    inProject: (name: string) => `in ${name}`,
    inOrganisation: "Organisation record",
    matchedIn: (field: string) => `Matched in ${field}`,
    typeCount: (label: string, count: number, capped: boolean) => `${label} (${capped ? `${count}+` : count})`,
    // Field picker
    fieldsLabel: "Fields searched",
    fieldsFilterLabel: "Search fields",
    fieldsUnavailable: (labels: string) => `No longer available: ${labels}.`,
    fieldsEmpty: "ID and Title",
    fieldCarriedBy: (types: string) => `(${types})`,
    slowFieldHint: "(slower: reads every discussion)",
    fieldPickerSummaryLimit: 3,
  },
  help: {
    // Server Management → Add user
    addUserOrganization: "The organisation the new person joins. Leave it as none for an account that belongs to no organisation yet.",
    // Requirements and change requests
    requirementLevel: "How binding the {requirement} is: a Requirement must be met, a Recommended one should be met unless there is a reason not to, and an Optional one is nice to have.",
    requirementTargetVersion: "The release this {requirement} is planned for. Leave it empty while that is undecided.",
    requirementClarification: "Extra detail that explains how to read or apply the {requirement} without changing what it requires, such as an interpretation or an example.",
    requirementReviewDate: "When this {requirement} is next due to be checked that it is still right. A review that falls due notifies the assigned reviewer.",
    requirementReminderLead: "How many days before the review date the assigned reviewer is reminded, for example 14.",
    requirementReviewer: "The person or group who carries out the periodic review of this {requirement} and is notified when it falls due.",
    requirementPrefix: "A short code that starts the identifiers of everything under it, for example SW in SW-PERF-014.",
    // Reports
    reportBrandingTemplate: "The branding applied to the export: logo, colours, cover page and footer. Leave it unset to use the default.",
    reportChapterLayout: "Whether the report starts a new chapter for each {component} or runs on continuously. Automatic follows the chosen template.",
    reportChapterDefault: "New reports start a chapter for each {component} unless the person exporting chooses a continuous layout.",
    // Search
    searchIncludeOrgRecords: "When you search one project, also look in the records your organisation owns and shares with every project (a shared Strategy, say). A project that has the feature switched off never shows them. You can change this for any one search from the search page.",
    searchDefaultFields: "Which fields the header search and a new search look in. ID and Title are always included. You can still change the fields for any one search from the search page.",
    // Project and organisation codes
    orgCode: "A short code for this organisation, used to qualify the codes of organisation-level records (for example ACME-PER-001). Letters and digits only, and different from every project code.",
    projectCode: "The short code that qualifies this {project}'s record codes outside it (for example ACME-REQ-001). It must be unique in the organisation and follow the organisation's code rules.",
    codeCharacters: "Which characters a project code may use: letters only, digits only, or both.",
    codeShortest: "The shortest a project code may be. The limits apply to codes set from now on; existing codes are never rewritten.",
    codeLongest: "The longest a project code may be. The limits apply to codes set from now on; existing codes are never rewritten.",
    codeAssignment: "Automatic generates a code from the {project}'s name when it is created; manual asks the person creating it to type one.",
    // Scoring
    scoringModel: "The formula that combines the scoring axes (for example likelihood and consequence) into one score and band.",
    scoringDefaultModel: "The scoring model used for new scores in this {project} when none is chosen. The model decides how the axes combine into one score.",
    scoringRollup: "How several scores become one number: a weighted average uses each score's weight, worst case takes the highest, and a plain average ignores weights.",
    // Organisation and server administration
    ssoEnable: "Lets members sign in through the organisation's identity provider (OpenID Connect). Fill in the issuer and client details first.",
    ssoNativeFormHidden: "Removes the email and password form from the organisation's login page so people can only sign in through SSO. Check that SSO works first, or nobody can sign in.",
    ssoIssuerUrl: "The base URL of your identity provider, the address that serves /.well-known/openid-configuration, for example https://login.example.com/realms/acme.",
    ssoClientId: "The identifier your identity provider assigned to this application.",
    ssoClientSecret: "The secret your identity provider issued for this application.",
    ssoGroupSync: "Keeps this group's members in step with a group at the identity provider each time someone signs in through SSO.",
    ssoGroupName: "The name of the identity-provider group whose members this group mirrors.",
    customRoleScope: "Where the role can be granted: across the organisation, within one {project}, or on the records of one kind in a module.",
    externalUserPolicy: "Whether people from outside the organisation can be added to projects: nobody, only people whose email is on the organisation's domain, or anyone.",
    moduleEntitlementPolicy: "Whether organisations may use a module when the server has no setting for that organisation. Choose the default that suits new organisations.",
    // Projects
    projectAllowMemberChangeRequests: "When on, ordinary members can submit {changeRequests}; when off, only managers can.",
    projectUsableAsTemplate: "Lets people create new {project}s from this one, copying its structure.",
    projectParent: "Places this {project} under another so the two can share settings and see each other's records, subject to each person's access.",
    projectInheritAccess: "When on, people who have access to the parent {project} also get access here, with the same role.",
    projectRoleToMirror: "Only people who hold this role on the parent are given access here. Leave it on all roles to mirror everyone.",
    // Links and tags
    linkRelationship: "How the two records are connected. The choices depend on the kinds of record being linked.",
    tagMergeInto: "Moves every use of this tag onto the target tag, then removes this one.",
  },
  mutation: {
    past: {
      add: "added", save: "saved", remove: "removed", delete: "deleted", rename: "renamed", move: "moved", update: "updated",
      upload: "uploaded", send: "sent", archive: "archived", restore: "restored", revoke: "revoked", grant: "granted",
      create: "created", start: "started", approve: "approved", complete: "completed", respond: "recorded", reset: "reset",
      enable: "enabled", disable: "disabled", link: "linked", unlink: "unlinked", post: "posted", edit: "edited", change: "changed",
      confirm: "confirmed", set: "set", clear: "cleared", mark: "marked", unban: "unbanned", reactivate: "reactivated", join: "joined",
      toggle: "updated", submit: "submitted", cast: "recorded", generate: "generated",
    },
    success: (noun: string, past: string) =>
      `${noun.replace(/^\{?\w/, (head) => head.toUpperCase())} ${past}.`,
    failure: (verb: string, noun: string) => `Could not ${verb} the ${noun}.`,
  },
  common: {
    requiredLegend: "* required",
    hexCode: (field: string) => `${field} (hex code)`,
    hexCodeInvalid: "Enter a colour as #rgb or #rrggbb.",
    loading: "Loading…",
    error: "Something went wrong.",
    cancel: "Cancel",
    back: "Back",
    create: "Create",
    delete: "Delete",
    edit: "Edit",
    save: "Save",
    saveAndActivate: "Save and activate",
    up: "Move up",
    down: "Move down",
    yes: "Yes",
    no: "No",
    loadMore: "Load more",
    copy: "Copy",
    close: "Close",
    remove: "Remove",
    platformDefault: "Platform default",
    customValue: "Custom",
    resetToPlatformDefault: "Reset to platform default",
    chooseFile: "Choose file",
    fieldHelp: (label: string) => `Help: ${label}`,
    nSelected: (count: number) => `${count} selected`,
    filterOptions: (label: string) => `Filter ${label}`,
    filterPlaceholder: "Filter…",
    noMatchingOptions: "Nothing matches.",
    selectOption: "Select…",
    typeToConfirmLabel: (name: string) => `Type "${name}" to confirm`,
    // `SplitButtonTrigger`'s chevron affordance (style guide "Pattern:
    // split-button trigger") — generic across every call site, not
    // per-instance, since the chevron's own job ("reveal the alternatives")
    // doesn't change with what those alternatives are.
    moreOptions: "More options",
    // `ResultCount` — generic across every list
    // page that uses it, same reasoning as `moreOptions` above.
    resultCountTotal: (total: number) => `${total} total`,
    resultCountMatching: (matching: number, total: number) => `Showing ${matching} matching · ${total} total`,
    // `FilterPanel`'s collapsible filter body —
    // below the mobile breakpoint it's a `CollapsibleSection` titled this.
    filters: "Filters",
    showMore: "More",
    showLess: "Less",
    // `ModuleSettingsList`'s collapsed sub-component disclosure.
    moduleComponentsSummary: (count: number) => `${count} component${count === 1 ? "" : "s"}`,
  },
};

export type Strings = typeof en;

const locales: Record<string, Strings> = { en };

/** Returns the string table for a locale, defaulting to English. */
export function t(locale = "en"): Strings {
  return locales[locale] ?? en;
}
