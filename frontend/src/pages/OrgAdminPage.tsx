import { Download, Eye, Lock, Pencil, Plus, Send, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import type {
  AssignByEmailOutcome,
  EffectiveMember,
  ExternalUserPolicy,
  FileAsset,
  LinkTypeDefinition,
  MaterializeResult,
  MergeConflict,
  ModuleRoleDefinition,
  OrgAdvancedSettings,
  OrgGroup,
  OrgModule,
  OrgMergePreviewResult,
  OrgMergeResult,
  OrgPendingInvite,
  OrgPersonalAccessToken,
  OrgProjectSummary,
  OrgReportDefaults,
  OrgRole,
  OrgSsoConfig,
  OrgUser,
  Organization,
  OutsideDomainUser,
  PendingInvite,
  ProjectListItem,
  ProjectRole,
  ProjectStatusDefinition,
  ReportChapter,
  ReportTemplate,
  ScimTokenCreated,
  ScimTokenStatus,
  UserAccess,
} from "../api/types";
import { collapseProjectRoles, ORG_ROLE_LABEL, PENDING_INVITE_STATUS_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { AddToGroupControl } from "../components/AddToGroupControl";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DefinitionList } from "../components/DefinitionList";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { FileUploadTrigger } from "../components/FileUploadTrigger";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { ImportConflictPanel } from "../components/ImportConflictPanel";
import { Modal } from "../components/Modal";
import { MultiSelectDropdown } from "../components/MultiSelectDropdown";
import { OverridePill } from "../components/OverridePill";
import { ProjectMembersTable } from "../components/ProjectMembersTable";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { RichTextEditor } from "../components/RichTextEditor";
import { SidePanel } from "../components/SidePanel";
import { cycleSort, type SortState } from "../components/SortableHeader";
import { Spinner } from "../components/Spinner";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { downloadBlob } from "../utils/download";
import { defaultResolutions } from "../utils/mergeConflicts";

/**
 * The 7 resource-menu groups Org Admin's previous 15 flat accordions were
 * regrouped into (2026-08 UX audit, style guide "Pattern: settings
 * hierarchy" — see its "after" diagram). Each key is also the route
 * segment under `/orgs/:orgId/admin/:group?` (App.tsx), so a group
 * selection is a real navigation, not client-only state: back/forward and
 * a bookmark to one specific group both work. An unrecognised or absent
 * `:group` (including the bare `/orgs/:orgId/admin` used by every existing
 * link into this page) falls back to "overview".
 *
 * "people" (Users and Groups combined in one panel) was later split into
 * its own two top-level groups, "users" and "groups" — a flat regroup per
 * the style guide's settings-hierarchy addendum, not a new navigation
 * capability (`ResourceMenu` already renders any number of flat groups).
 * "integrations-security" was later split the same way, into "oauth-sso"
 * (SSO/OIDC + SCIM — both identity-provisioning integrations, grouped
 * together rather than splitting SCIM into "security"), "email" (SMTP +
 * test email), and "security" (2FA/self-signup/external-user policy, plus
 * Personal Access Tokens — see `docs/decisions.md` for the SCIM placement
 * call).
 */
type OrgAdminGroupKey =
  | "overview"
  | "users"
  | "groups"
  | "projects-workflow"
  | "branding-defaults"
  | "templates-reports"
  | "oauth-sso"
  | "email"
  | "security"
  | "modules";

/** One row of the Org Users `DirectoryTable` (Phase A, follow-up UX batch)
 * — a real user or a not-yet-accepted org-only invite, merged client-side.
 * Same `kind`-discriminated union row-merge pattern `ProjectMembersTable`
 * (Phase D) later applied one level down, for a project's own members. */
type UsersRow = { kind: "user"; user: OrgUser } | { kind: "invited"; invite: OrgPendingInvite };

const ORG_ADMIN_GROUP_KEYS: OrgAdminGroupKey[] = [
  "overview",
  "users",
  "groups",
  "projects-workflow",
  "branding-defaults",
  "templates-reports",
  "oauth-sso",
  "email",
  "security",
  "modules",
];

/**
 * Organisation administration: users (C-U-01), groups (C-U-08), shared
 * resource files (C-M-03), the organisation logo (U-C-02), the default
 * template project used for new projects (C-E-04), the org's definable
 * project statuses (Project Statuses section — the status list every
 * project in this org picks from), and the org's definable, bidirectional
 * requirement link types (Link Types section — each type stores both a
 * forward and reverse display name, since a link renders differently
 * depending on which requirement it's viewed from; see
 * `docs/decisions.md`). Both of the latter two share the same
 * rename/reorder/delete-with-reassignment contract as custom fields, with
 * one addition: deleting a status/link type currently in use 409s with a
 * server-supplied count, at which point a reassignment picker (rather than
 * a plain confirm) lets the admin move existing references to another
 * status/type before the delete retries.
 */
export function OrgAdminPage() {
  const strings = useStrings();
  const { orgId, group: groupParam } = useParams<{ orgId: string; group?: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
  const [org, setOrg] = useState<Organization | null>(null);
  const [orgNameEdit, setOrgNameEdit] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  // Rename now opens in a `Modal` from the Overview group's `ActionMenu`
  // (style guide "Pattern: action menu") rather than an always-visible
  // inline input.
  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [degradedOrgName, setDegradedOrgName] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [enableError, setEnableError] = useState<string | null>(null);
  const [enabling, setEnabling] = useState(false);
  const [bootstrapEmail, setBootstrapEmail] = useState("");
  const [bootstrapName, setBootstrapName] = useState("");
  const [bootstrapPassword, setBootstrapPassword] = useState("");
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [bootstrapCreated, setBootstrapCreated] = useState(false);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [userSearch, setUserSearch] = useState("");
  const [viewingUser, setViewingUser] = useState<OrgUser | null>(null);
  // "Remove from {org}" (Users table Actions column, PR6) — the user
  // pending confirmation in the `ConfirmDialog` below, or null when none.
  const [confirmRemoveUser, setConfirmRemoveUser] = useState<OrgUser | null>(null);
  const [userAccess, setUserAccess] = useState<UserAccess | null>(null);
  const [userAccessError, setUserAccessError] = useState<string | null>(null);
  // "View access" panel (2026-08 UX audit reversal — see docs/decisions.md
  // and docs/ux-style-guide.md's "Pattern: role display" section): each
  // project row shows `collapseProjectRoles()`'s summary by default, with
  // this per-project-id set tracking which rows the viewer has explicitly
  // expanded to the full, uncollapsed role list. Reset whenever a new
  // user's access is opened so expansion never leaks between users.
  const [expandedAccessProjectIds, setExpandedAccessProjectIds] = useState<Set<string>>(new Set());
  const [groups, setGroups] = useState<OrgGroup[]>([]);
  const [groupsTotal, setGroupsTotal] = useState(0);
  const [groupSearch, setGroupSearch] = useState("");
  // Every org group by id/name, unpaginated and unfiltered by
  // `groupSearch` — the paginated/searched `groups` above drives which
  // groups render as full cards (2026-08 UX audit "Directories at
  // scale"), but nesting a group into another needs to pick from *every*
  // group in the org regardless of what's currently searched/paged, so
  // the nested-group name resolution and the "add nested group" dropdown
  // both read from this instead.
  const [allGroups, setAllGroups] = useState<OrgGroup[]>([]);
  // Org Groups table (Phase B, follow-up UX batch, 2026-08-31): replaces
  // the old `CollapsibleSection`-of-`CollapsibleSection`s accordion with
  // `DirectoryTable` + a per-row `SidePanel`, the same shape Project
  // Groups already used before this phase also retrofitted it onto
  // `DirectoryTable`. `list_org_groups` already pages via `limit`/`offset`,
  // so Name sort is a backend-sorted refetch (its new `order` param) like
  // Org Users' own table, not a client-side sort of only the loaded page —
  // style guide "Pattern: sortable column header"'s "already paginated ->
  // backend sort/order params" branch (Members has no natural order at
  // all, so it stays unsorted rather than needing a param of its own).
  type OrgGroupSortKey = "name";
  const [groupSort, setGroupSort] = useState<SortState<OrgGroupSortKey> | null>(null);
  const [openOrgGroupId, setOpenOrgGroupId] = useState<string | null>(null);
  // Per-group SSO-sync enable/disable toggle (Phase B bug-fix pass) —
  // `undefined` means "not yet touched this session," in which case the
  // checkbox's displayed state derives from `idp_synced_group_name != null`
  // instead. Unchecking clears both synced fields immediately via the same
  // `PATCH` the "Save sync settings" button already uses (see
  // `toggleGroupSync` below) — no backend schema change needed.
  const [syncEnabledEdits, setSyncEnabledEdits] = useState<Record<string, boolean>>({});
  const [resources, setResources] = useState<FileAsset[]>([]);
  const [templateProjects, setTemplateProjects] = useState<ProjectListItem[]>([]);

  // --- Project statuses (C-G-XX) ---------------------------------------
  const [projectStatuses, setProjectStatuses] = useState<ProjectStatusDefinition[]>([]);

  // --- Requirement link types (C-G-09) ---------------------------------
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[]>([]);

  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState<OrgRole>("member");
  // "New user" now opens in a `Modal` (style guide "Pattern: modal dialog
  // for entity create/rename") rather than the permanently-visible inline
  // form it used to be — the first real usage of that pattern, setting the
  // shape items 521/519 (New Project/New Organisation, org rename) follow.
  const [newUserModalOpen, setNewUserModalOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupModalOpen, setNewGroupModalOpen] = useState(false);

  const [advanced, setAdvanced] = useState<OrgAdvancedSettings | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [testEmailRecipient, setTestEmailRecipient] = useState("");
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  const [testEmailError, setTestEmailError] = useState<string | null>(null);
  const [testEmailSuccess, setTestEmailSuccess] = useState(false);
  const [advancedError, setAdvancedError] = useState<string | null>(null);
  // Module system Phase 1 (compliance-module-plan.md): the org's own
  // enable/disable choice among modules it's entitled to. Fetched inside
  // the same try/catch-403-and-hide-section block as `advanced` above
  // (non-admins simply don't see the section) — `[]` before that resolves,
  // which also correctly renders as "no modules" for a deployment with
  // none registered yet (there are zero implemented modules until Phase 5).
  const [modules, setModules] = useState<OrgModule[]>([]);
  // Module system Phase 2: org-scoped module-contributed role definitions
  // currently available to grant in this org, fed into the Users table's
  // Roles column `MultiSelectDropdown` alongside the three fixed `OrgRole`
  // options. Fetched in the same block as `modules` above (both non-admin-
  // hidden, both need this org's own module registry state) — `[]` before
  // that resolves, which also correctly renders as "no module roles" for a
  // deployment with none registered yet (no module has any roles until
  // Phase 5).
  const [availableOrgModuleRoles, setAvailableOrgModuleRoles] = useState<ModuleRoleDefinition[]>([]);
  // Same, but project-scoped — for the "manage users" modal's own
  // `ProjectMembersTable`, keyed by whichever project that modal currently
  // has open (see `openManageUsers` below).
  const [manageUsersAvailableModuleRoles, setManageUsersAvailableModuleRoles] = useState<ModuleRoleDefinition[]>([]);
  // Users table filters (Phase A, follow-up UX batch, 2026-08-31): the
  // three access-review filters used to be a single-select "" | "stale" |
  // "no2fa" | "noaccess" toggle-button row (mutually exclusive, so e.g.
  // "stale AND no 2FA" couldn't be expressed even though the backend's
  // `stale_since_days`/`has_2fa`/`has_project_access` params are fully
  // independent) — migrated onto `FilterCheckbox`es inside the shared
  // `FilterPanel`, one boolean each, now genuinely independent. `roleFilter`
  // is new: `GET /orgs/{id}/users`'s existing `org_role` param had no
  // frontend control wired up to it before this phase.
  const [userFilterStale, setUserFilterStale] = useState(false);
  const [userFilterNo2fa, setUserFilterNo2fa] = useState(false);
  const [userFilterNoAccess, setUserFilterNoAccess] = useState(false);
  const [userRoleFilter, setUserRoleFilter] = useState<OrgRole | "">("");
  // Pending (unaccepted) org-only invites, merged into the Users table as
  // `kind: "invited"` rows (Phase A) — fetched unpaginated (there are
  // never many at once) alongside the paginated `users` list, and always
  // rendered ahead of it regardless of the user rows' own sort/page state.
  const [orgInvites, setOrgInvites] = useState<OrgPendingInvite[]>([]);
  const [showInvitedUsers, setShowInvitedUsers] = useState(true);
  const [resendingOrgInviteId, setResendingOrgInviteId] = useState<string | null>(null);
  const [inviteUserModalOpen, setInviteUserModalOpen] = useState(false);
  const [inviteUserEmail, setInviteUserEmail] = useState("");
  // Column-header sorting (2026-08 UX audit roadmap) — backend `sort`/
  // `order`, same reasoning as the Requirements/Change Requests lists:
  // this table is backend-paginated (`USERS_PAGE_SIZE`/`LoadMoreButton`
  // below), so sorting has to be honoured server-side.
  type OrgUserSortKey = "display_name" | "email" | "last_login_at";
  const [userSort, setUserSort] = useState<SortState<OrgUserSortKey> | null>(null);
  const [patMaxLifetimeDays, setPatMaxLifetimeDays] = useState("");
  const [require2fa, setRequire2fa] = useState(false);
  const [allowSelfSignup, setAllowSelfSignup] = useState(false);
  const [autoAcceptEmailDomain, setAutoAcceptEmailDomain] = useState("");
  const [externalUserPolicy, setExternalUserPolicy] = useState<ExternalUserPolicy>("disabled");
  const [allowRelaxedChildProjectCreation, setAllowRelaxedChildProjectCreation] = useState(true);
  // Guards the advanced-settings form fields above against `reload()` —
  // called after every unrelated mutation on this page (e.g.
  // `toggleDisplayNameLock`) and not awaited by its caller, so it can
  // still be mid-flight when the user edits and saves this form right
  // after triggering one of those other actions. Without this, a slow
  // `reload()`'s own advanced-settings fetch resolving *after* the user's
  // edit clobbers it back to the last-saved value before Save is even
  // clicked — a real (CI-reproducible, native-fast-machine-invisible)
  // race, not a test timing issue; see org-security-controls.spec.ts's
  // own comment and docs/decisions.md. Set on every field's onChange,
  // cleared once `saveAdvanced` succeeds (so a later, legitimate reload
  // can resume populating the form again).
  const advancedDirtyRef = useRef(false);
  const [outsideDomainUsers, setOutsideDomainUsers] = useState<OutsideDomainUser[] | null>(null);
  const [outsideDomainError, setOutsideDomainError] = useState<string | null>(null);
  const [orgPats, setOrgPats] = useState<OrgPersonalAccessToken[]>([]);
  const [patBulkResult, setPatBulkResult] = useState<string | null>(null);
  // ConfirmDialog (Tier 1) state for the three PAT actions below — converted
  // from `window.confirm` per the sixth-pass audit's "Confirmation and
  // feedback rollout, precisely" list.
  const [patToDescope, setPatToDescope] = useState<string | null>(null);
  const [revokeAllPatsOpen, setRevokeAllPatsOpen] = useState(false);
  const [patToRevoke, setPatToRevoke] = useState<string | null>(null);
  const [orgProjects, setOrgProjects] = useState<OrgProjectSummary[] | null>(null);
  // "Manage users" (Phase 5, docs/decisions.md; rebuilt again in Phase D,
  // follow-up UX batch, 2026-08-31): the old inline expand-in-place
  // (`expandedProjectId`/`expandedProjectGroups`/`toggleExpandedProject`/
  // `addExpandedProjectGroupMember`/`removeExpandedProjectGroupMember`) is
  // now a `Modal` wrapping the same `ProjectMembersTable`
  // `ProjectAdminPage.tsx`'s own Members section uses — literally the same
  // component, not a duplicate, worse reimplementation (the concrete
  // complaint this phase fixes). `manageUsersProjectId` is which project's
  // modal is open (`null` = closed); its effective-members/pending-invites
  // are fetched fresh on open, the same two endpoints `ProjectAdminPage.tsx`
  // itself uses.
  const [manageUsersProjectId, setManageUsersProjectId] = useState<string | null>(null);
  const [manageUsersProjectName, setManageUsersProjectName] = useState("");
  const [manageUsersMembers, setManageUsersMembers] = useState<EffectiveMember[]>([]);
  const [manageUsersInvites, setManageUsersInvites] = useState<PendingInvite[]>([]);
  const [manageUsersResendingInviteId, setManageUsersResendingInviteId] = useState<string | null>(null);
  const [manageUsersAddRole, setManageUsersAddRole] = useState<ProjectRole>("member");
  // Style guide "Pattern: modal dialog for entity create/rename" (Principle
  // 3) — the inline add-member sub-form used to render permanently inside
  // this outer "Manage users" Modal; it's now a button that opens a second,
  // nested Modal (`useDialogA11y`'s own docstring explains why a nested
  // Modal's Escape/focus handling is already safe here). The outer Modal
  // remains the right container for "manage users for this project" as a
  // whole — only the always-visible add sub-form within it is modal-ified.
  const [manageUsersAddMemberModalOpen, setManageUsersAddMemberModalOpen] = useState(false);

  const [ssoConfig, setSsoConfig] = useState<OrgSsoConfig | null>(null);
  const [slugInput, setSlugInput] = useState("");
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ssoOnly, setSsoOnly] = useState(false);
  const [oidcIssuerUrl, setOidcIssuerUrl] = useState("");
  const [oidcClientId, setOidcClientId] = useState("");
  const [oidcClientSecret, setOidcClientSecret] = useState("");
  const [oidcRequiredGroup, setOidcRequiredGroup] = useState("");
  const [ssoError, setSsoError] = useState<string | null>(null);

  const [scimStatus, setScimStatus] = useState<ScimTokenStatus | null>(null);
  const [scimGeneratedToken, setScimGeneratedToken] = useState<string | null>(null);
  const [scimError, setScimError] = useState<string | null>(null);

  const [orgReportDefaultsAvailable, setOrgReportDefaultsAvailable] = useState(false);
  const [orgReportIntro, setOrgReportIntro] = useState("");
  const [orgReportChapters, setOrgReportChapters] = useState<ReportChapter[]>([]);
  const [orgReportAppendices, setOrgReportAppendices] = useState<ReportChapter[]>([]);

  const [reportTemplates, setReportTemplates] = useState<ReportTemplate[]>([]);
  const [newTemplateName, setNewTemplateName] = useState("");
  const [newTemplateAccentColor, setNewTemplateAccentColor] = useState("#475569");
  const [newTemplateIncludeCoverPage, setNewTemplateIncludeCoverPage] = useState(true);
  const [newTemplateIncludeLogo, setNewTemplateIncludeLogo] = useState(true);
  const [newTemplateFooterText, setNewTemplateFooterText] = useState("");
  const [newTemplateIntro, setNewTemplateIntro] = useState("");
  const [newTemplateChapters, setNewTemplateChapters] = useState<ReportChapter[]>([]);
  const [newTemplateAppendices, setNewTemplateAppendices] = useState<ReportChapter[]>([]);
  const [newTemplateChaptersPerComponent, setNewTemplateChaptersPerComponent] = useState(true);
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  // The create/edit form for a report template is a brand-new (or, when
  // editing, an existing) entity's full field set, not contextual detail
  // about anything already on screen — per the revised Principle 3 it
  // opens in a `Modal`, not a permanently-visible nested accordion.
  const [templateFormOpen, setTemplateFormOpen] = useState(false);

  const [useOwnAccentColor, setUseOwnAccentColor] = useState(false);
  const [accentColorInput, setAccentColorInput] = useState("#475569");
  const [headerTitleInput, setHeaderTitleInput] = useState("");
  const [emailFooterCompanyNameInput, setEmailFooterCompanyNameInput] = useState("");
  const [emailFooterWebsiteInput, setEmailFooterWebsiteInput] = useState("");
  const [emailFooterAddressInput, setEmailFooterAddressInput] = useState("");
  const [brandingError, setBrandingError] = useState<string | null>(null);

  const USERS_PAGE_SIZE = 30;
  const GROUPS_PAGE_SIZE = 20;

  interface UserFilters {
    stale: boolean;
    no2fa: boolean;
    noAccess: boolean;
    role: OrgRole | "";
  }

  function currentUserFilters(): UserFilters {
    return { stale: userFilterStale, no2fa: userFilterNo2fa, noAccess: userFilterNoAccess, role: userRoleFilter };
  }

  async function loadUsers(
    filters: UserFilters, search: string, offset: number, append: boolean, sort: typeof userSort = userSort
  ) {
    if (!orgId) return;
    function query(includeFilter: boolean) {
      const params = new URLSearchParams({ limit: String(USERS_PAGE_SIZE), offset: String(offset) });
      if (includeFilter) {
        if (filters.stale) params.set("stale_since_days", "180");
        if (filters.no2fa) params.set("has_2fa", "false");
        if (filters.noAccess) params.set("has_project_access", "false");
        if (filters.role) params.set("org_role", filters.role);
      }
      if (search) params.set("search", search);
      if (sort) {
        params.set("sort", sort.key);
        params.set("order", sort.direction);
      }
      return params.toString();
    }
    try {
      const page = await api.getPage<OrgUser>(`/api/v1/orgs/${orgId}/users?${query(true)}`);
      setUsers((prev) => (append ? [...prev, ...page.items] : page.items));
      setUsersTotal(page.total);
    } catch (err) {
      // Non-admins get 403 on filtered queries; fall back to the plain
      // list (search/pagination alone stay available to them either way).
      if (err instanceof ApiError && err.status === 403) {
        const page = await api.getPage<OrgUser>(`/api/v1/orgs/${orgId}/users?${query(false)}`);
        setUsers((prev) => (append ? [...prev, ...page.items] : page.items));
        setUsersTotal(page.total);
      } else {
        throw err;
      }
    }
  }

  /** Pending org-only invites (Phase A) — gated at org-admin/server-admin
   * tier server-side (same as `create_org_user`), so a plain member simply
   * sees none rather than an error; every other 403 still surfaces. */
  async function loadOrgInvites() {
    if (!orgId) return;
    try {
      setOrgInvites(await api.get<OrgPendingInvite[]>(`/api/v1/orgs/${orgId}/pending-invites`));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setOrgInvites([]);
      } else {
        throw err;
      }
    }
  }

  async function loadGroups(
    search: string, offset: number, append: boolean, sort: typeof groupSort = groupSort
  ) {
    if (!orgId) return;
    const params = new URLSearchParams({ limit: String(GROUPS_PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (sort) params.set("order", sort.direction);
    const page = await api.getPage<OrgGroup>(`/api/v1/orgs/${orgId}/groups?${params.toString()}`);
    setGroups((prev) => (append ? [...prev, ...page.items] : page.items));
    setGroupsTotal(page.total);
  }

  async function reload() {
    if (!orgId) return;
    // Reaching this page at all doesn't imply membership in this specific
    // organisation — a server admin can see every org listed under Server
    // Management without holding any role in most of them (I-M-05: server
    // admin access is tenancy-wide, not content-wide), and a stale link/
    // bookmark can point at an org whose membership has since changed.
    // Every call below requires at least `member`, so this bundle 403s as
    // a whole for exactly that case — caught here so it surfaces as a
    // real message instead of leaving `org` unset and the page spinning
    // forever (its loading gate is just `if (!org) return <Spinner />`).
    let o: Organization, allG: OrgGroup[], r: FileAsset[], projects: ProjectListItem[], templates: ReportTemplate[];
    let statuses: ProjectStatusDefinition[], linkTypeList: LinkTypeDefinition[];
    try {
      [o, allG, r, projects, templates, statuses, linkTypeList] = await Promise.all([
        api.get<Organization>(`/api/v1/orgs/${orgId}`),
        // Unpaginated — nested-group name resolution and the "add nested
        // group" dropdown both need every group in the org regardless of
        // the Groups section's own search/page state (see `allGroups`).
        api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`),
        api.get<FileAsset[]>(`/api/v1/orgs/${orgId}/resources`),
        api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
        api.get<ReportTemplate[]>(`/api/v1/orgs/${orgId}/report-templates`),
        api.get<ProjectStatusDefinition[]>(`/api/v1/orgs/${orgId}/project-statuses`),
        api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${orgId}/link-types`),
      ]);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : strings.common.error);
      // `GET /orgs/{id}` alone has its own server-admin bypass (unlike the
      // group/resource/template calls above, which is exactly why the
      // bundle as a whole just failed) — best-effort fetch here so the
      // degraded view below can at least show which org this is.
      try {
        setDegradedOrgName((await api.get<Organization>(`/api/v1/orgs/${orgId}`)).name);
      } catch {
        setDegradedOrgName(null);
      }
      return;
    }
    setLoadError(null);
    setDegradedOrgName(null);
    setOrg(o);
    setOrgNameEdit(o.name);
    setUseOwnAccentColor(o.accent_color_hex != null);
    setAccentColorInput(o.accent_color_hex ?? "#475569");
    setHeaderTitleInput(o.header_title ?? "");
    setEmailFooterCompanyNameInput(o.email_footer_company_name ?? "");
    setEmailFooterWebsiteInput(o.email_footer_website ?? "");
    setEmailFooterAddressInput(o.email_footer_address ?? "");
    setAllGroups(allG);
    setResources(r);
    setTemplateProjects(projects.filter((p) => p.is_template && p.organization_id === orgId));
    setReportTemplates(templates);
    setProjectStatuses(statuses);
    setLinkTypes(linkTypeList);
    await Promise.all([loadUsers(currentUserFilters(), userSearch, 0, false), loadGroups(groupSearch, 0, false), loadOrgInvites()]);

    try {
      const a = await api.get<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`);
      setAdvanced(a);
      // Skip re-populating the editable fields below if the user has an
      // unsaved edit pending — this fetch may have been in flight since
      // before that edit started (see `advancedDirtyRef`'s own comment).
      if (!advancedDirtyRef.current) {
        setSmtpHost(a.smtp_host ?? "");
        setSmtpPort(a.smtp_port ? String(a.smtp_port) : "");
        setSmtpUsername(a.smtp_username ?? "");
        setSmtpUseTls(a.smtp_use_tls);
        setPatMaxLifetimeDays(a.pat_max_lifetime_days ? String(a.pat_max_lifetime_days) : "");
        setRequire2fa(a.require_2fa);
        setAllowSelfSignup(a.allow_self_signup);
        setAutoAcceptEmailDomain(a.auto_accept_email_domain ?? "");
        setExternalUserPolicy(a.external_user_policy);
        setAllowRelaxedChildProjectCreation(a.allow_relaxed_child_project_creation);
      }
      setOrgPats(await api.get<OrgPersonalAccessToken[]>(`/api/v1/orgs/${orgId}/pats`));
      setOrgProjects(await api.get<OrgProjectSummary[]>(`/api/v1/orgs/${orgId}/projects`));
      setModules(await api.get<OrgModule[]>(`/api/v1/orgs/${orgId}/modules`));
      setAvailableOrgModuleRoles(await api.get<ModuleRoleDefinition[]>(`/api/v1/orgs/${orgId}/module-roles`));
    } catch (err) {
      // Non-admins can't read advanced settings (403) — the section is simply hidden for them.
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      const sso = await api.get<OrgSsoConfig>(`/api/v1/orgs/${orgId}/sso-config`);
      setSsoConfig(sso);
      setSlugInput(sso.slug ?? "");
      setSsoEnabled(sso.sso_enabled);
      setSsoOnly(sso.sso_only);
      setOidcIssuerUrl(sso.oidc_issuer_url ?? "");
      setOidcClientId(sso.oidc_client_id ?? "");
      setOidcRequiredGroup(sso.oidc_required_group ?? "");
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      setScimStatus(await api.get<ScimTokenStatus>(`/api/v1/orgs/${orgId}/scim-token`));
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      const rd = await api.get<OrgReportDefaults>(`/api/v1/orgs/${orgId}/report-defaults`);
      setOrgReportDefaultsAvailable(true);
      setOrgReportIntro(rd.intro);
      setOrgReportChapters(rd.chapters);
      setOrgReportAppendices(rd.appendices);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setOrgReportDefaultsAvailable(false);
      } else {
        throw err;
      }
    }
  }

  async function saveOrgReportDefaults() {
    if (!orgId) return;
    await api.put(`/api/v1/orgs/${orgId}/report-defaults`, {
      intro: orgReportIntro, chapters: orgReportChapters, appendices: orgReportAppendices,
    });
    reload();
  }

  /** Applies a partial filter change (one `FilterCheckbox`/`FilterField` at
   * a time) on top of the other filters' current values, then reloads from
   * offset 0 — same "merge onto current state" shape every other partial-
   * filter-change handler in this codebase uses. */
  function applyUserFilters(next: Partial<UserFilters>) {
    const merged: UserFilters = { ...currentUserFilters(), ...next };
    setUserFilterStale(merged.stale);
    setUserFilterNo2fa(merged.no2fa);
    setUserFilterNoAccess(merged.noAccess);
    setUserRoleFilter(merged.role);
    loadUsers(merged, userSearch, 0, false);
  }

  function handleUserSearchChange(value: string) {
    setUserSearch(value);
    loadUsers(currentUserFilters(), value, 0, false);
  }

  function applyUserSort(key: OrgUserSortKey) {
    const next = cycleSort(userSort, key);
    setUserSort(next);
    loadUsers(currentUserFilters(), userSearch, 0, false, next);
  }

  function handleGroupSearchChange(value: string) {
    setGroupSearch(value);
    loadGroups(value, 0, false);
  }

  /** Backend-sorted refetch, same shape as `applyUserSort` — `list_org_
   * groups` already pages via `limit`/`offset` (Phase 0/B design review:
   * a client-side sort of only the currently-loaded page would misrepresent
   * the true full-list order, style guide "Pattern: sortable column
   * header"). */
  function applyGroupSort(key: OrgGroupSortKey) {
    const next = cycleSort(groupSort, key);
    setGroupSort(next);
    loadGroups(groupSearch, 0, false, next);
  }

  async function openUserAccess(user: OrgUser) {
    if (!orgId) return;
    setViewingUser(user);
    setUserAccess(null);
    setUserAccessError(null);
    setExpandedAccessProjectIds(new Set());
    try {
      setUserAccess(await api.get<UserAccess>(`/api/v1/orgs/${orgId}/users/${user.user_id}/access`));
    } catch (err) {
      setUserAccessError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  /** Toggles one project row's roles between `collapseProjectRoles()`'s
   * default summary and the full, uncollapsed set on the "View access"
   * panel. See `expandedAccessProjectIds` above for why this is per-row,
   * local, and reset on each new user rather than persisted. */
  function toggleAccessProjectExpanded(projectId: string) {
    setExpandedAccessProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      return next;
    });
  }

  async function toggleOutsideDomainUsers() {
    if (!orgId) return;
    if (outsideDomainUsers !== null) {
      setOutsideDomainUsers(null);
      return;
    }
    setOutsideDomainError(null);
    try {
      setOutsideDomainUsers(await api.get<OutsideDomainUser[]>(`/api/v1/orgs/${orgId}/users/outside-domain`));
    } catch (err) {
      setOutsideDomainError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function renameOrg() {
    if (!orgId || !orgNameEdit.trim() || !org || orgNameEdit === org.name) return;
    setRenameError(null);
    try {
      const updated = await api.put<Organization>(`/api/v1/orgs/${orgId}/name`, { name: orgNameEdit });
      setOrg(updated);
      setOrgNameEdit(updated.name);
      setRenameModalOpen(false);
      showToast(strings.orgAdmin.renamed);
    } catch (err) {
      setRenameError(err instanceof ApiError ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function sendOrgTestEmail() {
    if (!orgId) return;
    setTestEmailError(null);
    setTestEmailSuccess(false);
    setSendingTestEmail(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/test-email`, testEmailRecipient ? { to_email: testEmailRecipient } : {});
      setTestEmailSuccess(true);
    } catch (err) {
      setTestEmailError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setSendingTestEmail(false);
    }
  }

  async function saveAdvanced() {
    if (!orgId) return;
    setAdvancedError(null);
    try {
      const saved = await api.put<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`, {
        smtp_host: smtpHost || null,
        smtp_port: smtpPort ? Number(smtpPort) : null,
        smtp_username: smtpUsername || null,
        smtp_password: smtpPassword || undefined,
        smtp_use_tls: smtpUseTls,
        pat_max_lifetime_days: patMaxLifetimeDays ? Number(patMaxLifetimeDays) : null,
        require_2fa: require2fa,
        allow_self_signup: allowSelfSignup,
        auto_accept_email_domain: autoAcceptEmailDomain || null,
        external_user_policy: externalUserPolicy,
        allow_relaxed_child_project_creation: allowRelaxedChildProjectCreation,
      });
      setAdvanced(saved);
      setSmtpPassword("");
      // Saved successfully, so the fields now match the server again — a
      // later reload() is safe to repopulate them from a fresh fetch.
      advancedDirtyRef.current = false;
    } catch (err) {
      setAdvancedError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function revokeOrgPat(patId: string) {
    if (!orgId) return;
    setPatToRevoke(null);
    await api.post(`/api/v1/orgs/${orgId}/pats/${patId}/revoke`);
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function descopeOrgPat(patId: string) {
    if (!orgId) return;
    setPatToDescope(null);
    await api.post(`/api/v1/orgs/${orgId}/pats/${patId}/descope`);
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function revokeAllOrgPats() {
    if (!orgId) return;
    setRevokeAllPatsOpen(false);
    const result = await api.post<{ revoked_count: number }>(`/api/v1/orgs/${orgId}/pats/revoke-all`);
    setOrgPats([]);
    setPatBulkResult(strings.orgAdmin.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
  }

  async function setDefaultTemplate(projectId: string) {
    await api.put(`/api/v1/orgs/${orgId}/default-template`, { project_id: projectId || null });
    reload();
  }

  /** Opens the "Manage users" `Modal` for one project (Phase 5,
   * docs/decisions.md; rebuilt in Phase D, follow-up UX batch, 2026-08-31)
   * — fetches its effective-members + pending invites fresh every open,
   * the same two calls `ProjectAdminPage.tsx`'s own Members section makes
   * on its own `reload()`. */
  async function openManageUsers(project: OrgProjectSummary) {
    setManageUsersProjectId(project.id);
    setManageUsersProjectName(project.name);
    const [members, invites, moduleRoles] = await Promise.all([
      api.get<EffectiveMember[]>(`/api/v1/projects/${project.id}/effective-members`),
      api.get<PendingInvite[]>(`/api/v1/projects/${project.id}/pending-invites`),
      // Module system Phase 2: this project's own available project-scoped
      // module roles — fetched fresh per open, same as `members`/`invites`
      // above, since a different project can have a different owning org
      // (and therefore a different set of currently-enabled modules).
      api.get<ModuleRoleDefinition[]>(`/api/v1/projects/${project.id}/module-roles`),
    ]);
    setManageUsersAvailableModuleRoles(moduleRoles);
    setManageUsersMembers(members);
    setManageUsersInvites(invites);
  }

  function closeManageUsers() {
    setManageUsersProjectId(null);
    setManageUsersProjectName("");
    setManageUsersMembers([]);
    setManageUsersInvites([]);
    setManageUsersAvailableModuleRoles([]);
    setManageUsersAddMemberModalOpen(false);
  }

  async function reloadManageUsersMembers() {
    if (!manageUsersProjectId) return;
    setManageUsersMembers(await api.get<EffectiveMember[]>(`/api/v1/projects/${manageUsersProjectId}/effective-members`));
  }

  /** `ProjectMembersTable`'s own `onToggleRole` — only ever called for an
   * option whose sole source is `direct_role` (see that component's
   * docstring). Same "re-fetch just effective-members" treatment
   * `ProjectAdminPage.tsx`'s own `toggleProjectMemberRole` uses. */
  async function toggleManageUsersRole(userId: string, role: ProjectRole, checked: boolean) {
    if (!manageUsersProjectId) return;
    try {
      if (checked) {
        await api.post(`/api/v1/projects/${manageUsersProjectId}/roles`, { user_id: userId, role });
      } else {
        await api.delete(`/api/v1/projects/${manageUsersProjectId}/roles/${userId}/${role}`);
      }
      await reloadManageUsersMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s `onToggleModuleRole` (module system Phase 2),
   * scoped to `manageUsersProjectId` — same "re-fetch just effective-
   * members" treatment `toggleManageUsersRole` above uses. */
  async function toggleManageUsersModuleRole(userId: string, moduleKey: string, roleKey: string, grant: boolean) {
    if (!manageUsersProjectId) return;
    try {
      if (grant) {
        await api.post(`/api/v1/projects/${manageUsersProjectId}/members/${userId}/module-roles`, {
          module_key: moduleKey, role_key: roleKey,
        });
      } else {
        await api.delete(
          `/api/v1/projects/${manageUsersProjectId}/members/${userId}/module-roles/${moduleKey}/${roleKey}`
        );
      }
      await reloadManageUsersMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function addManageUsersMember(userId: string) {
    if (!manageUsersProjectId) return;
    await api.post(`/api/v1/projects/${manageUsersProjectId}/roles`, { user_id: userId, role: manageUsersAddRole });
    await reloadManageUsersMembers();
  }

  /** The group branch of the same add-control (PR5 of the members/groups
   * directory rework plan) — `UserAutocomplete`'s combined user-or-group
   * autocomplete calls this instead of `addManageUsersMember` when the
   * selected match is an org group, granting it `manageUsersAddRole`
   * *directly* on `manageUsersProjectId` via PR4's new mechanism, the same
   * pattern `ProjectAdminPage.tsx`'s own `addProjectGroupRole` uses. No
   * `ProjectGroup` wrapper is created, and nesting stays out of scope for
   * this control — see that function's own docstring for the full
   * rationale, shared verbatim here. */
  async function addManageUsersGroupRole(orgGroupId: string) {
    if (!manageUsersProjectId) return;
    await api.post(`/api/v1/projects/${manageUsersProjectId}/group-roles`, { org_group_id: orgGroupId, role: manageUsersAddRole });
    await reloadManageUsersMembers();
  }

  /** `ProjectMembersTable`'s per-row "Remove all access" (Actions column,
   * PR6 of the members/groups directory rework plan) — same treatment
   * `ProjectAdminPage.tsx`'s own `removeAllProjectMemberAccess` uses,
   * scoped to `manageUsersProjectId`/`manageUsersMembers`. */
  async function removeAllManageUsersMemberAccess(userId: string) {
    if (!manageUsersProjectId) return;
    const member = manageUsersMembers.find((m) => m.user_id === userId);
    if (!member) return;
    try {
      const roles = [...new Set(member.sources.map((s) => s.role))];
      await Promise.all(
        roles.map((role) => api.delete(`/api/v1/projects/${manageUsersProjectId}/roles/${userId}/${role}`))
      );
      showToast(strings.membersTable.removeAllAccessSuccess(member.display_name));
      await reloadManageUsersMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s per-row "Convert inherited access to direct
   * roles" (Actions column, PR6) — same treatment
   * `ProjectAdminPage.tsx`'s own `convertProjectMemberToDirect` uses,
   * scoped to `manageUsersProjectId`/`manageUsersMembers`. */
  async function convertManageUsersMemberToDirect(userId: string) {
    if (!manageUsersProjectId) return;
    const member = manageUsersMembers.find((m) => m.user_id === userId);
    try {
      const result = await api.post<MaterializeResult>(
        `/api/v1/projects/${manageUsersProjectId}/materialize-inherited-access/${userId}`
      );
      const name = member?.display_name ?? "";
      showToast(
        result.created.length > 0
          ? strings.membersTable.convertToDirectSuccess(name)
          : strings.membersTable.convertToDirectNoOp(name)
      );
      await reloadManageUsersMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** The by-email counterpart, for a user outside this org entirely — same
   * endpoint and outcome messaging `ProjectAdminPage.tsx`'s own
   * `addExternalMember` uses, reused here via a `Toast` instead of that
   * page's inline result banner (this Modal has no equivalent persistent
   * banner slot). */
  async function addManageUsersExternalMember(email: string) {
    if (!manageUsersProjectId) return;
    try {
      const result = await api.post<{ outcome: AssignByEmailOutcome }>(
        `/api/v1/projects/${manageUsersProjectId}/roles/by-email`,
        { email, role: manageUsersAddRole },
      );
      const messages: Record<AssignByEmailOutcome, (email: string, role: string, org: string) => string> = {
        added: strings.admin.externalAddedDirectly,
        invited: strings.admin.externalInvited,
        sso_provisioned: strings.admin.externalSsoProvisioned,
      };
      showToast(messages[result.outcome](email, manageUsersAddRole, orgLabel));
      await reloadManageUsersMembers();
      setManageUsersInvites(await api.get<PendingInvite[]>(`/api/v1/projects/${manageUsersProjectId}/pending-invites`));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : strings.admin.externalAddError, "error");
    }
  }

  async function resendManageUsersInvite(invite: PendingInvite) {
    if (!manageUsersProjectId) return;
    setManageUsersResendingInviteId(invite.id);
    try {
      await api.post(`/api/v1/projects/${manageUsersProjectId}/pending-invites/${invite.id}/resend`);
      showToast(strings.admin.resendInviteSuccess(invite.email));
      setManageUsersInvites(await api.get<PendingInvite[]>(`/api/v1/projects/${manageUsersProjectId}/pending-invites`));
    } catch (err) {
      showToast(toErrorMessage(err, strings.admin.resendInviteError), "error");
    } finally {
      setManageUsersResendingInviteId(null);
    }
  }

  async function addProjectStatus(name: string) {
    if (!orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/project-statuses`, { name });
    reload();
  }

  async function moveProjectStatus(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/orgs/${orgId}/project-statuses/${id}/move`, { direction });
    reload();
  }

  async function renameProjectStatus(id: string, name: string) {
    await api.patch(`/api/v1/orgs/${orgId}/project-statuses/${id}`, { name });
    reload();
  }

  /** Attempts a plain delete first (no `reassign_to_id`) per §4.0's server
   * contract: a 204 means done; a 409 means the status is in use;
   * `DefinitionList` opens the reassignment picker itself, showing the
   * server's own count message rather than a generic one. */
  async function deleteProjectStatus(id: string, reassignToId?: string) {
    await api.delete(`/api/v1/orgs/${orgId}/project-statuses/${id}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`);
    reload();
  }

  async function addLinkType(forward: string, reverse: string) {
    if (!orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/link-types`, { forward_name: forward, reverse_name: reverse });
    reload();
  }

  async function moveLinkType(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/orgs/${orgId}/link-types/${id}/move`, { direction });
    reload();
  }

  async function renameLinkType(id: string, forward: string, reverse: string) {
    await api.patch(`/api/v1/orgs/${orgId}/link-types/${id}`, { forward_name: forward, reverse_name: reverse });
    reload();
  }

  async function deleteLinkType(id: string, reassignToId?: string) {
    await api.delete(`/api/v1/orgs/${orgId}/link-types/${id}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`);
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  /** Degraded-view action for a *disabled* org specifically (distinct from
   * "not a member" below — a server admin might well already be a genuine
   * member of an org that's since been disabled): re-enables it, then
   * reloads, which now succeeds fully again for anyone who already had a
   * role here. */
  async function enableThisOrg() {
    if (!orgId) return;
    setEnableError(null);
    setEnabling(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/enable`);
      await reload();
    } catch (err) {
      setEnableError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setEnabling(false);
    }
  }

  /** Degraded-view action (self-hosting use case): a server admin with no
   * role in this org grants *themselves* org_admin, then reloads — which
   * now succeeds fully, since they're a genuine member from this point on. */
  async function joinAsAdmin() {
    if (!orgId) return;
    setJoinError(null);
    setJoining(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/join-as-admin`);
      await reload();
    } catch (err) {
      setJoinError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setJoining(false);
    }
  }

  /** Degraded-view action (hosting-company use case): a server admin
   * creates an org_admin user in this org for *someone else*, without
   * becoming a member themselves — the same carve-out `create_org_user`
   * already grants (regardless of whether this org already has users),
   * just reachable from here now that the full page can't load. */
  async function createInitialAdmin() {
    if (!orgId) return;
    setBootstrapError(null);
    setBootstrapCreated(false);
    try {
      await api.post(`/api/v1/orgs/${orgId}/users`, {
        email: bootstrapEmail, display_name: bootstrapName, password: bootstrapPassword, role: "org_admin",
      });
      setBootstrapEmail("");
      setBootstrapName("");
      setBootstrapPassword("");
      setBootstrapCreated(true);
    } catch (err) {
      setBootstrapError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function createUser() {
    try {
      await api.post(`/api/v1/orgs/${orgId}/users`, {
        email: newUserEmail, display_name: newUserName, password: newUserPassword, role: newUserRole,
      });
      setNewUserEmail("");
      setNewUserName("");
      setNewUserPassword("");
      setNewUserRole("member");
      setNewUserModalOpen(false);
      showToast(strings.orgAdmin.userCreated);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** "Invite user" (Phase A) — the org-level counterpart to `createUser`
   * above: emails a sign-up link instead of setting a password immediately.
   * Only refreshes `orgInvites` (not the whole page, matching `grantOrgRole`/
   * `revokeOrgRole`'s own reasoning above) since nothing else on the page
   * changes as a result. */
  async function inviteOrgUser() {
    try {
      await api.post(`/api/v1/orgs/${orgId}/pending-invites`, { email: inviteUserEmail });
      setInviteUserEmail("");
      setInviteUserModalOpen(false);
      showToast(strings.orgAdmin.inviteSent);
      await loadOrgInvites();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function resendOrgInvite(invite: OrgPendingInvite) {
    setResendingOrgInviteId(invite.id);
    try {
      await api.post(`/api/v1/orgs/${orgId}/pending-invites/${invite.id}/resend`);
      showToast(strings.admin.resendInviteSuccess(invite.email));
      await loadOrgInvites();
    } catch (err) {
      showToast(toErrorMessage(err, strings.admin.resendInviteError), "error");
    } finally {
      setResendingOrgInviteId(null);
    }
  }

  // Updates just the affected row's own `roles` array in local state on
  // success, rather than calling the page-wide `reload()` every other
  // mutation on this page uses. `reload()` re-fetches ~10 endpoints
  // (including the users list from offset 0), so toggling a role would
  // silently drop any users paged in past the first 30 and — if two
  // toggles landed close together — race two overlapping reload bundles
  // against each other; a transient failure in either one replaces the
  // whole page with a load-error state (see docs/decisions.md, this entry).
  // A single grant/revoke only ever changes this one row's own role set, so
  // there's nothing else on the page a full reload would need to refresh.
  async function grantOrgRole(u: OrgUser, role: OrgRole) {
    try {
      await api.post(`/api/v1/orgs/${orgId}/users/${u.user_id}/roles`, { role });
      setUsers((prev) =>
        prev.map((x) => (x.user_id === u.user_id ? { ...x, roles: [...x.roles, role] } : x))
      );
      showToast(strings.orgAdmin.roleGranted);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeOrgRole(u: OrgUser, role: OrgRole) {
    try {
      await api.delete(`/api/v1/orgs/${orgId}/users/${u.user_id}/roles/${role}`);
      setUsers((prev) =>
        prev.map((x) => (x.user_id === u.user_id ? { ...x, roles: x.roles.filter((r) => r !== role) } : x))
      );
      showToast(strings.orgAdmin.roleRevoked);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Module system Phase 2: same single-row local-state patch as
  // `grantOrgRole`/`revokeOrgRole` above, for the same reasoning (a
  // single grant/revoke only ever changes this one row's own module-role
  // set, so a full `reload()` would refresh nothing else it needs).
  async function grantModuleRole(u: OrgUser, moduleKey: string, roleKey: string) {
    try {
      await api.post(`/api/v1/orgs/${orgId}/users/${u.user_id}/module-roles`, {
        module_key: moduleKey, role_key: roleKey,
      });
      setUsers((prev) =>
        prev.map((x) =>
          x.user_id === u.user_id
            ? { ...x, module_roles: [...x.module_roles, { module_key: moduleKey, role_key: roleKey }] }
            : x
        )
      );
      showToast(strings.orgAdmin.roleGranted);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeModuleRole(u: OrgUser, moduleKey: string, roleKey: string) {
    try {
      await api.delete(`/api/v1/orgs/${orgId}/users/${u.user_id}/module-roles/${moduleKey}/${roleKey}`);
      setUsers((prev) =>
        prev.map((x) =>
          x.user_id === u.user_id
            ? { ...x, module_roles: x.module_roles.filter((g) => !(g.module_key === moduleKey && g.role_key === roleKey)) }
            : x
        )
      );
      showToast(strings.orgAdmin.roleRevoked);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Module system Phase 1: immediate PUT + local-state patch, same shape
  // as `grantOrgRole`/`revokeOrgRole` above — a single toggle only ever
  // changes this one module's own row, so there's nothing else on the page
  // a full `reload()` would need to refresh, and a toast gives the
  // feedback-on-every-mutation the style guide requires.
  async function toggleModuleEnabled(moduleKey: string, enabled: boolean) {
    try {
      const updated = await api.put<OrgModule>(`/api/v1/orgs/${orgId}/modules/${moduleKey}`, { enabled });
      setModules((prev) => prev.map((m) => (m.module_key === moduleKey ? updated : m)));
      showToast(enabled ? strings.orgAdmin.moduleEnabledToast(updated.name) : strings.orgAdmin.moduleDisabledToast(updated.name));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function createGroup() {
    try {
      await api.post(`/api/v1/orgs/${orgId}/groups`, { name: newGroupName });
      setNewGroupName("");
      setNewGroupModalOpen(false);
      showToast(strings.orgAdmin.groupCreated);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function addGroupMember(groupId: string, userId: string) {
    await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { user_id: userId });
    reload();
  }

  async function removeGroupMember(groupId: string, userId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${userId}`);
    reload();
  }

  const [nestSelections, setNestSelections] = useState<Record<string, string>>({});
  const [nestErrors, setNestErrors] = useState<Record<string, string | null>>({});

  async function addNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    setNestErrors((prev) => ({ ...prev, [groupId]: null }));
    try {
      await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { member_org_group_id: memberOrgGroupId });
      setNestSelections((prev) => ({ ...prev, [groupId]: "" }));
      reload();
    } catch (err) {
      setNestErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
  }

  async function removeNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${memberOrgGroupId}`);
    reload();
  }

  const [idpSyncEdits, setIdpSyncEdits] = useState<Record<string, string>>({});
  // Granted-role edits (2026-08 UX audit roadmap item 522), saved together
  // with the sync name above via one button — a role only makes sense
  // alongside a sync name, so splitting them into separate save actions
  // would let the UI momentarily represent the invalid "role with no sync
  // target" state the backend itself rejects.
  const [grantedRoleEdits, setGrantedRoleEdits] = useState<Record<string, OrgRole | "">>({});
  const [idpSyncErrors, setIdpSyncErrors] = useState<Record<string, string | null>>({});

  async function saveIdpSync(groupId: string, syncName: string, grantedRole: OrgRole | "") {
    setIdpSyncErrors((prev) => ({ ...prev, [groupId]: null }));
    try {
      await api.patch(`/api/v1/orgs/${orgId}/groups/${groupId}`, {
        idp_synced_group_name: syncName.trim() || null,
        granted_org_role: grantedRole || null,
      });
      setIdpSyncEdits((prev) => {
        const next = { ...prev };
        delete next[groupId];
        return next;
      });
      setGrantedRoleEdits((prev) => {
        const next = { ...prev };
        delete next[groupId];
        return next;
      });
      // Principle 7 (feedback on every mutation) — this save previously had
      // no success feedback at all, relying only on the inline error state
      // below for the failure path.
      showToast(strings.orgAdmin.groupSyncUpdated);
      reload();
    } catch (err) {
      setIdpSyncErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
  }

  /** The SSO-sync enable/disable checkbox (Phase B bug-fix pass,
   * 2026-08-31): checking it just reveals the name/role fields for editing
   * (no request until "Save sync settings" is clicked) — unchecking clears
   * both fields immediately via the same `PATCH` the Save button uses,
   * since there's nothing left to edit once sync is off. */
  async function toggleGroupSync(groupId: string, enabled: boolean) {
    setSyncEnabledEdits((prev) => ({ ...prev, [groupId]: enabled }));
    if (!enabled) {
      await saveIdpSync(groupId, "", "");
    }
  }

  const [logoUploading, setLogoUploading] = useState(false);
  const [logoUploaded, setLogoUploaded] = useState(false);
  const [logoError, setLogoError] = useState<string | null>(null);

  async function uploadLogo(file: File) {
    setLogoError(null);
    setLogoUploaded(false);
    setLogoUploading(true);
    try {
      await api.postFile(`/api/v1/orgs/${orgId}/logo`, file);
      await reload();
      setLogoUploaded(true);
    } catch (err) {
      setLogoError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setLogoUploading(false);
    }
  }

  async function removeLogo() {
    setLogoError(null);
    setLogoUploaded(false);
    setLogoUploading(true);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/logo`);
      await reload();
      showToast(strings.orgAdmin.logoRemoved);
    } catch (err) {
      setLogoError(err instanceof ApiError ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setLogoUploading(false);
    }
  }

  async function saveBranding() {
    setBrandingError(null);
    try {
      await api.put<Organization>(`/api/v1/orgs/${orgId}/branding`, {
        accent_color_hex: useOwnAccentColor ? accentColorInput : null,
        header_title: headerTitleInput || null,
        email_footer_company_name: emailFooterCompanyNameInput || null,
        email_footer_website: emailFooterWebsiteInput || null,
        email_footer_address: emailFooterAddressInput || null,
      });
      showToast(strings.orgAdmin.brandingSaved);
      reload();
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const [loginBackgroundUploading, setLoginBackgroundUploading] = useState(false);
  const [loginBackgroundUploaded, setLoginBackgroundUploaded] = useState(false);
  const [loginBackgroundError, setLoginBackgroundError] = useState<string | null>(null);

  async function uploadLoginBackground(file: File) {
    setLoginBackgroundError(null);
    setLoginBackgroundUploaded(false);
    setLoginBackgroundUploading(true);
    try {
      await api.postFile(`/api/v1/orgs/${orgId}/login-background`, file);
      await reload();
      setLoginBackgroundUploaded(true);
    } catch (err) {
      setLoginBackgroundError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setLoginBackgroundUploading(false);
    }
  }

  async function removeLoginBackground() {
    setLoginBackgroundError(null);
    setLoginBackgroundUploaded(false);
    setLoginBackgroundUploading(true);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/login-background`);
      await reload();
      showToast(strings.orgAdmin.loginBackgroundRemoved);
    } catch (err) {
      setLoginBackgroundError(err instanceof ApiError ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setLoginBackgroundUploading(false);
    }
  }

  async function saveSso() {
    setSsoError(null);
    try {
      const saved = await api.put<OrgSsoConfig>(`/api/v1/orgs/${orgId}/sso-config`, {
        slug: slugInput || null,
        sso_enabled: ssoEnabled,
        sso_only: ssoOnly,
        oidc_issuer_url: oidcIssuerUrl || null,
        oidc_client_id: oidcClientId || null,
        oidc_client_secret: oidcClientSecret || null,
        oidc_required_group: oidcRequiredGroup || null,
      });
      setSsoConfig(saved);
      setOidcClientSecret("");
    } catch (err) {
      setSsoError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function regenerateScimToken() {
    setScimError(null);
    try {
      const created = await api.post<ScimTokenCreated>(`/api/v1/orgs/${orgId}/scim-token`);
      setScimGeneratedToken(created.token);
      setScimStatus({ enabled: true, token_prefix: created.token_prefix });
    } catch (err) {
      setScimError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function revokeScimToken() {
    setScimError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/scim-token`);
      setScimGeneratedToken(null);
      setScimStatus({ enabled: false, token_prefix: null });
    } catch (err) {
      setScimError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  function resetTemplateForm() {
    setEditingTemplateId(null);
    setNewTemplateName("");
    setNewTemplateAccentColor("#475569");
    setNewTemplateIncludeCoverPage(true);
    setNewTemplateIncludeLogo(true);
    setNewTemplateFooterText("");
    setNewTemplateIntro("");
    setNewTemplateChapters([]);
    setNewTemplateAppendices([]);
    setNewTemplateChaptersPerComponent(true);
  }

  function openNewTemplateForm() {
    resetTemplateForm();
    setTemplateFormOpen(true);
  }

  function closeTemplateForm() {
    resetTemplateForm();
    setTemplateFormOpen(false);
  }

  function startEditTemplate(tpl: ReportTemplate) {
    setEditingTemplateId(tpl.id);
    setNewTemplateName(tpl.name);
    setNewTemplateAccentColor(tpl.accent_color_hex);
    setNewTemplateIncludeCoverPage(tpl.include_cover_page);
    setNewTemplateIncludeLogo(tpl.include_logo);
    setNewTemplateFooterText(tpl.footer_text ?? "");
    setNewTemplateIntro(tpl.intro);
    setNewTemplateChapters(tpl.chapters);
    setNewTemplateAppendices(tpl.appendices);
    setNewTemplateChaptersPerComponent(tpl.chapters_per_component);
    setTemplateFormOpen(true);
  }

  async function saveReportTemplate() {
    if (!newTemplateName) return;
    const payload = {
      name: newTemplateName,
      accent_color_hex: newTemplateAccentColor,
      include_cover_page: newTemplateIncludeCoverPage,
      include_logo: newTemplateIncludeLogo,
      footer_text: newTemplateFooterText || null,
      intro: newTemplateIntro,
      chapters: newTemplateChapters,
      appendices: newTemplateAppendices,
      chapters_per_component: newTemplateChaptersPerComponent,
    };
    if (editingTemplateId) {
      await api.put(`/api/v1/orgs/${orgId}/report-templates/${editingTemplateId}`, payload);
    } else {
      await api.post(`/api/v1/orgs/${orgId}/report-templates`, payload);
    }
    closeTemplateForm();
    reload();
  }

  async function deleteReportTemplate(templateId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/report-templates/${templateId}`);
    if (editingTemplateId === templateId) resetTemplateForm();
    reload();
  }

  async function uploadResource(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/resources`, file);
    reload();
  }

  async function deleteResource(fileId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/resources/${fileId}`);
    reload();
  }

  async function toggleDisplayNameLock(user: OrgUser) {
    await api.put(`/api/v1/orgs/${orgId}/users/${user.user_id}/display-name-lock`, {
      display_name_locked: !user.display_name_locked,
    });
    reload();
  }

  /** Users table Actions column, "Remove from {org}" (PR6 of the members/
   * groups directory rework plan, docs/decisions.md) — the new admin-
   * initiated `DELETE /{organization_id}/users/{user_id}/membership`
   * endpoint. Confirmed via `ConfirmDialog` (`confirmRemoveUser` below)
   * before this is ever called; not offered at all for the caller's own
   * row (see the Actions column's own `ActionMenu` items, which route
   * self-removal to the existing "Leave organisation" flow on
   * `PreferencesPage.tsx` instead, matching the backend's own self-
   * targeting guard on this endpoint). */
  async function removeOrgUser(u: OrgUser) {
    if (!orgId) return;
    try {
      await api.delete(`/api/v1/orgs/${orgId}/users/${u.user_id}/membership`);
      setConfirmRemoveUser(null);
      showToast(strings.orgAdmin.removedFromOrgToast(u.display_name));
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const [exportingOrg, setExportingOrg] = useState(false);

  async function exportOrg() {
    if (!orgId || !org) return;
    setExportingOrg(true);
    try {
      const blob = await api.getForBlob(`/api/v1/orgs/${orgId}/export`);
      const safeName = org.name.replace(/[\\/"\r\n\t]/g, "") || "organization";
      downloadBlob(blob, `${safeName}-export.zip`);
    } finally {
      setExportingOrg(false);
    }
  }

  const [importMergeFile, setImportMergeFile] = useState<File | null>(null);
  const [importMergeConflicts, setImportMergeConflicts] = useState<MergeConflict[] | null>(null);
  const [importMergeResolutions, setImportMergeResolutions] = useState<Record<string, string>>({});
  const [importMergePreviewing, setImportMergePreviewing] = useState(false);
  const [importMergeSubmitting, setImportMergeSubmitting] = useState(false);
  const [importMergeError, setImportMergeError] = useState<string | null>(null);
  const [importMergeResult, setImportMergeResult] = useState<OrgMergeResult | null>(null);

  async function previewImportMerge() {
    if (!orgId || !importMergeFile) return;
    setImportMergeError(null);
    setImportMergeResult(null);
    setImportMergePreviewing(true);
    try {
      const result = await api.postFile<OrgMergePreviewResult>(`/api/v1/orgs/${orgId}/import/preview`, importMergeFile);
      setImportMergeConflicts(result.conflicts);
      setImportMergeResolutions(defaultResolutions(result.conflicts));
    } catch (err) {
      setImportMergeError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setImportMergePreviewing(false);
    }
  }

  async function confirmImportMerge() {
    if (!orgId || !importMergeFile) return;
    setImportMergeError(null);
    setImportMergeSubmitting(true);
    try {
      const result = await api.postFile<OrgMergeResult>(`/api/v1/orgs/${orgId}/import/merge`, importMergeFile, {
        resolutions: JSON.stringify(importMergeResolutions),
      });
      setImportMergeResult(result);
      setImportMergeFile(null);
      setImportMergeConflicts(null);
      setImportMergeResolutions({});
      reload();
    } catch (err) {
      setImportMergeError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setImportMergeSubmitting(false);
    }
  }

  function cancelImportMerge() {
    setImportMergeFile(null);
    setImportMergeConflicts(null);
    setImportMergeResolutions({});
    setImportMergeError(null);
  }

  const orgIsDisabled = loadError?.toLowerCase().includes("disabled") ?? false;

  if (loadError && orgIsDisabled && user?.is_server_admin) {
    // A server admin hitting a *disabled* org — distinct from "not a
    // member" below, since they might well already be a genuine member of
    // an org that's since been disabled. The one useful action here is
    // re-enabling it, which then reloads as normal for anyone with a
    // pre-existing role.
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.serverOrgs.disabled}</h2>
          <p className="text-muted">{loadError}</p>
          {enableError && <div style={{ color: "var(--color-danger)" }}>{enableError}</div>}
          <button className="btn btn-primary" onClick={enableThisOrg} disabled={enabling} style={{ alignSelf: "flex-start" }}>
            {strings.serverOrgs.enable}
          </button>
        </div>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
        </Link>
      </div>
    );
  }

  if (loadError && (orgIsDisabled || !user?.is_server_admin)) {
    // Plain, non-actionable error: a disabled org for a non-server-admin
    // (nothing they can do here), or any org for a non-server-admin who
    // simply isn't a member — no carve-out applies to either case.
    return (
      <div className="card stack">
        <p>{loadError}</p>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
        </Link>
      </div>
    );
  }

  if (loadError && user?.is_server_admin) {
    // I-M-05's carve-out, surfaced here rather than just erroring out: a
    // server admin has no automatic role in this org, but can still
    // either become its admin themselves (self-hosting) or create an
    // admin user in it for someone else (hosting-company use case,
    // whether or not this org already has users) — both already allowed
    // server-admin-only at the API layer, just not previously reachable
    // from this page at all.
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.notAMemberTitle(orgLabel)}</h2>
          <p className="text-muted">{strings.orgAdmin.notAMemberHint}</p>
          {joinError && <div style={{ color: "var(--color-danger)" }}>{joinError}</div>}
          <button className="btn btn-primary" onClick={joinAsAdmin} disabled={joining} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.joinAsAdmin(orgLabel)}
          </button>
        </div>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.createInitialAdmin}</h2>
          <input className="input" placeholder={strings.orgAdmin.email} value={bootstrapEmail} onChange={(e) => setBootstrapEmail(e.target.value)} />
          <input className="input" placeholder={strings.orgAdmin.name} value={bootstrapName} onChange={(e) => setBootstrapName(e.target.value)} />
          <input
            className="input"
            type="password"
            placeholder={strings.orgAdmin.password}
            value={bootstrapPassword}
            onChange={(e) => setBootstrapPassword(e.target.value)}
          />
          {bootstrapError && <div style={{ color: "var(--color-danger)" }}>{bootstrapError}</div>}
          {bootstrapCreated && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.initialAdminCreated(orgLabel)}</div>}
          <button
            className="btn btn-primary"
            onClick={createInitialAdmin}
            disabled={!bootstrapEmail || !bootstrapName || !bootstrapPassword}
            style={{ alignSelf: "flex-start" }}
          >
            {strings.orgAdmin.newUser}
          </button>
        </div>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
        </Link>
      </div>
    );
  }

  if (!org) return <Spinner />;

  // sso_only and allow_self_signup are mutually exclusive (an org that only
  // accepts SSO logins can't also let people create native-password
  // accounts) — the backend already rejects saving this combination
  // (test_sso_only_enforcement.py), this just surfaces the conflict before
  // the round trip instead of only after a 422.
  const selfSignupConflict = allowSelfSignup && ssoOnly;

  const activeGroup: OrgAdminGroupKey = ORG_ADMIN_GROUP_KEYS.includes(groupParam as OrgAdminGroupKey)
    ? (groupParam as OrgAdminGroupKey)
    : "overview";
  const orgAdminGroups: ResourceMenuGroupDef<OrgAdminGroupKey>[] = [
    { key: "overview", label: strings.orgAdmin.groupOverview, href: `/orgs/${orgId}/admin/overview` },
    { key: "users", label: strings.orgAdmin.groupUsers, href: `/orgs/${orgId}/admin/users` },
    { key: "groups", label: strings.orgAdmin.groupGroups, href: `/orgs/${orgId}/admin/groups` },
    { key: "projects-workflow", label: strings.orgAdmin.groupProjectsWorkflow, href: `/orgs/${orgId}/admin/projects-workflow` },
    { key: "branding-defaults", label: strings.orgAdmin.groupBrandingDefaults, href: `/orgs/${orgId}/admin/branding-defaults` },
    { key: "templates-reports", label: strings.orgAdmin.groupTemplatesReports, href: `/orgs/${orgId}/admin/templates-reports` },
    { key: "oauth-sso", label: strings.orgAdmin.groupOauthSso, href: `/orgs/${orgId}/admin/oauth-sso` },
    { key: "email", label: strings.orgAdmin.groupEmail, href: `/orgs/${orgId}/admin/email` },
    { key: "security", label: strings.orgAdmin.groupSecurity, href: `/orgs/${orgId}/admin/security` },
    { key: "modules", label: strings.orgAdmin.groupModules, href: `/orgs/${orgId}/admin/modules` },
  ];

  // Users table row merge (Phase A, follow-up UX batch, 2026-08-31): pending
  // org-only invites are merged client-side into the same `DirectoryTable`
  // as real users, `kind: "user" | "invited"` — the same union-row pattern
  // `MemberRoleTable` established. Invited rows aren't part of `users`'
  // own server-side sort/pagination (they come from a separate, unpaginated
  // endpoint), so they're always rendered ahead of the sorted/paginated
  // user rows rather than interleaved into that sort order. Search does
  // apply (client-side, against the invite's email) since it's the same
  // search box; the other access-review filters (stale/no-2FA/no-project-
  // access/role) don't apply to an account that doesn't exist yet, so
  // invited rows are unaffected by them — only "Show invited" hides them.
  const filteredOrgInvites = showInvitedUsers
    ? orgInvites.filter((invite) => !userSearch || invite.email.toLowerCase().includes(userSearch.toLowerCase()))
    : [];
  const usersRows: UsersRow[] = [
    ...filteredOrgInvites.map((invite): UsersRow => ({ kind: "invited", invite })),
    ...users.map((u): UsersRow => ({ kind: "user", user: u })),
  ];
  // Module system Phase 2: resolves a module role definition's own
  // `module_key` to that module's display `name` (from the already-fetched
  // `modules` list), for the Roles column option label "<role name>
  // (<module name>)" — falls back to the raw key only if `modules` hasn't
  // resolved yet or somehow doesn't include it (shouldn't happen in
  // practice, since a role is only ever "available" for a module that's
  // both registered and currently enabled).
  function moduleDisplayNameFor(moduleKey: string): string {
    return modules.find((m) => m.module_key === moduleKey)?.name ?? moduleKey;
  }
  const usersColumns: DirectoryColumn<UsersRow>[] = [
    {
      key: "email", label: strings.orgAdmin.email, sortable: true,
      render: (row) => (row.kind === "user" ? row.user.email : row.invite.email),
    },
    {
      // Repurposed for an invited row: there's no display name yet (the
      // invitee sets it at signup), so this shows who sent the invite
      // instead — the closest equivalent "identity" fact available.
      key: "display_name", label: strings.orgAdmin.name, sortable: true,
      render: (row) =>
        row.kind === "user" ? (
          row.user.display_name
        ) : (
          <span className="text-muted">{strings.orgAdmin.invitedBy(row.invite.invited_by_display_name)}</span>
        ),
    },
    {
      key: "roles", label: strings.orgAdmin.roles,
      render: (row) => {
        if (row.kind === "invited") return <span className="text-muted">—</span>;
        const u = row.user;
        return (
          <MultiSelectDropdown
            triggerLabel={strings.orgAdmin.rolesFor(u.display_name)}
            emptyLabel={strings.orgAdmin.noRoles}
            options={[
              ...(["member", "project_creator", "org_admin"] as const).map((role) => {
                const checked = u.roles.includes(role);
                // A user can never revoke their own org role via this
                // control — mirrors the backend's self-targeting block
                // on the revoke endpoint (an org can never reach zero
                // admins through here, by construction). Granting a
                // role to oneself is still allowed, matching the
                // backend, so only the "uncheck" direction is disabled.
                const disabled = checked && u.user_id === user?.id;
                return {
                  value: role,
                  label: ORG_ROLE_LABEL[role],
                  checked,
                  disabled,
                  title: disabled ? strings.orgAdmin.cannotChangeOwnRole : undefined,
                  optionLabel: checked
                    ? strings.orgAdmin.revokeRole(ORG_ROLE_LABEL[role], u.display_name)
                    : strings.orgAdmin.grantRole(ORG_ROLE_LABEL[role], u.display_name),
                  onToggle: () => (checked ? revokeOrgRole(u, role) : grantOrgRole(u, role)),
                };
              }),
              // Module system Phase 2: merged in alongside the three core
              // roles above — same dropdown, never disabled (module roles
              // carry no "own row" self-targeting restriction the way
              // ORG_ADMIN does). Label renders the role definition's own
              // `name` directly (already human-readable API data, not a
              // raw closed-enum wire value), plus the owning module's
              // display name for context, per the plan's own worked
              // example ("Compliance Officer (Compliance)").
              ...availableOrgModuleRoles.map((d) => {
                const checked = u.module_roles.some((g) => g.module_key === d.module_key && g.role_key === d.role_key);
                const label = `${d.name} (${moduleDisplayNameFor(d.module_key)})`;
                return {
                  value: `${d.module_key}:${d.role_key}`,
                  label,
                  checked,
                  optionLabel: checked
                    ? strings.orgAdmin.revokeRole(label, u.display_name)
                    : strings.orgAdmin.grantRole(label, u.display_name),
                  onToggle: () =>
                    checked ? revokeModuleRole(u, d.module_key, d.role_key) : grantModuleRole(u, d.module_key, d.role_key),
                };
              }),
            ]}
          />
        );
      },
    },
    {
      key: "status", label: strings.orgAdmin.status,
      render: (row) => {
        if (row.kind === "invited") {
          const invite = row.invite;
          return (
            <div className="row" style={{ gap: "0.4rem", alignItems: "center" }}>
              <span className="badge">{PENDING_INVITE_STATUS_LABEL[invite.status]}</span>
              <button
                className="btn"
                disabled={resendingOrgInviteId === invite.id}
                onClick={() => resendOrgInvite(invite)}
                title={strings.admin.resendInviteAria(invite.email)}
                aria-label={strings.admin.resendInviteAria(invite.email)}
              >
                <Send size={14} /> {strings.admin.resendInvite}
              </button>
            </div>
          );
        }
        const u = row.user;
        if (u.is_archived) return strings.orgAdmin.statusArchived;
        if (!u.is_active) return strings.orgAdmin.statusDeactivated;
        return <span title={strings.orgAdmin.statusActiveHint}>{strings.orgAdmin.statusActive}</span>;
      },
    },
    {
      // Repurposed for an invited row: shows when the invite was sent
      // rather than a last-login date, which doesn't exist yet.
      key: "last_login_at", label: strings.orgAdmin.lastLogin, sortable: true,
      render: (row) => {
        if (row.kind === "invited") {
          return (
            <span className="text-muted">
              {strings.orgAdmin.invitedSentOn(new Date(row.invite.created_at).toLocaleDateString())}
            </span>
          );
        }
        return row.user.last_login_at ? new Date(row.user.last_login_at).toLocaleDateString() : strings.orgAdmin.never;
      },
    },
    {
      key: "2fa", label: strings.orgAdmin.twoFactor,
      render: (row) => (row.kind === "invited" ? "" : row.user.is_2fa_enabled ? strings.common.yes : strings.common.no),
    },
    {
      // Users table Actions column (PR6 of the members/groups directory
      // rework plan, docs/decisions.md) — the two previously-bare buttons
      // (View access, lock/unlock display name) consolidated into one
      // `ActionMenu`, plus "Remove from {org}" (new, access-mutating).
      // "Add to group" sits as its own small control next to the menu,
      // not inside it — `AddToGroupControl` needs its own anchored
      // `Popover` trigger, which a plain `ActionMenu` item (a single
      // `onSelect` callback) can't host.
      key: "actions", label: "",
      render: (row) => {
        if (row.kind === "invited") return null;
        const u = row.user;
        const isSelf = u.user_id === user?.id;
        return (
          <div className="row" style={{ gap: "0.25rem" }}>
            <ActionMenu
              triggerLabel={strings.orgAdmin.usersActionsFor(u.display_name)}
              items={[
                { label: strings.orgAdmin.viewAccess(u.display_name), icon: <Eye size={14} />, onSelect: () => openUserAccess(u) },
                {
                  label: u.display_name_locked ? strings.orgAdmin.unlockDisplayName : strings.orgAdmin.lockDisplayName,
                  icon: u.display_name_locked ? <Lock size={14} /> : <Unlock size={14} />,
                  onSelect: () => toggleDisplayNameLock(u),
                },
                // Not offered on the caller's own row — self-removal has
                // its own, already-guarded path ("Leave organisation" on
                // Preferences), matching the backend's own self-targeting
                // guard on this endpoint (see `remove_org_user`'s
                // docstring).
                ...(isSelf
                  ? []
                  : [
                      {
                        label: strings.orgAdmin.removeFromOrg(orgLabel),
                        icon: <Trash2 size={14} />,
                        onSelect: () => setConfirmRemoveUser(u),
                      },
                    ]),
              ]}
            />
            <AddToGroupControl user={u} groups={allGroups} onAdd={addGroupMember} />
          </div>
        );
      },
    },
  ];

  // Org Groups `DirectoryTable` (Phase B, follow-up UX batch, 2026-08-31) —
  // `groups` itself is already sorted server-side (`applyGroupSort`/
  // `loadGroups`'s `order` param), no client-side re-sort needed.
  const orgGroupColumns: DirectoryColumn<OrgGroup>[] = [
    { key: "name", label: strings.orgAdmin.name, sortable: true, render: (g) => g.name },
    {
      key: "members", label: strings.orgAdmin.groupMembersColumn,
      render: (g) => strings.admin.memberCount(g.member_user_ids.length),
    },
  ];

  return (
    <div className="stack">
      <ResourceMenu
        title={org.name}
        subtitle={strings.orgAdmin.adminSubtitle(orgLabelCap)}
        ariaLabel={strings.orgAdmin.sectionsNav}
        groups={orgAdminGroups}
        active={activeGroup}
      >
        {activeGroup === "overview" && (
          <div className="stack">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="stack" style={{ gap: "0.35rem" }}>
                {/* Org name is now shown once, universally, as `ResourceMenu`'s
                    own title above every group — repeating it here as a
                    second <h1> (previously the only place it appeared at
                    all — every other group had no page title whatsoever)
                    would just duplicate that same text on this one group. */}
              </div>
              <div className="row">
                {org.logo_file_id && (
                  <img src={fileUrl(org.logo_file_id)} alt={`${org.name} logo`} style={{ height: 40 }} />
                )}
                {/* Style guide "Pattern: action menu" — rename and export
                    combined behind one kebab trigger instead of an
                    always-visible rename input plus a separate export
                    button. Rename is only offered when `advanced` has
                    loaded (the same org-admin-only gate the inline input
                    used to carry — a non-admin 403s on advanced-settings);
                    export stays available to every member, matching its
                    previous ungated placement. */}
                <ActionMenu
                  triggerLabel={strings.orgAdmin.orgActions(orgLabelCap)}
                  disabled={exportingOrg}
                  items={[
                    ...(advanced
                      ? [{ label: strings.orgAdmin.rename, icon: <Pencil size={14} />, onSelect: () => setRenameModalOpen(true) }]
                      : []),
                    {
                      label: `Export ${orgLabel} bundle`,
                      icon: <Download size={14} />,
                      onSelect: exportOrg,
                    },
                  ]}
                />
              </div>
            </div>

            {renameModalOpen && (
              <Modal title={strings.orgAdmin.rename} onClose={() => setRenameModalOpen(false)}>
                <div className="stack">
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.rename}
                    <input
                      className="input"
                      autoFocus
                      value={orgNameEdit}
                      onChange={(e) => setOrgNameEdit(e.target.value)}
                    />
                  </label>
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.renameHint(orgLabel)}</span>
                  {renameError && <div style={{ color: "var(--color-danger)" }}>{renameError}</div>}
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn" onClick={() => setRenameModalOpen(false)}>
                      {strings.common.cancel}
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={renameOrg}
                      disabled={!orgNameEdit.trim() || orgNameEdit === org.name}
                    >
                      {strings.common.save}
                    </button>
                  </div>
                </div>
              </Modal>
            )}

            <CollapsibleSection sectionKey="orgAdmin.importMerge" title={strings.importMerge.action(orgLabel)} defaultCollapsed>
              <p className="text-muted" style={{ margin: 0 }}>{strings.importMerge.hint(orgLabel)}</p>
              {!importMergeConflicts && !importMergeResult && (
                <div className="stack">
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.importMerge.chooseFile}
                    <input
                      type="file" accept=".zip,application/zip"
                      onChange={(e) => setImportMergeFile(e.target.files?.[0] ?? null)}
                    />
                  </label>
                  <button
                    className="btn btn-primary" onClick={previewImportMerge}
                    disabled={!importMergeFile || importMergePreviewing} style={{ alignSelf: "flex-start" }}
                  >
                    <Upload size={14} /> {importMergePreviewing ? strings.importMerge.previewing : strings.importMerge.preview}
                  </button>
                </div>
              )}
              {importMergeConflicts && !importMergeResult && (
                <div className="stack">
                  {importMergeConflicts.length === 0 ? (
                    <p>{strings.importMerge.noConflicts}</p>
                  ) : (
                    <ImportConflictPanel
                      conflicts={importMergeConflicts}
                      resolutions={importMergeResolutions}
                      onResolutionChange={(id, value) => setImportMergeResolutions((r) => ({ ...r, [id]: value }))}
                    />
                  )}
                  <div className="row">
                    <button
                      className="btn btn-primary" onClick={confirmImportMerge} disabled={importMergeSubmitting}
                    >
                      {importMergeSubmitting ? strings.importMerge.importing : strings.importMerge.confirmImport}
                    </button>
                    <button className="btn" onClick={cancelImportMerge} disabled={importMergeSubmitting}>
                      {strings.importMerge.cancel}
                    </button>
                  </div>
                </div>
              )}
              {importMergeResult && (
                <div className="card stack">
                  <strong>{strings.importMerge.resultTitle}</strong>
                  <ul style={{ margin: 0 }}>
                    <li>{strings.importMerge.projectsImported(importMergeResult.projects_imported)}</li>
                    <li>{strings.importMerge.projectsSkipped(importMergeResult.projects_skipped)}</li>
                    <li>{strings.importMerge.reportTemplatesImported(importMergeResult.report_templates_imported)}</li>
                    <li>{strings.importMerge.reportTemplatesOverwritten(importMergeResult.report_templates_overwritten)}</li>
                  </ul>
                  {importMergeResult.warnings.length > 0 && (
                    <ul style={{ margin: 0, color: "var(--color-warning, #b58900)" }}>
                      {importMergeResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  )}
                  <button className="btn" onClick={() => setImportMergeResult(null)} style={{ alignSelf: "flex-start" }}>
                    {strings.common.close}
                  </button>
                </div>
              )}
              {importMergeError && <div style={{ color: "var(--color-danger)" }}>{importMergeError}</div>}
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.resources" title={strings.orgAdmin.resources} defaultCollapsed>
              {resources.map((r) => (
                <div key={r.id} className="row" style={{ justifyContent: "space-between" }}>
                  <a href={fileUrl(r.id)} target="_blank" rel="noreferrer">
                    {r.filename}
                  </a>
                  <button
                    className="btn btn-danger"
                    title={strings.orgAdmin.deleteResource(r.filename)}
                    aria-label={strings.orgAdmin.deleteResource(r.filename)}
                    onClick={() => deleteResource(r.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <FileUploadTrigger onSelect={uploadResource}>
                <Upload size={14} /> {strings.common.chooseFile}
              </FileUploadTrigger>
              <span className="text-muted row">{strings.orgAdmin.resourcesHint(orgLabel)}</span>
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "users" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.users" title={strings.orgAdmin.users(orgLabelCap)}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.5rem" }}>
                <div className="stack" style={{ gap: "0.25rem" }}>
                  <div className="row" style={{ gap: "0.5rem" }}>
                    <button className="btn" onClick={() => setInviteUserModalOpen(true)}>
                      <Send size={14} /> {strings.orgAdmin.inviteUser}
                    </button>
                    <button className="btn btn-primary" onClick={() => setNewUserModalOpen(true)}>
                      <Plus size={14} /> {strings.orgAdmin.newUser}
                    </button>
                  </div>
                  {/* "New user" (immediate password account) vs. "Invite
                      user" (email sign-up link) — distinct, both-legitimate
                      flows (docs/decisions.md) that read as ambiguous
                      without this hint. */}
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.newUserVsInviteHint}</span>
                </div>
                {advanced?.auto_accept_email_domain && (
                  <button
                    className={`btn${outsideDomainUsers !== null ? " btn-primary" : ""}`}
                    onClick={toggleOutsideDomainUsers}
                  >
                    {strings.orgAdmin.showOutsideDomainUsers}
                  </button>
                )}
              </div>
              {outsideDomainError && <div style={{ color: "var(--color-danger)" }}>{outsideDomainError}</div>}
              {outsideDomainUsers !== null && (
                <div className="card stack">
                  <strong>{strings.orgAdmin.outsideDomainUsers(orgLabel)}</strong>
                  <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.outsideDomainUsersHint(orgLabel)}</p>
                  {outsideDomainUsers.length === 0 ? (
                    <p className="text-muted">{strings.orgAdmin.noOutsideDomainUsers(orgLabel)}</p>
                  ) : (
                    <div style={{ overflowX: "auto" }}>
                      <table>
                        <thead>
                          <tr>
                            <th>{strings.orgAdmin.email}</th>
                            <th>{strings.orgAdmin.name}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {outsideDomainUsers.map((u) => (
                            <tr key={u.user_id}>
                              <td>{u.email}</td>
                              <td>{u.display_name}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Rebuilt on the shared `DirectoryTable` (Phase 0), with
                  `FilterPanel` as a full-width bar ABOVE the table rather
                  than the standard `.side-grid` side layout every other
                  list page uses (2026-08-31, Phase A, follow-up UX batch;
                  moved to `layout="top"` in a later follow-up fix — see
                  docs/decisions.md and docs/ux-style-guide.md's "Pattern:
                  filter panel placement — side vs. top"). This table has 6
                  columns (Email, Name, Role, Last login, 2FA, Actions) —
                  wide enough that a 240px side sidebar visibly crowded it. */}
              <div className="stack">
                <FilterPanel
                  layout="top"
                  sectionKey="orgAdminUsersFilters"
                  search={userSearch}
                  onSearchChange={handleUserSearchChange}
                  searchPlaceholder={strings.orgAdmin.searchUsers}
                >
                  {/* `strings.orgAdmin.orgRole` — distinct label text from
                      the "New user" modal's own "Role" field, deliberately:
                      that modal renders via a portal to `document.body`
                      while this page stays mounted behind it, so an
                      unscoped `getByLabel("Role")` while both are visible
                      would otherwise be ambiguous. */}
                  <FilterField label={strings.orgAdmin.orgRole(orgLabelCap)}>
                    <select
                      className="input"
                      value={userRoleFilter}
                      onChange={(e) => applyUserFilters({ role: e.target.value as OrgRole | "" })}
                    >
                      <option value="">{strings.orgAdmin.allRoles}</option>
                      <option value="member">{ORG_ROLE_LABEL.member}</option>
                      <option value="project_creator">{ORG_ROLE_LABEL.project_creator}</option>
                      <option value="org_admin">{ORG_ROLE_LABEL.org_admin}</option>
                    </select>
                  </FilterField>
                  <FilterCheckbox
                    label={strings.orgAdmin.filterStale}
                    checked={userFilterStale}
                    onChange={(checked) => applyUserFilters({ stale: checked })}
                  />
                  <FilterCheckbox
                    label={strings.orgAdmin.filterNo2fa}
                    checked={userFilterNo2fa}
                    onChange={(checked) => applyUserFilters({ no2fa: checked })}
                  />
                  <FilterCheckbox
                    label={strings.orgAdmin.filterNoProjectAccess}
                    checked={userFilterNoAccess}
                    onChange={(checked) => applyUserFilters({ noAccess: checked })}
                  />
                  <FilterCheckbox
                    label={strings.orgAdmin.filterShowInvited}
                    checked={showInvitedUsers}
                    onChange={setShowInvitedUsers}
                  />
                </FilterPanel>
                <DirectoryTable
                  ariaLabel={strings.orgAdmin.users(orgLabelCap)}
                  columns={usersColumns}
                  rows={usersRows}
                  rowKey={(row) => (row.kind === "user" ? `user-${row.user.user_id}` : `invited-${row.invite.id}`)}
                  sort={userSort}
                  onSort={(key) => applyUserSort(key as OrgUserSortKey)}
                  total={usersTotal + filteredOrgInvites.length}
                  onLoadMore={() => loadUsers(currentUserFilters(), userSearch, users.length, true)}
                  emptyState={<p className="text-muted">{strings.orgAdmin.noUsersFound}</p>}
                />
              </div>
            </CollapsibleSection>

            {newUserModalOpen && (
              <Modal title={strings.orgAdmin.newUser} onClose={() => setNewUserModalOpen(false)}>
                <div className="stack">
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.email}
                    <input
                      className="input"
                      type="email"
                      autoFocus
                      value={newUserEmail}
                      onChange={(e) => setNewUserEmail(e.target.value)}
                    />
                  </label>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.name}
                    <input className="input" value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
                  </label>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.password}
                    <input
                      className="input"
                      type="password"
                      value={newUserPassword}
                      onChange={(e) => setNewUserPassword(e.target.value)}
                    />
                  </label>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.role}
                    <select className="input" value={newUserRole} onChange={(e) => setNewUserRole(e.target.value as OrgRole)}>
                      <option value="member">{ORG_ROLE_LABEL.member}</option>
                      <option value="project_creator">{ORG_ROLE_LABEL.project_creator}</option>
                      <option value="org_admin">{ORG_ROLE_LABEL.org_admin}</option>
                    </select>
                  </label>
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn" onClick={() => setNewUserModalOpen(false)}>
                      {strings.common.cancel}
                    </button>
                    <button className="btn btn-primary" onClick={createUser} disabled={!newUserEmail || !newUserName || !newUserPassword}>
                      {strings.common.create}
                    </button>
                  </div>
                </div>
              </Modal>
            )}

            {inviteUserModalOpen && (
              <Modal title={strings.orgAdmin.inviteUser} onClose={() => setInviteUserModalOpen(false)}>
                <div className="stack">
                  <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.inviteUserModalHint}</p>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.orgAdmin.email}
                    <input
                      className="input"
                      type="email"
                      autoFocus
                      value={inviteUserEmail}
                      onChange={(e) => setInviteUserEmail(e.target.value)}
                    />
                  </label>
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn" onClick={() => setInviteUserModalOpen(false)}>
                      {strings.common.cancel}
                    </button>
                    <button className="btn btn-primary" onClick={inviteOrgUser} disabled={!inviteUserEmail}>
                      {strings.orgAdmin.sendInvite}
                    </button>
                  </div>
                </div>
              </Modal>
            )}

            {viewingUser && (
              <SidePanel title={strings.orgAdmin.userAccessTitle(viewingUser.display_name)} onClose={() => setViewingUser(null)}>
                {userAccessError && <div style={{ color: "var(--color-danger)" }}>{userAccessError}</div>}
                {!userAccess && !userAccessError && <Spinner />}
                {userAccess && (
                  <div className="stack">
                    <div className="stack" style={{ gap: "0.25rem" }}>
                      <strong>{strings.orgAdmin.userAccessOrgGroups(orgLabelCap)}</strong>
                      {userAccess.org_groups.length === 0 ? (
                        <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.userAccessNoOrgGroups(orgLabel)}</p>
                      ) : (
                        <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                          {userAccess.org_groups.map((g) => (
                            <li key={g.id}>{g.name}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="stack" style={{ gap: "0.25rem" }}>
                      <strong>{strings.orgAdmin.userAccessProjects}</strong>
                      {userAccess.projects.length === 0 ? (
                        <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.userAccessNoProjects}</p>
                      ) : (
                        userAccess.projects.map((p) => {
                          const isExpanded = expandedAccessProjectIds.has(p.project_id);
                          const collapsedRoles = collapseProjectRoles(p.roles);
                          const canExpand = collapsedRoles.length < p.roles.length;
                          const shownRoles = isExpanded ? p.roles : collapsedRoles;
                          return (
                            <div key={p.project_id} className="card stack" style={{ gap: "0.4rem" }}>
                              <Link to={`/projects/${p.project_id}`}>{p.project_name}</Link>
                              <div className="row" style={{ gap: "0.25rem", flexWrap: "wrap", alignItems: "center" }}>
                                {shownRoles.map((r) => (
                                  <span key={r} className="badge">{PROJECT_ROLE_LABEL[r]}</span>
                                ))}
                                {canExpand && (
                                  <button
                                    type="button"
                                    className="btn"
                                    style={{ fontSize: "0.75rem", padding: "0.15rem 0.5rem" }}
                                    onClick={() => toggleAccessProjectExpanded(p.project_id)}
                                  >
                                    {isExpanded
                                      ? strings.orgAdmin.userAccessShowFewerRoles
                                      : strings.orgAdmin.userAccessShowAllRoles(p.roles.length)}
                                  </button>
                                )}
                              </div>
                              {p.project_groups.length > 0 && (
                                <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                                  {strings.orgAdmin.userAccessProjectGroups}: {p.project_groups.map((g) => g.name).join(", ")}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </SidePanel>
            )}
          </div>
        )}

        {activeGroup === "groups" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.groups" title={strings.orgAdmin.groups(orgLabelCap)}>
              <button
                className="btn btn-primary"
                style={{ alignSelf: "flex-start" }}
                onClick={() => setNewGroupModalOpen(true)}
              >
                <Plus size={14} /> {strings.orgAdmin.newGroup}
              </button>
              {newGroupModalOpen && (
                // Style guide "Pattern: modal dialog for entity create/rename"
                // — a brand-new entity (a group) opens in a Modal, not a
                // Popover — the Popover-vs-Modal decision tree reserves
                // Popover for a one/two-field quick action on something
                // that already exists, not creating a new entity.
                <Modal title={strings.orgAdmin.newGroup} onClose={() => setNewGroupModalOpen(false)}>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.admin.name}
                    <input
                      className="input"
                      autoFocus
                      placeholder={strings.orgAdmin.groupNamePlaceholder}
                      value={newGroupName}
                      onChange={(e) => setNewGroupName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && newGroupName) createGroup();
                      }}
                    />
                  </label>
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn" onClick={() => setNewGroupModalOpen(false)}>
                      {strings.common.cancel}
                    </button>
                    <button className="btn btn-primary" onClick={createGroup} disabled={!newGroupName}>
                      {strings.common.create}
                    </button>
                  </div>
                </Modal>
              )}

              {/* Rebuilt on the shared `DirectoryTable` (Phase 0) inside the
                  standard `.side-grid` + `FilterPanel` layout, replacing the
                  old `CollapsibleSection`-of-`CollapsibleSection`s accordion
                  that rendered every group's full member list open and
                  inline, unconditionally (2026-08-31, Phase B, follow-up UX
                  batch — see docs/decisions.md). Each row now opens a
                  `SidePanel` instead — style guide "Pattern: entity detail
                  panel." */}
              <div className="side-grid">
                <div className="stack">
                  <DirectoryTable
                    ariaLabel={strings.orgAdmin.groups(orgLabelCap)}
                    columns={orgGroupColumns}
                    rows={groups}
                    rowKey={(row) => row.id}
                    sort={groupSort}
                    onSort={(key) => applyGroupSort(key as OrgGroupSortKey)}
                    total={groupsTotal}
                    onLoadMore={() => loadGroups(groupSearch, groups.length, true)}
                    onRowClick={(row) => setOpenOrgGroupId(row.id)}
                    emptyState={<p className="text-muted">{strings.orgAdmin.noGroupsFound}</p>}
                  />
                </div>
                <FilterPanel
                  sectionKey="orgAdminGroupsFilters"
                  search={groupSearch}
                  onSearchChange={handleGroupSearchChange}
                  searchPlaceholder={strings.orgAdmin.searchGroups}
                >
                  {/* No dedicated filter fields beyond search exist for
                      Groups today — `FilterPanel` is still the right shell
                      (consistent chrome/mobile-collapse with every other
                      directory), it just has nothing besides the header
                      search box to offer here. */}
                  {null}
                </FilterPanel>
              </div>
            </CollapsibleSection>

            {openOrgGroupId && (() => {
              const g = groups.find((x) => x.id === openOrgGroupId);
              if (!g) return null;
              const memberIds = new Set(g.member_user_ids);
              const members = users.filter((u) => memberIds.has(u.user_id));
              const nonMembers = users.filter((u) => !memberIds.has(u.user_id));
              const nestedGroupIds = new Set(g.member_org_group_ids);
              // Resolved against `allGroups` (every group in the org,
              // unpaginated), not the paginated/searched `groups` above —
              // a nested group's name, or a candidate to nest, can easily
              // fall outside whatever page/search the Groups list itself
              // is currently showing (2026-08 UX audit "Directories at
              // scale").
              const nestedGroups = allGroups.filter((og) => nestedGroupIds.has(og.id));
              const nestableGroups = allGroups.filter((og) => og.id !== g.id && !nestedGroupIds.has(og.id));
              // SSO-sync gating (2026-08-31 bug-fix pass): the name input,
              // role select, and Save action all sit behind this same
              // check now — previously only the role select was gated, so
              // the name field (and the ability to "save" a sync config)
              // was visible even with no SSO configured for the org at all.
              const ssoConfigured = !!(ssoConfig?.oidc_issuer_url && ssoConfig?.oidc_client_id);
              const syncEnabled = syncEnabledEdits[g.id] ?? g.idp_synced_group_name != null;
              return (
                <SidePanel title={strings.orgAdmin.groupDetails(g.name)} onClose={() => setOpenOrgGroupId(null)}>
                  <div className="stack">
                    {members.length > 0 && (
                      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {members.map((u) => (
                          <li key={u.user_id} style={{ listStyle: "disc" }}>
                            <span className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                              <span>
                                {u.display_name} <span className="text-muted">({u.email})</span>
                              </span>
                              <button
                                className="btn"
                                title={strings.admin.removeMember(u.display_name)}
                                aria-label={strings.admin.removeMember(u.display_name)}
                                onClick={() => removeGroupMember(g.id, u.user_id)}
                              >
                                <Trash2 size={14} />
                              </button>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <UserAutocomplete
                      users={nonMembers}
                      placeholder={strings.admin.addMemberPlaceholder}
                      onSelect={(userId) => addGroupMember(g.id, userId)}
                    />
                    {nestedGroups.length > 0 && (
                      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {nestedGroups.map((og) => (
                          <li key={og.id} style={{ listStyle: "circle" }}>
                            <span className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                              <span>{strings.orgAdmin.nestedGroupLabel(og.name)}</span>
                              <button
                                className="btn"
                                title={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                                aria-label={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                                onClick={() => removeNestedGroupMember(g.id, og.id)}
                              >
                                <Trash2 size={14} />
                              </button>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {nestableGroups.length > 0 && (
                      <div className="row">
                        <select
                          className="input"
                          value={nestSelections[g.id] ?? ""}
                          onChange={(e) => setNestSelections((prev) => ({ ...prev, [g.id]: e.target.value }))}
                        >
                          <option value="">{strings.orgAdmin.addNestedGroup}</option>
                          {nestableGroups.map((og) => (
                            <option key={og.id} value={og.id}>
                              {og.name}
                            </option>
                          ))}
                        </select>
                        <button
                          className="btn"
                          disabled={!nestSelections[g.id]}
                          title={strings.orgAdmin.addNestedGroup}
                          aria-label={strings.orgAdmin.addNestedGroup}
                          onClick={() => addNestedGroupMember(g.id, nestSelections[g.id])}
                        >
                          <Plus size={14} />
                        </button>
                      </div>
                    )}
                    {nestErrors[g.id] && <div style={{ color: "var(--color-danger)" }}>{nestErrors[g.id]}</div>}

                    {/* SSO sync sub-section — fully gated on `ssoConfigured`
                        (bug fix, see comment above): with no SSO configured,
                        only the muted hint renders, nothing else. */}
                    {ssoConfigured ? (
                      <div className="stack" style={{ gap: "0.5rem" }}>
                        <label className="row" style={{ gap: "0.4rem" }}>
                          <input
                            type="checkbox"
                            checked={syncEnabled}
                            onChange={(e) => toggleGroupSync(g.id, e.target.checked)}
                          />
                          {strings.orgAdmin.syncFromSso}
                        </label>
                        {syncEnabled && (
                          <>
                            <label className="row" style={{ gap: "0.25rem" }}>
                              {strings.orgAdmin.idpSyncedGroupName}
                              <input
                                className="input"
                                placeholder={strings.orgAdmin.idpSyncedGroupNamePlaceholder}
                                value={idpSyncEdits[g.id] ?? g.idp_synced_group_name ?? ""}
                                onChange={(e) => setIdpSyncEdits((prev) => ({ ...prev, [g.id]: e.target.value }))}
                              />
                            </label>
                            <label className="row" style={{ gap: "0.25rem" }}>
                              {strings.orgAdmin.grantedOrgRole}
                              <select
                                className="input"
                                value={grantedRoleEdits[g.id] ?? g.granted_org_role ?? ""}
                                onChange={(e) => setGrantedRoleEdits((prev) => ({ ...prev, [g.id]: e.target.value as OrgRole | "" }))}
                              >
                                <option value="">{strings.orgAdmin.grantedOrgRoleNone}</option>
                                <option value="member">{ORG_ROLE_LABEL.member}</option>
                                <option value="project_creator">{ORG_ROLE_LABEL.project_creator}</option>
                                <option value="org_admin">{ORG_ROLE_LABEL.org_admin}</option>
                              </select>
                            </label>
                            <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.grantedOrgRoleHint}</span>
                            <button
                              className="btn" style={{ alignSelf: "flex-start" }}
                              onClick={() =>
                                saveIdpSync(
                                  g.id,
                                  idpSyncEdits[g.id] ?? g.idp_synced_group_name ?? "",
                                  grantedRoleEdits[g.id] ?? g.granted_org_role ?? ""
                                )
                              }
                            >
                              {strings.orgAdmin.saveIdpSync}
                            </button>
                            {idpSyncErrors[g.id] && <div style={{ color: "var(--color-danger)" }}>{idpSyncErrors[g.id]}</div>}
                          </>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.ssoNotConfiguredHint(orgLabel)}</span>
                    )}
                  </div>
                </SidePanel>
              );
            })()}
          </div>
        )}

        {activeGroup === "projects-workflow" && (
          <div className="stack">
            {orgProjects && (
              <CollapsibleSection sectionKey="orgAdmin.projects" title={strings.orgAdmin.projects}>
                <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectsHint(orgLabel)}</p>
                {orgProjects.map((p) => (
                  <div key={p.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <span className="row" style={{ gap: "0.5rem" }}>
                        {p.name}
                        {p.is_archived && <span className="badge">{strings.projects.archived}</span>}
                      </span>
                      <button className="btn" onClick={() => openManageUsers(p)}>
                        {strings.orgAdmin.manageUsers}
                      </button>
                    </div>
                  </div>
                ))}
              </CollapsibleSection>
            )}

            {manageUsersProjectId && (
              // Phase 5 (docs/decisions.md; rebuilt in Phase D, follow-up UX
              // batch, 2026-08-31): the same `ProjectMembersTable`
              // `ProjectAdminPage.tsx`'s own Members section renders — this
              // is the direct fix for "should show up in a similar way to
              // the project admin page," not a parallel reimplementation.
              <Modal title={strings.orgAdmin.manageUsersModalTitle(manageUsersProjectName)} onClose={closeManageUsers} size="lg">
                <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
                  <button className="btn btn-primary" onClick={() => setManageUsersAddMemberModalOpen(true)}>
                    <Plus size={14} /> {strings.admin.addMember}
                  </button>
                  {/* No sibling "Add group" button (PR5 of the members/groups
                      directory rework plan, corrected during PR5's own
                      review): the autocomplete below is expanded to match
                      org groups too — see UserAutocomplete's own module
                      docstring. */}
                </div>
                {manageUsersAddMemberModalOpen && (
                  <Modal title={strings.admin.addMember} onClose={() => setManageUsersAddMemberModalOpen(false)}>
                    <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
                      <UserAutocomplete
                        users={users}
                        placeholder={strings.admin.addOrInviteMemberPlaceholder}
                        onSelect={(userId) => {
                          addManageUsersMember(userId);
                          setManageUsersAddMemberModalOpen(false);
                        }}
                        groups={allGroups}
                        onSelectGroup={(groupId) => {
                          addManageUsersGroupRole(groupId);
                          setManageUsersAddMemberModalOpen(false);
                        }}
                        organizationId={orgId}
                        projectId={manageUsersProjectId}
                        onSelectExternal={(email) => {
                          addManageUsersExternalMember(email);
                          setManageUsersAddMemberModalOpen(false);
                        }}
                      />
                      <select
                        className="input"
                        aria-label={strings.membersTable.addRoleSelectLabel}
                        value={manageUsersAddRole}
                        onChange={(e) => setManageUsersAddRole(e.target.value as ProjectRole)}
                      >
                        <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                        <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                        <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                        <option value="member">{PROJECT_ROLE_LABEL.member}</option>
                      </select>
                    </div>
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn" onClick={() => setManageUsersAddMemberModalOpen(false)}>
                        {strings.common.cancel}
                      </button>
                    </div>
                  </Modal>
                )}
                <ProjectMembersTable
                  members={manageUsersMembers}
                  invites={manageUsersInvites}
                  onToggleRole={toggleManageUsersRole}
                  onResendInvite={resendManageUsersInvite}
                  resendingInviteId={manageUsersResendingInviteId}
                  onRemoveAllAccess={removeAllManageUsersMemberAccess}
                  onConvertToDirect={convertManageUsersMemberToDirect}
                  ariaLabel={strings.orgAdmin.manageUsers}
                  availableModuleRoles={manageUsersAvailableModuleRoles}
                  onToggleModuleRole={toggleManageUsersModuleRole}
                />
              </Modal>
            )}

            <CollapsibleSection sectionKey="orgAdmin.projectStatuses" title={strings.orgAdmin.projectStatuses}>
              <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectStatusesHint}</p>
              <DefinitionList
                items={projectStatuses}
                fields={[{ key: "name", getValue: (i) => i.name, placeholder: strings.admin.name, maxWidth: 220 }]}
                getReassignLabel={(i) => i.name}
                onMove={moveProjectStatus}
                onRename={(id, values) => renameProjectStatus(id, values.name)}
                onAdd={(values) => addProjectStatus(values.name)}
                onDelete={deleteProjectStatus}
                deleteLabel={strings.orgAdmin.deleteProjectStatus}
                addLabel={strings.orgAdmin.newProjectStatus}
              />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.linkTypes" title={strings.orgAdmin.linkTypes}>
              <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypesHint}</p>
              <DefinitionList
                items={linkTypes}
                fields={[
                  { key: "forward", getValue: (i) => i.forward_name, placeholder: strings.orgAdmin.forwardName, ariaLabel: strings.orgAdmin.forwardName, maxWidth: 200 },
                  { key: "reverse", getValue: (i) => i.reverse_name, placeholder: strings.orgAdmin.reverseName, ariaLabel: strings.orgAdmin.reverseName, maxWidth: 200 },
                ]}
                getReassignLabel={(i) => i.forward_name}
                onMove={moveLinkType}
                onRename={(id, values) => renameLinkType(id, values.forward, values.reverse)}
                onAdd={(values) => addLinkType(values.forward, values.reverse)}
                onDelete={deleteLinkType}
                deleteLabel={strings.orgAdmin.deleteLinkType}
                addLabel={strings.orgAdmin.newLinkType}
              />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "branding-defaults" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.branding" title={strings.orgAdmin.branding}>
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-logo-input">{strings.orgAdmin.logo(orgLabel)}</label>
                  <OverridePill custom={org.logo_file_id != null} onReset={removeLogo} disabled={logoUploading} />
                </span>
                <FileUploadTrigger id="org-logo-input" accept="image/*" disabled={logoUploading} onSelect={uploadLogo}>
                  <Upload size={14} /> {strings.common.chooseFile}
                </FileUploadTrigger>
              </div>
              {logoUploading && <Spinner />}
              {logoError && <div style={{ color: "var(--color-danger)" }}>{logoError}</div>}
              {logoUploaded && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.logoUploaded}</div>}
              {org.logo_file_id && <img src={fileUrl(org.logo_file_id)} alt="" style={{ height: 40 }} />}

              {/* Login-background sits alongside the org logo (style guide
                  "after" diagram, G4a: "Branding — logo, colour, footer") —
                  moved here from the SSO section, where it previously sat
                  for no reason connected to SSO/OIDC itself. */}
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-login-background-input">{strings.orgAdmin.loginBackground}</label>
                  <OverridePill
                    custom={org.login_background_file_id != null}
                    onReset={removeLoginBackground}
                    disabled={loginBackgroundUploading}
                  />
                </span>
                <FileUploadTrigger
                  id="org-login-background-input"
                  accept="image/*"
                  disabled={loginBackgroundUploading}
                  onSelect={uploadLoginBackground}
                >
                  <Upload size={14} /> {strings.common.chooseFile}
                </FileUploadTrigger>
              </div>
              {loginBackgroundUploading && <Spinner />}
              {loginBackgroundError && <div style={{ color: "var(--color-danger)" }}>{loginBackgroundError}</div>}
              {loginBackgroundUploaded && (
                <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.loginBackgroundUploaded}</div>
              )}
              {org.login_background_file_id && (
                <img src={fileUrl(org.login_background_file_id)} alt="" style={{ maxHeight: 100, borderRadius: 4 }} />
              )}

              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-header-title">{strings.orgAdmin.headerTitle}</label>
                  <OverridePill custom={org.header_title != null} onReset={() => setHeaderTitleInput("")} />
                </span>
                <input
                  id="org-header-title"
                  className="input" placeholder={strings.appName}
                  value={headerTitleInput} onChange={(e) => setHeaderTitleInput(e.target.value)}
                />
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.headerTitleHint}</span>
              </div>
              <label className="row">
                <input type="checkbox" checked={useOwnAccentColor} onChange={(e) => setUseOwnAccentColor(e.target.checked)} />
                {strings.orgAdmin.useOwnAccentColor(orgLabel)}
              </label>
              {useOwnAccentColor && (
                <input
                  type="color" value={accentColorInput} onChange={(e) => setAccentColorInput(e.target.value)}
                  style={{ width: 60, height: 36, padding: 2 }}
                />
              )}
              <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)" }} />
              <h4 style={{ margin: 0 }}>{strings.orgAdmin.emailFooterTitle}</h4>
              <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.orgAdmin.emailFooterHint(orgLabel)}</p>
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-email-footer-company">{strings.orgAdmin.emailFooterCompanyName}</label>
                  <OverridePill custom={org.email_footer_company_name != null} onReset={() => setEmailFooterCompanyNameInput("")} />
                </span>
                <input
                  id="org-email-footer-company"
                  className="input"
                  value={emailFooterCompanyNameInput} onChange={(e) => setEmailFooterCompanyNameInput(e.target.value)}
                />
              </div>
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-email-footer-website">{strings.orgAdmin.emailFooterWebsite}</label>
                  <OverridePill custom={org.email_footer_website != null} onReset={() => setEmailFooterWebsiteInput("")} />
                </span>
                <input
                  id="org-email-footer-website"
                  className="input"
                  value={emailFooterWebsiteInput} onChange={(e) => setEmailFooterWebsiteInput(e.target.value)}
                />
              </div>
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <label htmlFor="org-email-footer-address">{strings.orgAdmin.emailFooterAddress}</label>
                  <OverridePill custom={org.email_footer_address != null} onReset={() => setEmailFooterAddressInput("")} />
                </span>
                <textarea
                  id="org-email-footer-address"
                  className="input" rows={3}
                  value={emailFooterAddressInput} onChange={(e) => setEmailFooterAddressInput(e.target.value)}
                />
              </div>
              {brandingError && <div style={{ color: "var(--color-danger)" }}>{brandingError}</div>}
              <button className="btn btn-primary" onClick={saveBranding} style={{ alignSelf: "flex-start" }}>
                {strings.orgAdmin.saveBranding}
              </button>
            </CollapsibleSection>

            {templateProjects.length > 0 && (
              <CollapsibleSection sectionKey="orgAdmin.defaultTemplate" title={strings.orgAdmin.defaultTemplate}>
                <select
                  className="input"
                  value={org.default_template_project_id ?? ""}
                  onChange={(e) => setDefaultTemplate(e.target.value)}
                >
                  <option value="">{strings.projects.noTemplate}</option>
                  {templateProjects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </CollapsibleSection>
            )}
          </div>
        )}

        {activeGroup === "templates-reports" && (
          <div className="stack">
            {orgReportDefaultsAvailable && (
              <CollapsibleSection sectionKey="orgAdmin.reportDefaults" title="Report Defaults">
                <p className="text-muted" style={{ margin: 0 }}>
                  Used as the default intro, body chapters, and appendices for any project in this {orgLabel} that
                  hasn't set its own — see each project's Report Setup tab.
                </p>
                <div className="stack" style={{ gap: "0.25rem" }}>
                  <span>Default intro</span>
                  <RichTextEditor rows={3} value={orgReportIntro} onChange={setOrgReportIntro} organizationId={orgId} />
                </div>
                <ReportChapterListEditor
                  label="Default body chapters" list={orgReportChapters} setList={setOrgReportChapters} organizationId={orgId}
                />
                <ReportChapterListEditor
                  label="Default appendices" list={orgReportAppendices} setList={setOrgReportAppendices} organizationId={orgId}
                />
                <button className="btn btn-primary" onClick={saveOrgReportDefaults} style={{ alignSelf: "flex-start" }}>
                  {strings.admin.saveSettings}
                </button>
              </CollapsibleSection>
            )}

            <CollapsibleSection sectionKey="orgAdmin.reportTemplates" title={strings.admin.reportTemplates}>
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn btn-primary" onClick={openNewTemplateForm}>
                  <Plus size={14} /> {strings.admin.newReportTemplate}
                </button>
              </div>
              {reportTemplates.map((tpl) => (
                <div key={tpl.id} className="row" style={{ justifyContent: "space-between" }}>
                  <span>
                    {tpl.name} <span className="badge" style={{ background: tpl.accent_color_hex }}>&nbsp;&nbsp;</span>
                  </span>
                  <div className="row" style={{ gap: "0.4rem" }}>
                    <button className="btn" onClick={() => startEditTemplate(tpl)}>
                      {strings.common.edit}
                    </button>
                    <button
                      className="btn btn-danger"
                      title={strings.orgAdmin.deleteReportTemplate(tpl.name)}
                      aria-label={strings.orgAdmin.deleteReportTemplate(tpl.name)}
                      onClick={() => deleteReportTemplate(tpl.id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </CollapsibleSection>
            {templateFormOpen && (
              <Modal
                title={editingTemplateId ? strings.admin.editReportTemplate : strings.admin.newReportTemplate}
                onClose={closeTemplateForm}
                size="lg"
              >
                <div className="row">
                  <input
                    className="input" placeholder={strings.admin.templateName}
                    value={newTemplateName} onChange={(e) => setNewTemplateName(e.target.value)}
                  />
                  <label className="row" style={{ gap: "0.4rem" }}>
                    {strings.admin.accentColor}
                    <input
                      type="color" value={newTemplateAccentColor} onChange={(e) => setNewTemplateAccentColor(e.target.value)}
                      style={{ width: 44, height: 32, padding: 2 }}
                    />
                  </label>
                </div>
                <div className="row">
                  <label className="row" style={{ gap: "0.4rem" }}>
                    <input
                      type="checkbox" checked={newTemplateIncludeCoverPage}
                      onChange={(e) => setNewTemplateIncludeCoverPage(e.target.checked)}
                    />
                    {strings.admin.includeCoverPage}
                  </label>
                  <label className="row" style={{ gap: "0.4rem" }}>
                    <input
                      type="checkbox" checked={newTemplateIncludeLogo}
                      onChange={(e) => setNewTemplateIncludeLogo(e.target.checked)}
                    />
                    {strings.admin.includeLogo(orgLabel)}
                  </label>
                </div>
                <input
                  className="input" placeholder={strings.admin.footerText}
                  value={newTemplateFooterText} onChange={(e) => setNewTemplateFooterText(e.target.value)}
                />
                <div className="stack" style={{ gap: "0.25rem" }}>
                  <span>{strings.admin.templateIntro}</span>
                  <RichTextEditor rows={3} value={newTemplateIntro} onChange={setNewTemplateIntro} organizationId={orgId} />
                </div>
                <ReportChapterListEditor
                  label={strings.admin.templateChapters} list={newTemplateChapters} setList={setNewTemplateChapters}
                  organizationId={orgId}
                />
                <ReportChapterListEditor
                  label={strings.admin.templateAppendices} list={newTemplateAppendices} setList={setNewTemplateAppendices}
                  organizationId={orgId}
                />
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.admin.templateContentHint(orgLabel)}</span>
                <label className="row" style={{ gap: "0.4rem" }}>
                  <input
                    type="checkbox" checked={newTemplateChaptersPerComponent}
                    onChange={(e) => setNewTemplateChaptersPerComponent(e.target.checked)}
                  />
                  {strings.admin.templateChaptersPerComponent}
                </label>
                <div className="row">
                  <button className="btn btn-primary" onClick={saveReportTemplate} disabled={!newTemplateName}>
                    <Plus size={14} /> {editingTemplateId ? strings.common.save : strings.common.create}
                  </button>
                  <button className="btn" onClick={closeTemplateForm}>
                    {strings.common.cancel}
                  </button>
                </div>
              </Modal>
            )}
          </div>
        )}

        {activeGroup === "oauth-sso" && (
          <div className="stack">
            {ssoConfig && (
              <CollapsibleSection sectionKey="orgAdmin.sso" title={strings.orgAdmin.ssoConfig}>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.slug}
                  <input className="input" value={slugInput} onChange={(e) => setSlugInput(e.target.value)} />
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                    {strings.orgAdmin.slugHint(orgLabel).replace("{slug}", slugInput || "…")}
                  </span>
                </label>
                <label className="row">
                  <input type="checkbox" checked={ssoEnabled} onChange={(e) => setSsoEnabled(e.target.checked)} />
                  {strings.orgAdmin.ssoEnabled}
                </label>
                <label className="row">
                  <input type="checkbox" checked={ssoOnly} onChange={(e) => setSsoOnly(e.target.checked)} />
                  {strings.orgAdmin.ssoOnly}
                </label>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.oidcIssuerUrl}
                  <input className="input" value={oidcIssuerUrl} onChange={(e) => setOidcIssuerUrl(e.target.value)} />
                </label>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.oidcClientId}
                  <input className="input" value={oidcClientId} onChange={(e) => setOidcClientId(e.target.value)} />
                </label>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.oidcClientSecret}
                  <input
                    className="input" type="password" value={oidcClientSecret}
                    onChange={(e) => setOidcClientSecret(e.target.value)}
                  />
                </label>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.oidcRequiredGroup}
                  <input
                    className="input" value={oidcRequiredGroup}
                    onChange={(e) => setOidcRequiredGroup(e.target.value)}
                  />
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.oidcRequiredGroupHint}</span>
                </label>

                {/* SSO group → org-role mapping used to live here, as a
                    flat, disconnected list (`sso_group_mappings`) — it's
                    now a property of the org group being synced into
                    instead (`OrgGroup.granted_org_role`, alongside
                    `idp_synced_group_name`), managed from the Groups
                    section (2026-08 UX audit roadmap item 522). */}
                <p className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.orgAdmin.ssoMappingsMovedHint}</p>

                {ssoError && <div style={{ color: "var(--color-danger)" }}>{ssoError}</div>}
                <button className="btn btn-primary" onClick={saveSso} style={{ alignSelf: "flex-start" }}>
                  {strings.orgAdmin.saveSso}
                </button>
              </CollapsibleSection>
            )}

            {scimStatus && (
              <CollapsibleSection sectionKey="orgAdmin.scim" title={strings.orgAdmin.scimProvisioning}>
                <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.scimHint}</p>
                <div className="row">
                  <span>
                    {scimStatus.enabled
                      ? strings.orgAdmin.scimEnabledWithPrefix(scimStatus.token_prefix ?? "")
                      : strings.orgAdmin.scimDisabled}
                  </span>
                </div>
                {scimGeneratedToken && (
                  <div className="stack" style={{ gap: "0.25rem" }}>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.scimTokenShownOnce}</span>
                    <input className="input" readOnly value={scimGeneratedToken} onFocus={(e) => e.target.select()} />
                  </div>
                )}
                {scimError && <div style={{ color: "var(--color-danger)" }}>{scimError}</div>}
                <div className="row">
                  <button className="btn btn-primary" onClick={regenerateScimToken}>
                    {scimStatus.enabled ? strings.orgAdmin.scimRegenerate : strings.orgAdmin.scimGenerate}
                  </button>
                  {scimStatus.enabled && (
                    <button className="btn btn-danger" onClick={revokeScimToken}>
                      {strings.orgAdmin.scimRevoke}
                    </button>
                  )}
                </div>
              </CollapsibleSection>
            )}
          </div>
        )}

        {activeGroup === "email" && (
          <div className="stack">
            {advanced && (
              <CollapsibleSection sectionKey="orgAdmin.smtpEmail" title={strings.orgAdmin.smtpEmailTitle}>
                <div className="row">
                  <input
                    className="input"
                    placeholder={strings.orgAdmin.smtpHost}
                    value={smtpHost}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setSmtpHost(e.target.value);
                    }}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 120 }}
                    placeholder={strings.orgAdmin.smtpPort}
                    value={smtpPort}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setSmtpPort(e.target.value);
                    }}
                  />
                </div>
                <div className="row">
                  <input
                    className="input"
                    placeholder={strings.orgAdmin.smtpUsername}
                    value={smtpUsername}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setSmtpUsername(e.target.value);
                    }}
                  />
                  <input
                    className="input"
                    type="password"
                    placeholder={strings.orgAdmin.smtpPassword}
                    value={smtpPassword}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setSmtpPassword(e.target.value);
                    }}
                  />
                </div>
                <label className="row">
                  <input
                    type="checkbox"
                    checked={smtpUseTls}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setSmtpUseTls(e.target.checked);
                    }}
                  />
                  {strings.orgAdmin.smtpUseTls}
                </label>

                <div className="stack" style={{ gap: "0.4rem" }}>
                  <strong>{strings.orgAdmin.testEmail}</strong>
                  <span className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.orgAdmin.testEmailHint(orgLabel)}</span>
                  <div className="row">
                    <input
                      className="input"
                      type="email"
                      placeholder={strings.orgAdmin.testEmailRecipientPlaceholder}
                      value={testEmailRecipient}
                      onChange={(e) => setTestEmailRecipient(e.target.value)}
                    />
                    <button className="btn" onClick={sendOrgTestEmail} disabled={!smtpHost || sendingTestEmail}>
                      {sendingTestEmail ? strings.orgAdmin.testEmailSending : strings.orgAdmin.testEmail}
                    </button>
                  </div>
                  {!smtpHost && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.testEmailNoSmtp}</span>}
                  {testEmailError && <div style={{ color: "var(--color-danger)" }}>{testEmailError}</div>}
                  {testEmailSuccess && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.testEmailSent}</div>}
                </div>
                {/* SMTP fields are part of the same `OrgAdvancedSettings`
                    object the Security group's own save button submits —
                    previously a shared button on the same page ("saved
                    with the Security settings below"), now its own
                    explicit button now that Email and Security are
                    separate top-level groups (2026-08 UX audit roadmap
                    item 523). See the SSO mappings save button's own
                    comment for why calling the same `saveAdvanced()` from
                    here is still correct. */}
                {advancedError && <div style={{ color: "var(--color-danger)" }}>{advancedError}</div>}
                <button
                  className="btn btn-primary"
                  onClick={saveAdvanced}
                  disabled={selfSignupConflict}
                  style={{ alignSelf: "flex-start" }}
                >
                  {strings.orgAdmin.saveEmailSettings}
                </button>
              </CollapsibleSection>
            )}
          </div>
        )}

        {activeGroup === "security" && (
          <div className="stack">
            {advanced && (
              <CollapsibleSection sectionKey="orgAdmin.security" title={strings.orgAdmin.securityTitle}>
                <label className="row" style={{ gap: "0.6rem" }}>
                  <ToggleSwitch
                    checked={require2fa}
                    onChange={(next) => {
                      advancedDirtyRef.current = true;
                      setRequire2fa(next);
                    }}
                    label={strings.orgAdmin.require2fa}
                  />
                  <span className="stack" style={{ gap: 0 }}>
                    {strings.orgAdmin.require2fa}
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.require2faHint(orgLabel)}</span>
                  </span>
                </label>

                <label className="row" style={{ gap: "0.6rem" }}>
                  <ToggleSwitch
                    checked={allowSelfSignup}
                    onChange={(next) => {
                      advancedDirtyRef.current = true;
                      setAllowSelfSignup(next);
                    }}
                    label={strings.orgAdmin.allowSelfSignup}
                  />
                  <span className="stack" style={{ gap: 0 }}>
                    {strings.orgAdmin.allowSelfSignup}
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.allowSelfSignupHint(orgLabel)}</span>
                  </span>
                </label>

                {selfSignupConflict && (
                  <div style={{ color: "var(--color-danger)" }}>{strings.orgAdmin.selfSignupSsoConflict(orgLabel)}</div>
                )}

                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.autoAcceptEmailDomain}
                  <input
                    className="input"
                    placeholder="acme.com"
                    value={autoAcceptEmailDomain}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setAutoAcceptEmailDomain(e.target.value);
                    }}
                  />
                  <span className="text-muted">{strings.orgAdmin.autoAcceptEmailDomainHint}</span>
                </label>

                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.externalUserPolicy}
                  <select
                    className="input"
                    value={externalUserPolicy}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setExternalUserPolicy(e.target.value as ExternalUserPolicy);
                    }}
                  >
                    <option value="disabled">{strings.orgAdmin.externalUserPolicyDisabled(orgLabel)}</option>
                    <option value="org_domain_only">{strings.orgAdmin.externalUserPolicyDomainOnly}</option>
                    <option value="anyone">{strings.orgAdmin.externalUserPolicyAnyone}</option>
                  </select>
                </label>

                <label className="row" style={{ gap: "0.6rem" }}>
                  <ToggleSwitch
                    checked={allowRelaxedChildProjectCreation}
                    onChange={(next) => {
                      advancedDirtyRef.current = true;
                      setAllowRelaxedChildProjectCreation(next);
                    }}
                    label={strings.orgAdmin.allowRelaxedChildProjectCreation}
                  />
                  <span className="stack" style={{ gap: 0 }}>
                    {strings.orgAdmin.allowRelaxedChildProjectCreation}
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.allowRelaxedChildProjectCreationHint}</span>
                  </span>
                </label>

                {advancedError && <div style={{ color: "var(--color-danger)" }}>{advancedError}</div>}
                {/* `onClick={saveAdvanced}` submits the *whole*
                    `OrgAdvancedSettings` object — SMTP/email (its own
                    "Email" group now) and the SSO mappings (its own
                    "OAuth/SSO" group) are all part of the same underlying
                    settings resource/PUT, just split across three separate
                    top-level resource-menu groups by what they actually
                    govern (2026-08 UX audit roadmap item 523, splitting
                    the earlier "Integrations & security" group further)
                    rather than one combined page. Each group that touches
                    a field on this object now has its own save button
                    calling the same `saveAdvanced()` — see the SSO
                    mappings and SMTP & email save buttons' own comments —
                    since every field lives in this one component's shared
                    state regardless of which group is currently
                    rendered. */}
                <button
                  className="btn btn-primary"
                  onClick={saveAdvanced}
                  disabled={selfSignupConflict}
                  style={{ alignSelf: "flex-start" }}
                >
                  {strings.orgAdmin.saveAdvanced}
                </button>
              </CollapsibleSection>
            )}

            {advanced && (
              <CollapsibleSection sectionKey="orgAdmin.pats" title={strings.orgAdmin.pats}>
                {/* PAT lifetime joins the existing PAT list per the style
                    guide's regrouping notes, rather than staying under the
                    old "Advanced" catch-all. Still saved via the shared
                    Security-card button above, on this same "Security"
                    group/page, since it's one field on the same
                    OrgAdvancedSettings object. */}
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.orgAdmin.patMaxLifetime}
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={3650}
                    style={{ maxWidth: 160 }}
                    value={patMaxLifetimeDays}
                    onChange={(e) => {
                      advancedDirtyRef.current = true;
                      setPatMaxLifetimeDays(e.target.value);
                    }}
                  />
                  <span className="text-muted">{strings.orgAdmin.patMaxLifetimeHint(orgLabel)}</span>
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                    Saved with the Security settings above.
                  </span>
                </label>

                {orgPats.length === 0 ? (
                  <p className="text-muted">{strings.orgAdmin.patNone(orgLabel)}</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>{strings.orgAdmin.patUser}</th>
                        <th>{strings.orgAdmin.patName}</th>
                        <th>{strings.orgAdmin.patExpires}</th>
                        <th>{strings.orgAdmin.patLastUsed}</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {orgPats.map((p) => (
                        <tr key={p.id}>
                          <td>
                            {p.user_display_name} <span className="text-muted">({p.user_email})</span>
                          </td>
                          <td>
                            {p.name}
                            {p.other_org_count > 0 && (
                              <div className="text-muted">{strings.orgAdmin.patOtherOrgs(p.other_org_count, orgLabelPlural)}</div>
                            )}
                          </td>
                          <td>{new Date(p.expires_at).toLocaleDateString()}</td>
                          <td>{p.last_used_at ? new Date(p.last_used_at).toLocaleString() : strings.orgAdmin.never}</td>
                          <td>
                            <div className="row">
                              {p.other_org_count > 0 && (
                                <button className="btn" onClick={() => setPatToDescope(p.id)}>
                                  {strings.orgAdmin.patDescope}
                                </button>
                              )}
                              <button
                                className="btn btn-danger"
                                onClick={() => setPatToRevoke(p.id)}
                              >
                                {strings.orgAdmin.patRevoke}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {orgPats.length > 0 && (
                  <button className="btn btn-danger" onClick={() => setRevokeAllPatsOpen(true)} style={{ alignSelf: "flex-start" }}>
                    {strings.orgAdmin.patRevokeAll(orgLabel)}
                  </button>
                )}
                {patBulkResult && <div style={{ color: "var(--color-accent)" }}>{patBulkResult}</div>}
              </CollapsibleSection>
            )}
          </div>
        )}

        {activeGroup === "modules" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.modules" title={strings.orgAdmin.modulesTitle}>
              <p className="text-muted">{strings.orgAdmin.modulesDescription}</p>
              {modules.length === 0 ? (
                <p className="text-muted">{strings.orgAdmin.modulesEmpty}</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>{strings.orgAdmin.name}</th>
                      <th></th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {modules.map((m) => {
                      // Non-entitled (or not-yet-implemented) modules are
                      // shown greyed out with an explanatory note rather
                      // than hidden entirely (plan requirement — visibility
                      // helps future upsell); the toggle itself stays
                      // disabled either way.
                      const disabled = !m.entitled || !m.implemented;
                      const hint = !m.entitled
                        ? strings.orgAdmin.moduleNotEntitledHint
                        : !m.implemented
                          ? strings.orgAdmin.moduleNotImplementedHint
                          : null;
                      return (
                        <tr key={m.module_key} style={!m.entitled ? { opacity: 0.55 } : undefined}>
                          <td>
                            <div className="stack" style={{ gap: 0 }}>
                              <strong>{m.name}</strong>
                              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{m.description}</span>
                              {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
                            </div>
                          </td>
                          <td className="text-muted" style={{ fontSize: "0.8rem" }}>{m.version}</td>
                          <td>
                            <ToggleSwitch
                              checked={m.enabled}
                              disabled={disabled}
                              label={strings.orgAdmin.moduleToggleLabel(m.name)}
                              onChange={(next) => toggleModuleEnabled(m.module_key, next)}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </CollapsibleSection>
          </div>
        )}
      </ResourceMenu>

      {confirmRemoveUser && (
        <ConfirmDialog
          title={strings.orgAdmin.removeFromOrgConfirmTitle(confirmRemoveUser.display_name)}
          message={strings.orgAdmin.removeFromOrgConfirmMessage(confirmRemoveUser.display_name, orgLabel)}
          confirmLabel={strings.orgAdmin.removeFromOrgConfirmButton}
          onConfirm={() => removeOrgUser(confirmRemoveUser)}
          onCancel={() => setConfirmRemoveUser(null)}
        />
      )}
      {patToDescope && (
        <ConfirmDialog
          title={strings.orgAdmin.patDescopeTitle(orgLabel)}
          message={strings.orgAdmin.patDescopeConfirm(orgLabelPlural)}
          confirmLabel={strings.orgAdmin.patDescope}
          onConfirm={() => descopeOrgPat(patToDescope)}
          onCancel={() => setPatToDescope(null)}
        />
      )}
      {patToRevoke && (
        <ConfirmDialog
          title={strings.orgAdmin.patRevokeOneTitle}
          message={strings.orgAdmin.patRevokeOneConfirm}
          confirmLabel={strings.orgAdmin.patRevoke}
          onConfirm={() => revokeOrgPat(patToRevoke)}
          onCancel={() => setPatToRevoke(null)}
        />
      )}
      {revokeAllPatsOpen && (
        <ConfirmDialog
          title={strings.orgAdmin.patRevokeAllTitle(orgLabel)}
          message={strings.orgAdmin.patRevokeAllConfirm(orgLabelPlural)}
          confirmLabel={strings.orgAdmin.patRevokeAll(orgLabel)}
          onConfirm={revokeAllOrgPats}
          onCancel={() => setRevokeAllPatsOpen(false)}
        />
      )}
    </div>
  );
}
