import { useMutation } from "../hooks/useMutation";
import { usePlatformBranding } from "../hooks/usePlatformBranding";
import { ImportWarnings } from "../components/ImportWarnings";
import { UploadsDisabledPrompt } from "../components/UploadsDisabledPrompt";
import { uploadsDisabledInfo, type UploadsDisabledInfo } from "../utils/uploadsDisabled";
import { Download, Eye, KeyRound, Lock, Pencil, Plus, Send, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import type {
  CustomRoleDefinition,
  CustomRolePreset,
  EntityScope,
  ExternalUserPolicy,
  MergeConflict,
  ModuleRoleDefinition,
  OrgAdvancedSettings,
  OrgGroup,
  OrgModule,
  OrgModuleSubComponent,
  OrgMergePreviewResult,
  OrgMergeResult,
  OrgPendingInvite,
  OrgPersonalAccessToken,
  OrgProjectSummary,
  OrgRole,
  OrgSsoConfig,
  OrgUser,
  Organization,
  OutsideDomainUser,
  Permission,
  ProjectListItem,
  ProjectStatusDefinition,
  ScimTokenCreated,
  ScimTokenStatus,
  UserAccess,
} from "../api/types";
import type { ModuleAvailability, PrincipalRef, PrincipalUsage } from "../api/types";
import {
  collapseProjectRoles,
  FOOTER_POSITION_LABEL,
  fromModuleAvailability,
  MODULE_AVAILABILITY_LABEL,
  ORG_ROLE_LABEL,
  PENDING_INVITE_STATUS_LABEL,
  PROJECT_ROLE_LABEL,
  toModuleAvailability,
  type FooterPosition,
} from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { Tooltip } from "../components/Tooltip";
import { AddToGroupControl } from "../components/AddToGroupControl";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { SendPasswordResetDialog } from "../components/SendPasswordResetDialog";
import { GroupInUseDialog } from "../components/GroupInUseDialog";
import { DefinitionList } from "../components/DefinitionList";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { ImportedPeoplePanel } from "../components/ImportedPeoplePanel";
import { DirectoryTable } from "../components/DirectoryTable";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ImportConflictPanel } from "../components/ImportConflictPanel";
import { StageWorkflowsPanel } from "../components/StageWorkflowsPanel";
import { LinkTypesPanel } from "../components/LinkTypesPanel";
import { Modal } from "../components/Modal";
import { OrganisationDetailsPanel } from "../components/OrganisationDetailsPanel";
import { OrgUsageTable } from "../components/OrgUsageTable";
import { AddUserMenu } from "../components/AddUserMenu";
import { NewUserFields } from "../components/NewUserFields";
import { EMPTY_NEW_USER, type NewUserValues } from "../components/newUserValues";
import { ModuleAvailabilitySelect, ModuleSettingsList } from "../components/ModuleSettingsList";
import { MultiSelectDropdown } from "../components/MultiSelectDropdown";
import { BrandingImageField } from "../components/BrandingImageField";
import { InlineMessage } from "../components/InlineMessage";
import { PermissionPicker } from "../components/PermissionPicker";
import { AnnouncementsPanel } from "../components/AnnouncementsPanel";
import { PoliciesPanel } from "../components/PoliciesPanel";
import { NavLabelsPanel } from "../components/NavLabelsPanel";
import { OrgOverviewDefaultPanel } from "../components/overview/OrgOverviewDefaultPanel";
import { OrganizationCodePanel } from "../components/OrganizationCodePanel";
import { OrgLifecyclesPanel } from "../components/OrgLifecyclesPanel";
import { PersonalDataPolicyPanel } from "../components/PersonalDataPolicyPanel";
import { ProjectCodePolicyPanel } from "../components/ProjectCodePolicyPanel";
import { OrgExternalSystemsPanel } from "../components/ExternalSystemsPanels";
import { RecordCodePrefixPanel } from "../components/RecordCodePrefixPanel";
import { RequirementAliasSettingsPanel } from "../components/RequirementAliasSettingsPanel";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { SidePanel } from "../components/SidePanel";
import { cycleSort, type SortState } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { useFederatedModules } from "../hooks/useFederatedModules";
import { buildAdminMenuEntries, resolveAdminSection } from "../modules/adminMenu";
import { installedModules } from "../modules/registry";
import { loadOrgSwitcherOptions } from "../utils/entitySwitcherLoaders";
import { downloadBlob } from "../utils/download";
import { labelOptions } from "../utils/labelOptions";
import { defaultResolutions } from "../utils/mergeConflicts";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { OrgUserNameCell } from "../components/OrgUserNameCell";
import { ServiceBadge } from "../components/ServiceBadge";
import { useServiceUserDialogs } from "../hooks/useServiceUserDialogs";
import { CheckboxField, ColorField, FileField, TextField, ToggleField } from "../components/FormFields";
import { LogoBandField } from "../components/LogoBandField";
import { FieldHelp } from "../components/FieldHelp";
import { ReportColourSchemeEditor } from "../components/ReportColourSchemeEditor";
import { DEFAULT_COLOUR_CONTEXT, type ColourEntry } from "../utils/reportColours";
import { FormActions } from "../components/FormActions";
import { FormGrid, FormGridFull } from "../components/FormGrid";
import { InlineSelect, LabeledSelect } from "../components/LabeledSelect";
import { RecordFieldGroup } from "../components/RecordDetailParts";

/**
 * The fixed `ResourceMenu` groups. Each key is the route segment under `/orgs/:orgId/admin/:group?` (App.tsx), so a selection is a
 * real navigation (back/forward and bookmarks work); an unrecognised or absent `:group` falls back to "overview". "oauth-sso" groups
 * SSO/OIDC and SCIM (identity-provisioning integrations; docs/decisions.md), "email" holds SMTP and the test email, "security" holds
 * 2FA, self-signup, external-user policy and Personal Access Tokens. Every installed and enabled module's `orgAdminSections`
 * (`modules/types.ts`) contributes its own groups dynamically (built into `orgAdminGroups`), so this type names only the ten core groups.
 */
const CORE_ORG_ADMIN_GROUP_KEYS = [
  "overview",
  "details",
  "users",
  "groups",
  "projects",
  "workflow",
  "lifecycles",
  "branding-defaults",
  "oauth-sso",
  "email",
  "security",
  "modules",
  "messages",
  "policies",
  // Fine-Grained Access Control (core): custom-role definition (ORG_ADMIN-only) and the broader `grant_roles` assignment surface, "Role Management".
  "role-management",
] as const;
type CoreOrgAdminGroupKey = (typeof CORE_ORG_ADMIN_GROUP_KEYS)[number];

/**
 * The group key is a `string` because a module-contributed `orgAdminSections` entry's `key` is not known at compile time. Tradeoff:
 * TypeScript no longer flags a typo such as `activeGroup === "userz"` in the ten core render blocks, because the type overlaps every
 * string. Accepted over hardcoding each module's group keys into this file. `CoreOrgAdminGroupKey` stays a closed literal type, so
 * `CORE_ORG_ADMIN_GROUP_KEYS` and anything typed with it keeps typo protection.
 */
type OrgAdminGroupKey = CoreOrgAdminGroupKey | string;

/** The three groups of advanced settings, each with its own Save (see `saveAdvanced`). */
type AdvancedGroup = "email" | "security" | "pats";

/** One row of the Org Users `DirectoryTable`: a real user or a pending org-only invite, merged client-side (the `kind`-discriminated
 * union `ProjectMembersTable` also uses). */
type UsersRow = { kind: "user"; user: OrgUser } | { kind: "invited"; invite: OrgPendingInvite };

/**
 * Organisation administration: users (C-U-01), groups (C-U-08), shared resource files (C-M-03), the logo (U-C-02), the default template
 * project (C-E-04), definable project statuses and definable bidirectional requirement link types (forward and reverse display name,
 * since a link reads differently from each side; `docs/decisions.md`). Both share custom fields' rename/reorder/delete-with-reassignment
 * contract: deleting one in use returns 409 with a count, and a reassignment picker moves references before the delete retries.
 */
export function OrgAdminPage() {
  const run = useMutation();
  const strings = useStrings();
  const { orgId, group: groupParam, section: sectionParam } = useParams<{ orgId: string; group?: string; section?: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const platformBranding = usePlatformBranding();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
  const [org, setOrg] = useState<Organization | null>(null);
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
  // "Remove from {org}" (Users table Actions column): the user pending confirmation in the `ConfirmDialog`, or null.
  const [confirmRemoveUser, setConfirmRemoveUser] = useState<OrgUser | null>(null);
  const [resetLinkUser, setResetLinkUser] = useState<OrgUser | null>(null);
  const [userAccess, setUserAccess] = useState<UserAccess | null>(null);
  const [userAccessError, setUserAccessError] = useState<string | null>(null);
  // "View access" panel: each project row shows `collapseProjectRoles()`'s summary; this set of project ids tracks the rows expanded to
  // the full role list. Reset when a new user's access is opened so expansion never leaks between users.
  const [expandedAccessProjectIds, setExpandedAccessProjectIds] = useState<Set<string>>(new Set());
  const [groups, setGroups] = useState<OrgGroup[]>([]);
  const [groupsTotal, setGroupsTotal] = useState(0);
  const [groupSearch, setGroupSearch] = useState("");
  // Every organisation group by id/name, unpaginated and ignoring `groupSearch`: nested-group name resolution and the "add nested group"
  // dropdown must offer every group whatever the paginated `groups` list shows.
  const [allGroups, setAllGroups] = useState<OrgGroup[]>([]);
  // Org Groups `DirectoryTable` with a per-row `SidePanel`, the shape Project Groups use. `list_org_groups` pages via `limit`/`offset`, so Name
  // sort is a backend `order` refetch, as in Org Users, not a client sort of the loaded page (style guide "Pattern: sortable column header");
  // Members has no natural order and stays unsorted.
  type OrgGroupSortKey = "name";
  const [groupSort, setGroupSort] = useState<SortState<OrgGroupSortKey> | null>(null);
  const [openOrgGroupId, setOpenOrgGroupId] = useState<string | null>(null);
  // Organisation group pending deletion in its Tier 1 `ConfirmDialog`, or null.
  const [deletingOrgGroupId, setDeletingOrgGroupId] = useState<string | null>(null);
  const [inUseOrgGroup, setInUseOrgGroup] = useState<{ id: string; usage: PrincipalUsage } | null>(null);
  // Per-group SSO-sync toggle: `undefined` means untouched this session, so the checkbox derives from `idp_synced_group_name != null`.
  // Unchecking clears both synced fields at once through the `PATCH` the "Save sync settings" button uses (`toggleGroupSync`).
  const [syncEnabledEdits, setSyncEnabledEdits] = useState<Record<string, boolean>>({});
    const [templateProjects, setTemplateProjects] = useState<ProjectListItem[]>([]);
  // Fine-Grained Access Control (core): the organisation's projects the caller can see (`GET /api/v1/projects`, already fetched for
  // `templateProjects`), the Role Management project-scoped grant picker's fallback when `orgProjects` (ORG_ADMIN-only) is unavailable, so a
  // `grant_roles` holder who is not an ORG_ADMIN can still grant a project-scoped custom role.
  const [thisOrgVisibleProjects, setThisOrgVisibleProjects] = useState<ProjectListItem[]>([]);

  // --- Project statuses (C-G-XX) ---------------------------------------
  const [projectStatuses, setProjectStatuses] = useState<ProjectStatusDefinition[]>([]);

  // --- Requirement link types (C-G-09) ---------------------------------

  const [newUser, setNewUser] = useState<NewUserValues>(EMPTY_NEW_USER);
  // "New user" opens in a `Modal` (style guide "Pattern: modal dialog for entity create/rename").
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
  // The organisation's enable/disable choice among modules it is entitled to. Fetched in the same try/catch-403 block as `advanced` above
  // (non-admins do not see the section); `[]` until it resolves or when no module is registered.
  const [modules, setModules] = useState<OrgModule[]>([]);
  // Each module's declared sub-components keyed by `module_key`, fetched with `modules`. `GET .../subcomponents` returns `[]` for a module
  // with none, so it is called for every module.
  const [orgModuleSubComponents, setOrgModuleSubComponents] = useState<Record<string, OrgModuleSubComponent[]>>({});
  // Module Federation (Tier C): a module effectively enabled for this organisation whose manifest is `"federated"` has no build-time
  // `installedModules` entry, so its `TierAModuleDefinition` is loaded at runtime before `moduleAdminSections` (below) looks for it. Called
  // here because a hook cannot follow the early-return guards (`if (!org) return <Spinner />`); only effectively enabled modules load, so a
  // disabled Tier C module's remote code is never fetched (see `useFederatedModules`, `modules/federatedLoader.ts`).
  useFederatedModules(modules.filter((m) => m.enabled));
  // Org-scoped module-contributed role definitions available to grant here, offered in the Users table's Roles `MultiSelectDropdown` beside
  // the three `OrgRole` options. Fetched with `modules`; `[]` until it resolves or when no module has roles.
  const [availableOrgModuleRoles, setAvailableOrgModuleRoles] = useState<ModuleRoleDefinition[]>([]);
  // Fine-Grained Access Control (core): Role Management state. `permissions`/`customRoles` are fetched in the main `reload()` bundle:
  // `GET .../permissions` and `GET .../custom-roles` are open to any organisation role (`_VIEW_ROLES`), not ORG_ADMIN-gated like role definition.
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [customRoles, setCustomRoles] = useState<CustomRoleDefinition[]>([]);
  // Fine-Grained Access Control (core): every registered module-owned entity scope (e.g. compliance's `"standard"`), from the non-admin-gated
  // `GET /orgs/{id}/entity-scopes`; it feeds the scope dropdown and entity picker generically.
  const [entityScopes, setEntityScopes] = useState<EntityScope[]>([]);
  const [customRoleModalOpen, setCustomRoleModalOpen] = useState(false);
  const [customRolePresets, setCustomRolePresets] = useState<CustomRolePreset[]>([]);
  const [editingCustomRoleId, setEditingCustomRoleId] = useState<string | null>(null);
  const [customRoleFormName, setCustomRoleFormName] = useState("");
  const [customRoleFormDescription, setCustomRoleFormDescription] = useState("");
  const [customRoleFormScope, setCustomRoleFormScope] = useState<string>("org");
  const [customRoleFormPermissions, setCustomRoleFormPermissions] = useState<string[]>([]);
  const [customRoleFormError, setCustomRoleFormError] = useState<string | null>(null);
  const [customRoleFormSaving, setCustomRoleFormSaving] = useState(false);
  const [confirmDeleteCustomRole, setConfirmDeleteCustomRole] = useState<CustomRoleDefinition | null>(null);
  // The {project} each project-scoped custom role's grant/revoke pickers target, keyed by `CustomRoleDefinition.id` (an org-scoped role needs none,
  // its grants carry no project_id).
  const [customRoleGrantProjectId, setCustomRoleGrantProjectId] = useState<Record<string, string>>({});
  // The entity-scope counterpart: the entity (e.g. standard) each entity-scoped role's pickers target, keyed by `CustomRoleDefinition.id`.
  const [customRoleGrantEntityId, setCustomRoleGrantEntityId] = useState<Record<string, string>>({});
  // Users table filters: `FilterCheckbox`es in the shared `FilterPanel`, one boolean each (the backend's `stale_since_days`/`has_2fa`/
  // `has_project_access` params are independent, so "stale AND no 2FA" is expressible), plus `roleFilter` for the `org_role` param.
  const [userFilterStale, setUserFilterStale] = useState(false);
  const [userFilterNo2fa, setUserFilterNo2fa] = useState(false);
  const [userFilterNoAccess, setUserFilterNoAccess] = useState(false);
  const [userFilterService, setUserFilterService] = useState(false);
  const [userFilterArchived, setUserFilterArchived] = useState(false);
  const [userRoleFilter, setUserRoleFilter] = useState<OrgRole | "">("");
  // Pending (unaccepted) org-only invites, merged into the Users table as `kind: "invited"` rows: fetched unpaginated (never many) and
  // always rendered ahead of the user rows whatever their sort or page.
  const [orgInvites, setOrgInvites] = useState<OrgPendingInvite[]>([]);
  const [showInvitedUsers, setShowInvitedUsers] = useState(true);
  const [resendingOrgInviteId, setResendingOrgInviteId] = useState<string | null>(null);
  const [inviteUserModalOpen, setInviteUserModalOpen] = useState(false);
  const [inviteUserEmail, setInviteUserEmail] = useState("");
  // Column-header sorting is backend `sort`/`order`: the table is backend-paginated (`USERS_PAGE_SIZE`/`LoadMoreButton`).
  type OrgUserSortKey = "display_name" | "email" | "last_login_at";
  const [userSort, setUserSort] = useState<SortState<OrgUserSortKey> | null>(null);
  const [patMaxLifetimeDays, setPatMaxLifetimeDays] = useState("");
  const [require2fa, setRequire2fa] = useState(false);
  const [allowSelfSignup, setAllowSelfSignup] = useState(false);
  const [autoAcceptEmailDomain, setAutoAcceptEmailDomain] = useState("");
  const [externalUserPolicy, setExternalUserPolicy] = useState<ExternalUserPolicy>("disabled");
  const [allowRelaxedChildProjectCreation, setAllowRelaxedChildProjectCreation] = useState(true);
  // Org-wide force of `Project.require_change_request_for_approved_links`, minus a per-project `exempt_from_org_link_lock` opt-out
  // (see `Organization`'s field docstring).
  const [forceRequireCrForLinks, setForceRequireCrForLinks] = useState(false);
  // AI approval via MCP (docs/decisions.md): the organisation half of the two-level opt-in gate; enabling it requires acknowledging the
  // accountability trade-off (`aiApprovalsAckPending`).
  const [allowAiApprovals, setAllowAiApprovals] = useState(false);
  const [allowImportedApprovalState, setAllowImportedApprovalState] = useState(true);
  const [aiApprovalsAckPending, setAiApprovalsAckPending] = useState(false);
  const [aiApprovalsAckChecked, setAiApprovalsAckChecked] = useState(false);
  // Guards the advanced-settings fields above against `reload()`, which runs after many unrelated mutations and is not awaited: a slow
  // `reload()` resolving after the user's edit would reset it to the last-saved value before Save (a race seen in CI, see
  // org-security-controls.spec.ts and docs/decisions.md). Set on every field's onChange, cleared once `saveAdvanced` succeeds.
  const advancedDirtyRef = useRef<Record<AdvancedGroup, boolean>>({ email: false, security: false, pats: false });
  const [outsideDomainUsers, setOutsideDomainUsers] = useState<OutsideDomainUser[] | null>(null);
  const [outsideDomainError, setOutsideDomainError] = useState<string | null>(null);
  const [orgPats, setOrgPats] = useState<OrgPersonalAccessToken[]>([]);
  const [patBulkResult, setPatBulkResult] = useState<string | null>(null);
  // Tier 1 `ConfirmDialog` state for the three PAT actions below.
  const [patToDescope, setPatToDescope] = useState<string | null>(null);
  const [revokeAllPatsOpen, setRevokeAllPatsOpen] = useState(false);
  const [patToRevoke, setPatToRevoke] = useState<string | null>(null);
  const [orgProjects, setOrgProjects] = useState<OrgProjectSummary[] | null>(null);
  // The full directory lists every template in the organisation, including ones the administrator holds no role in.
  const defaultTemplateOptions: { id: string; name: string }[] = orgProjects
    ? orgProjects.filter((p) => p.is_template && !p.is_archived)
    : templateProjects;
  const [ssoConfig, setSsoConfig] = useState<OrgSsoConfig | null>(null);
  const [slugInput, setSlugInput] = useState("");
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ssoOnly, setSsoOnly] = useState(false);
  const [oidcIssuerUrl, setOidcIssuerUrl] = useState("");
  const [oidcClientId, setOidcClientId] = useState("");
  const [oidcClientSecret, setOidcClientSecret] = useState("");
  const [oidcRequiredGroup, setOidcRequiredGroup] = useState("");
  const [oidcAllowAccountCreation, setOidcAllowAccountCreation] = useState(true);

  const [scimStatus, setScimStatus] = useState<ScimTokenStatus | null>(null);
  const [scimGeneratedToken, setScimGeneratedToken] = useState<string | null>(null);
  // The two actions that replace or remove the live provisioning credential ask first (Tier 1).
  const [scimConfirm, setScimConfirm] = useState<"regenerate" | "revoke" | null>(null);

  const [useOwnAccentColor, setUseOwnAccentColor] = useState(false);
  const [accentColorInput, setAccentColorInput] = useState("#475569");
  const [logoBandInput, setLogoBandInput] = useState("");
  const [logoBandTextInput, setLogoBandTextInput] = useState("");
  const [footerPositionInput, setFooterPositionInput] = useState<FooterPosition | "">("");
  // The report accent colour follows the UI accent until the person gives reports their own (`null` on the server).
  const [useOwnReportAccent, setUseOwnReportAccent] = useState(false);
  const [reportAccentInput, setReportAccentInput] = useState("#475569");
  const [reportColourScheme, setReportColourScheme] = useState<ColourEntry[]>([]);
  const [reportIncludeLogo, setReportIncludeLogo] = useState(true);
  const [headerTitleInput, setHeaderTitleInput] = useState("");
  const [brandingError, setBrandingError] = useState<string | null>(null);

  const USERS_PAGE_SIZE = 30;
  const GROUPS_PAGE_SIZE = 20;

  interface UserFilters {
    stale: boolean;
    no2fa: boolean;
    noAccess: boolean;
    service: boolean;
    archived: boolean;
    role: OrgRole | "";
  }

  function currentUserFilters(): UserFilters {
    return { stale: userFilterStale, no2fa: userFilterNo2fa, noAccess: userFilterNoAccess, service: userFilterService, archived: userFilterArchived, role: userRoleFilter };
  }

  // Only the newest users/groups load applies its response: filter and search changes fire overlapping loads.
  const beginUsersLoad = useRequestSequence();
  const beginGroupsLoad = useRequestSequence();

  async function loadUsers(
    filters: UserFilters, search: string, offset: number, append: boolean, sort: typeof userSort = userSort
  ) {
    if (!orgId) return;
    const isLatest = beginUsersLoad();
    function query(includeFilter: boolean) {
      const params = new URLSearchParams({ limit: String(USERS_PAGE_SIZE), offset: String(offset) });
      if (includeFilter) {
        if (filters.stale) params.set("stale_since_days", "180");
        if (filters.no2fa) params.set("has_2fa", "false");
        if (filters.noAccess) params.set("has_project_access", "false");
        if (filters.service) params.set("is_service_account", "true");
        if (filters.archived) params.set("include_archived", "true");
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
      if (!isLatest()) return;
      setUsers((prev) => (append ? [...prev, ...page.items] : page.items));
      setUsersTotal(page.total);
    } catch (err) {
      // Non-admins get 403 on filtered queries; fall back to the plain list (search and pagination stay available).
      if (err instanceof ApiError && err.status === 403) {
        const page = await api.getPage<OrgUser>(`/api/v1/orgs/${orgId}/users?${query(false)}`);
        if (!isLatest()) return;
        setUsers((prev) => (append ? [...prev, ...page.items] : page.items));
        setUsersTotal(page.total);
      } else {
        throw err;
      }
    }
  }

  /** Pending org-only invites, gated at organisation-admin/server-admin tier server-side (as `create_org_user`); a plain member sees none,
   * every other 403 still surfaces. */
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
    const isLatest = beginGroupsLoad();
    const params = new URLSearchParams({ limit: String(GROUPS_PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (sort) params.set("order", sort.direction);
    const page = await api.getPage<OrgGroup>(`/api/v1/orgs/${orgId}/groups?${params.toString()}`);
    if (!isLatest()) return;
    setGroups((prev) => (append ? [...prev, ...page.items] : page.items));
    setGroupsTotal(page.total);
  }

  async function reload() {
    if (!orgId) return;
    // Reaching this page does not imply membership of this organisation (a server administrator sees every organisation, and a stale link can
    // point at one whose membership changed). Every call below needs at least `member`, so the bundle 403s as a whole in that case; it is
    // caught so a message shows instead of a spinner forever (the loading gate is `if (!org) return <Spinner />`).
    let o: Organization, allG: OrgGroup[], projects: ProjectListItem[];
    let statuses: ProjectStatusDefinition[];
    let permissionsList: Permission[], customRoleList: CustomRoleDefinition[], entityScopeList: EntityScope[];
    try {
      [o, allG, projects, statuses, permissionsList, customRoleList, entityScopeList] =
        await Promise.all([
        api.get<Organization>(`/api/v1/orgs/${orgId}`),
        // Unpaginated: nested-group name resolution and the "add nested group" dropdown need every group (see `allGroups`).
        api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`),
        // Scoped to this organisation server-side: the unscoped list spanned every organisation the caller belongs to.
        api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&include_templates=true&organization_id=${orgId}`),
        api.get<ProjectStatusDefinition[]>(`/api/v1/orgs/${orgId}/project-statuses`),
        // Open to any organisation role (`_VIEW_ROLES`), so it belongs in this bundle, not the ORG_ADMIN-gated catch-403 block below (a
        // `grant_roles` holder who is not an ORG_ADMIN needs to see what is grantable).
        api.get<Permission[]>(`/api/v1/orgs/${orgId}/permissions`),
        api.get<CustomRoleDefinition[]>(`/api/v1/orgs/${orgId}/custom-roles`),
        // Fine-Grained Access Control (core): same tier as
        // `permissions`/`custom-roles` above.
        api.get<EntityScope[]>(`/api/v1/orgs/${orgId}/entity-scopes`),
      ]);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : strings.common.error);
      // `GET /orgs/{id}` has a server-administrator bypass (unlike the calls above, which is why the bundle fails); fetched best-effort so
      // the degraded view can show which organisation this is.
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
    setUseOwnAccentColor(o.accent_color_hex != null);
    setAccentColorInput(o.accent_color_hex ?? "#475569");
    setLogoBandInput(o.logo_band_color_hex ?? "");
    setLogoBandTextInput(o.logo_band_text_color_hex ?? "");
    setFooterPositionInput(o.footer_position ?? "");
    setUseOwnReportAccent(o.report_accent_color_hex != null);
    setReportAccentInput(o.report_accent_color_hex ?? o.accent_color_hex ?? "#475569");
    setReportColourScheme(o.report_colour_scheme ?? []);
    setReportIncludeLogo(o.report_include_logo);
    setHeaderTitleInput(o.header_title ?? "");
    setAllGroups(allG);
    setTemplateProjects(projects.filter((p) => p.is_template && p.organization_id === orgId));
    setThisOrgVisibleProjects(projects.filter((p) => p.organization_id === orgId));
    setProjectStatuses(statuses);
    setPermissions(permissionsList);
    setCustomRoles(customRoleList);
    setEntityScopes(entityScopeList);
    await Promise.all([loadUsers(currentUserFilters(), userSearch, 0, false), loadGroups(groupSearch, 0, false), loadOrgInvites()]);

    try {
      const a = await api.get<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`);
      setAdvanced(a);
      // Skip repopulating the editable fields while an unsaved edit is pending; this fetch may predate the edit (see `advancedDirtyRef`).
      const dirty = advancedDirtyRef.current;
      if (!dirty.email) {
        setSmtpHost(a.smtp_host ?? "");
        setSmtpPort(a.smtp_port ? String(a.smtp_port) : "");
        setSmtpUsername(a.smtp_username ?? "");
        setSmtpUseTls(a.smtp_use_tls);
      }
      if (!dirty.pats) setPatMaxLifetimeDays(a.pat_max_lifetime_days ? String(a.pat_max_lifetime_days) : "");
      if (!dirty.security) {
        setRequire2fa(a.require_2fa);
        setAllowSelfSignup(a.allow_self_signup);
        setAutoAcceptEmailDomain(a.auto_accept_email_domain ?? "");
        setExternalUserPolicy(a.external_user_policy);
        setAllowRelaxedChildProjectCreation(a.allow_relaxed_child_project_creation);
        setForceRequireCrForLinks(a.force_require_change_request_for_approved_links);
        setAllowAiApprovals(a.allow_ai_approvals);
        setAllowImportedApprovalState(a.allow_imported_approval_state ?? true);
      }
      setOrgPats(await api.get<OrgPersonalAccessToken[]>(`/api/v1/orgs/${orgId}/pats`));
      setOrgProjects(await api.get<OrgProjectSummary[]>(`/api/v1/orgs/${orgId}/projects`));
      const loadedModules = await api.get<OrgModule[]>(`/api/v1/orgs/${orgId}/modules`);
      setModules(loadedModules);
      const subComponentEntries = await Promise.all(
        loadedModules.map(async (m) => [
          m.module_key,
          await api.get<OrgModuleSubComponent[]>(`/api/v1/orgs/${orgId}/modules/${m.module_key}/subcomponents`),
        ] as const),
      );
      setOrgModuleSubComponents(Object.fromEntries(subComponentEntries));
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
      setOidcAllowAccountCreation(sso.oidc_allow_account_creation ?? true);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      setScimStatus(await api.get<ScimTokenStatus>(`/api/v1/orgs/${orgId}/scim-token`));
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }
  }

  // Service users are rows of the one Users list; their create form and detail dialog open from it.
  const serviceUserDialogs = useServiceUserDialogs({
    organizationId: orgId ?? "",
    onChanged: () => void loadUsers(currentUserFilters(), userSearch, 0, false),
  });

  /** Applies a partial filter change (one `FilterCheckbox`/`FilterField`) on top of the other filters' current values, then reloads from offset 0. */
  function applyUserFilters(next: Partial<UserFilters>) {
    const merged: UserFilters = { ...currentUserFilters(), ...next };
    setUserFilterStale(merged.stale);
    setUserFilterNo2fa(merged.no2fa);
    setUserFilterNoAccess(merged.noAccess);
    setUserFilterService(merged.service);
    setUserFilterArchived(merged.archived);
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

  /** Backend-sorted refetch, like `applyUserSort`: `list_org_groups` pages via `limit`/`offset`, so sorting only the loaded page would misstate
   * the full-list order (style guide "Pattern: sortable column header"). */
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

  /** Toggles one project row between `collapseProjectRoles()`'s summary and the full role set on the "View access" panel (per row, local,
   * reset on each new user; see `expandedAccessProjectIds`). */
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

  /**
   * Saves one group of the organisation's advanced settings. The endpoint leaves every field a request does not
   * send as it is, so each Save sends only its own group's fields and an unsaved edit in another group is neither
   * saved nor overwritten.
   *
   * @param group `email` (SMTP), `security` (sign-in and project policies) or `pats` (token lifetime).
   */
  async function saveAdvanced(group: AdvancedGroup) {
    if (!orgId) return;
    setAdvancedError(null);
    const fields: Record<AdvancedGroup, Record<string, unknown>> = {
      email: {
        smtp_host: smtpHost || null,
        smtp_port: smtpPort ? Number(smtpPort) : null,
        smtp_username: smtpUsername || null,
        smtp_password: smtpPassword || undefined,
        smtp_use_tls: smtpUseTls,
      },
      pats: { pat_max_lifetime_days: patMaxLifetimeDays ? Number(patMaxLifetimeDays) : null },
      security: {
        require_2fa: require2fa,
        allow_self_signup: allowSelfSignup,
        auto_accept_email_domain: autoAcceptEmailDomain || null,
        external_user_policy: externalUserPolicy,
        allow_relaxed_child_project_creation: allowRelaxedChildProjectCreation,
        force_require_change_request_for_approved_links: forceRequireCrForLinks,
        allow_ai_approvals: allowAiApprovals,
        allow_imported_approval_state: allowImportedApprovalState,
      },
    };
    try {
      const saved = await api.put<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`, fields[group]);
      setAdvanced(saved);
      if (group === "email") setSmtpPassword("");
      // The group's fields now match the server, so a later reload() may repopulate them.
      advancedDirtyRef.current[group] = false;
      showToast(strings.orgAdmin.advancedSaved);
    } catch (err) {
      setAdvancedError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function revokeOrgPat(patId: string) {
    if (!orgId) return;
    setPatToRevoke(null);
    if (!(await run(() => api.post(`/api/v1/orgs/${orgId}/pats/${patId}/revoke`), "revoke", "personal access token"))) return;
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function descopeOrgPat(patId: string) {
    if (!orgId) return;
    setPatToDescope(null);
    if (!(await run(() => api.post(`/api/v1/orgs/${orgId}/pats/${patId}/descope`), {
      success: strings.orgAdmin.patRemoved(orgLabel), failure: strings.orgAdmin.patRemoveFailed(orgLabel),
    }))) return;
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function revokeAllOrgPats() {
    if (!orgId) return;
    setRevokeAllPatsOpen(false);
    let revokedCount = 0;
    const done = await run(async () => {
      revokedCount = (await api.post<{ revoked_count: number }>(`/api/v1/orgs/${orgId}/pats/revoke-all`)).revoked_count;
    }, { failure: strings.orgAdmin.patRevokeAllFailed });
    if (!done) return;
    setOrgPats([]);
    setPatBulkResult(strings.orgAdmin.patRevokeAllResult.replace("{n}", String(revokedCount)));
  }

  async function setDefaultTemplate(projectId: string) {
    if (!(await run(() => api.put(`/api/v1/orgs/${orgId}/default-template`, { project_id: projectId || null }), "set", "default template"))) return;
    reload();
  }

  async function addProjectStatus(name: string) {
    if (!orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/project-statuses`, { name });
    showToast(strings.mutation.success("{project} status", strings.mutation.past.add));
    reload();
  }

  async function moveProjectStatus(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/orgs/${orgId}/project-statuses/${id}/move`, { direction });
    reload();
  }

  async function renameProjectStatus(id: string, name: string) {
    await api.patch(`/api/v1/orgs/${orgId}/project-statuses/${id}`, { name });
    showToast(strings.mutation.success("{project} status", strings.mutation.past.rename));
    reload();
  }

  /** Plain delete first (no `reassign_to_id`, §4.0's server contract): 204 is done, 409 means the status is in use and `DefinitionList` opens
   * the reassignment picker with the server's count message. */
  async function deleteProjectStatus(id: string, reassignToId?: string) {
    await api.delete(`/api/v1/orgs/${orgId}/project-statuses/${id}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`);
    showToast(strings.mutation.success("{project} status", strings.mutation.past.delete));
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  /** Degraded-view action for a disabled organisation (a server administrator may already be a member of one since disabled): re-enables it,
   * then reloads. */
  async function enableThisOrg() {
    if (!orgId) return;
    setEnableError(null);
    setEnabling(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/enable`);
      showToast(strings.mutation.success(orgLabel, strings.mutation.past.enable));
      await reload();
    } catch (err) {
      setEnableError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setEnabling(false);
    }
  }

  /** Degraded-view action (self-hosting): a server administrator with no role in this organisation grants themselves org_admin, then reloads. */
  async function joinAsAdmin() {
    if (!orgId) return;
    setJoinError(null);
    setJoining(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/join-as-admin`);
      showToast(strings.mutation.success("administrator access", strings.mutation.past.grant));
      await reload();
    } catch (err) {
      setJoinError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setJoining(false);
    }
  }

  /** Degraded-view action (hosting company): a server administrator creates an org_admin user in this organisation for someone else without
   * becoming a member, the carve-out `create_org_user` grants (whether or not the organisation has users). */
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
        email: newUser.email, display_name: newUser.displayName, password: newUser.password, role: newUser.role,
      });
      setNewUser(EMPTY_NEW_USER);
      setNewUserModalOpen(false);
      showToast(strings.orgAdmin.userCreated);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** "Invite user", the organisation-level counterpart to `createUser`: emails a sign-up link instead of setting a password. Refreshes only
   * `orgInvites`, since nothing else changes. */
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

  // Updates only the affected row's `roles` in local state instead of the page-wide `reload()`, which re-fetches ~10 endpoints (including the users
  // list from offset 0): it would drop users paged in past the first 30, and two close toggles would race two reload bundles, where one transient
  // failure replaces the page with a load error (docs/decisions.md). One grant/revoke changes only this row's role set.
  async function grantOrgRole(u: OrgUser, role: OrgRole) {
    try {
      await api.post(`/api/v1/orgs/${orgId}/users/${u.user_id}/roles`, { user_id: u.user_id, role });
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

  // The same single-row local patch as `grantOrgRole`/`revokeOrgRole`: a grant/revoke changes only this row's module-role set.
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

  // --- Fine-Grained Access Control (core): Role Management --------------
  // Custom-role definition (ORG_ADMIN-only, never delegable) and assignment (delegable via grant_roles) actions. The backend exposes no
  // "who holds this role" listing (a grant roster is a privilege-reconnaissance disclosure), so granting or revoking a custom role by
  // picking a person from a directory search is fire-and-forget, with no checked state to reflect; the Users table's per-row checkbox reads
  // `OrgUser.custom_roles` and is covered separately below.

  function openCreateCustomRoleModal() {
    setEditingCustomRoleId(null);
    setCustomRoleFormName("");
    setCustomRoleFormDescription("");
    setCustomRoleFormScope("org");
    setCustomRoleFormPermissions([]);
    setCustomRoleFormError(null);
    setCustomRoleModalOpen(true);
    // Presets are the same for every organisation and only an org admin may read them.
    if (customRolePresets.length === 0 && orgId) {
      api.get<CustomRolePreset[]>(`/api/v1/orgs/${orgId}/custom-role-presets`).then(setCustomRolePresets, () => {});
    }
  }

  function applyCustomRolePreset(key: string) {
    const preset = customRolePresets.find((p) => p.key === key);
    if (!preset) return;
    setCustomRoleFormName(preset.name);
    setCustomRoleFormDescription(preset.description);
    setCustomRoleFormScope(preset.scope);
    setCustomRoleFormPermissions(preset.permissions);
  }

  function openEditCustomRoleModal(role: CustomRoleDefinition) {
    setEditingCustomRoleId(role.id);
    setCustomRoleFormName(role.name);
    setCustomRoleFormDescription(role.description);
    setCustomRoleFormScope(role.scope);
    setCustomRoleFormPermissions(role.permissions);
    setCustomRoleFormError(null);
    setCustomRoleModalOpen(true);
  }

  function closeCustomRoleModal() {
    setCustomRoleModalOpen(false);
    setCustomRoleFormError(null);
  }

  async function saveCustomRole() {
    if (!orgId) return;
    setCustomRoleFormSaving(true);
    setCustomRoleFormError(null);
    const payload = {
      name: customRoleFormName,
      description: customRoleFormDescription,
      scope: customRoleFormScope,
      permissions: customRoleFormPermissions,
    };
    try {
      if (editingCustomRoleId) {
        const updated = await api.patch<CustomRoleDefinition>(
          `/api/v1/orgs/${orgId}/custom-roles/${editingCustomRoleId}`, payload
        );
        setCustomRoles((prev) => prev.map((r) => (r.id === updated.id ? updated : r)).sort((a, b) => a.name.localeCompare(b.name)));
        showToast(strings.orgAdmin.customRoleUpdated);
      } else {
        const created = await api.post<CustomRoleDefinition>(`/api/v1/orgs/${orgId}/custom-roles`, payload);
        setCustomRoles((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
        showToast(strings.orgAdmin.customRoleCreated);
      }
      setCustomRoleModalOpen(false);
    } catch (err) {
      setCustomRoleFormError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setCustomRoleFormSaving(false);
    }
  }

  async function deleteCustomRole(role: CustomRoleDefinition) {
    setConfirmDeleteCustomRole(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/custom-roles/${role.id}`);
      setCustomRoles((prev) => prev.filter((r) => r.id !== role.id));
      // A deleted role's grants cascade server-side; drop local Users-table state that references it so no stale checked row lingers.
      setUsers((prev) =>
        prev.map((u) => ({ ...u, custom_roles: u.custom_roles.filter((g) => g.custom_role_id !== role.id) }))
      );
      showToast(strings.orgAdmin.customRoleDeleted);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Users table role column: org-scoped (`scope === "org"`) custom roles only, matching `OrgUser.custom_roles`. A project-scoped role has no single
   * project on this table, so it is granted and revoked from the dedicated picker below. */
  async function grantOrgScopedCustomRoleToUser(u: OrgUser, role: CustomRoleDefinition) {
    try {
      await api.post(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/users/${u.user_id}`, {});
      setUsers((prev) =>
        prev.map((x) =>
          x.user_id === u.user_id
            ? { ...x, custom_roles: [...x.custom_roles, { custom_role_id: role.id, name: role.name }] }
            : x
        )
      );
      showToast(strings.orgAdmin.roleGranted);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeOrgScopedCustomRoleFromUser(u: OrgUser, role: CustomRoleDefinition) {
    try {
      await api.delete(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/users/${u.user_id}`);
      setUsers((prev) =>
        prev.map((x) =>
          x.user_id === u.user_id
            ? { ...x, custom_roles: x.custom_roles.filter((g) => g.custom_role_id !== role.id) }
            : x
        )
      );
      showToast(strings.orgAdmin.roleRevoked);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Whether `scope` is a registered module-owned entity scope (e.g. compliance's `"standard"`), not the core `"org"`/`"project"`; drives the
   * entity picker generically for any module's scope. */
  function isRegisteredEntityScope(scope: string): boolean {
    return entityScopes.some((s) => s.key === scope);
  }

  /** Label for a `CustomRoleDefinition.scope`: `"org"`/`"project"` use fixed strings, any other value its registered `EntityScope.label` (the raw key
   * if unregistered, e.g. the module was disabled after the role was defined), never a per-module branch. */
  function customRoleScopeLabel(scope: string): string {
    if (scope === "org") return strings.orgAdmin.customRoleScopeOrg;
    if (scope === "project") return strings.orgAdmin.customRoleScopeProject;
    return entityScopes.find((s) => s.key === scope)?.label ?? scope;
  }

  /** The Role Management grant/revoke-by-search control (below the custom-roles table) for org-, project- and entity-scoped roles and user and
   * group targets: `payload.project_id` is required iff `role.scope === "project"` and `payload.scope_entity_id` iff `role.scope` is a registered
   * entity scope. */
  function resolveCustomRoleGrantProjectId(role: CustomRoleDefinition): string | undefined {
    return role.scope === "project" ? customRoleGrantProjectId[role.id] || undefined : undefined;
  }

  function resolveCustomRoleGrantEntityId(role: CustomRoleDefinition): string | undefined {
    return isRegisteredEntityScope(role.scope) ? customRoleGrantEntityId[role.id] || undefined : undefined;
  }

  async function grantCustomRoleToUserById(role: CustomRoleDefinition, userId: string, targetLabel: string) {
    const projectId = resolveCustomRoleGrantProjectId(role);
    const scopeEntityId = resolveCustomRoleGrantEntityId(role);
    try {
      await api.post(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/users/${userId}`, {
        project_id: projectId ?? null,
        scope_entity_id: scopeEntityId ?? null,
      });
      if (!projectId && !scopeEntityId) {
        setUsers((prev) =>
          prev.map((x) =>
            x.user_id === userId && !x.custom_roles.some((g) => g.custom_role_id === role.id)
              ? { ...x, custom_roles: [...x.custom_roles, { custom_role_id: role.id, name: role.name }] }
              : x
          )
        );
      }
      showToast(strings.orgAdmin.customRoleGrantedTo(targetLabel));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeCustomRoleFromUserById(role: CustomRoleDefinition, userId: string, targetLabel: string) {
    const projectId = resolveCustomRoleGrantProjectId(role);
    const scopeEntityId = resolveCustomRoleGrantEntityId(role);
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (scopeEntityId) params.set("scope_entity_id", scopeEntityId);
      const qs = params.toString() ? `?${params.toString()}` : "";
      await api.delete(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/users/${userId}${qs}`);
      if (!projectId && !scopeEntityId) {
        setUsers((prev) =>
          prev.map((x) =>
            x.user_id === userId
              ? { ...x, custom_roles: x.custom_roles.filter((g) => g.custom_role_id !== role.id) }
              : x
          )
        );
      }
      showToast(strings.orgAdmin.customRoleRevokedFrom(targetLabel));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function grantCustomRoleToGroupById(role: CustomRoleDefinition, groupId: string, targetLabel: string) {
    const projectId = resolveCustomRoleGrantProjectId(role);
    const scopeEntityId = resolveCustomRoleGrantEntityId(role);
    try {
      await api.post(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/groups/${groupId}`, {
        project_id: projectId ?? null,
        scope_entity_id: scopeEntityId ?? null,
      });
      showToast(strings.orgAdmin.customRoleGrantedTo(targetLabel));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeCustomRoleFromGroupById(role: CustomRoleDefinition, groupId: string, targetLabel: string) {
    const projectId = resolveCustomRoleGrantProjectId(role);
    const scopeEntityId = resolveCustomRoleGrantEntityId(role);
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (scopeEntityId) params.set("scope_entity_id", scopeEntityId);
      const qs = params.toString() ? `?${params.toString()}` : "";
      await api.delete(`/api/v1/orgs/${orgId}/custom-roles/${role.id}/groups/${groupId}${qs}`);
      showToast(strings.orgAdmin.customRoleRevokedFrom(targetLabel));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // One availability choice is one PUT of both levers (`enabled` + `default_project_enabled`), patched into local state, with a toast.
  async function setModuleAvailability(moduleKey: string, availability: ModuleAvailability) {
    try {
      const updated = await api.put<OrgModule>(
        `/api/v1/orgs/${orgId}/modules/${moduleKey}`, fromModuleAvailability(availability),
      );
      setModules((prev) => prev.map((m) => (m.module_key === moduleKey ? updated : m)));
      showToast(strings.orgAdmin.moduleAvailabilityToast(updated.name, MODULE_AVAILABILITY_LABEL[availability]));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Sub-component sibling of `setModuleAvailability`. */
  async function setSubComponentAvailability(moduleKey: string, subcomponentKey: string, availability: ModuleAvailability) {
    try {
      const updated = await api.put<OrgModuleSubComponent>(
        `/api/v1/orgs/${orgId}/modules/${moduleKey}/subcomponents/${subcomponentKey}`,
        fromModuleAvailability(availability),
      );
      setOrgModuleSubComponents((prev) => ({
        ...prev,
        [moduleKey]: (prev[moduleKey] ?? []).map((s) => (s.subcomponent_key === subcomponentKey ? updated : s)),
      }));
      showToast(strings.orgAdmin.moduleAvailabilityToast(updated.name, MODULE_AVAILABILITY_LABEL[availability]));
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

  /** Deletes an organisation group after confirmation and closes its panel; a refusal (a module relies on the group) is an error toast with the server's reason. */
  async function deleteOrgGroup(groupId: string, replacement?: PrincipalRef, clearOptional = false) {
    const query = new URLSearchParams();
    if (replacement) {
      query.set("replacement_type", replacement.type);
      query.set("replacement_id", replacement.id);
    }
    if (clearOptional) query.set("clear_optional", "true");
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    try {
      await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}${suffix}`);
      setDeletingOrgGroupId(null);
      setInUseOrgGroup(null);
      if (openOrgGroupId === groupId) setOpenOrgGroupId(null);
      showToast(strings.admin.groupDeleted);
      reload();
    } catch (err) {
      setDeletingOrgGroupId(null);
      // From the in-use dialog: let it show the error itself.
      if (replacement || clearOptional) throw err;
      // Records still name the group: show what, and offer to hand them over (or clear them).
      if (err instanceof ApiError && err.status === 409) {
        try {
          const usage = await api.get<PrincipalUsage>(`/api/v1/orgs/${orgId}/groups/${groupId}/usage`);
          if (usage.total > 0) {
            setInUseOrgGroup({ id: groupId, usage });
            return;
          }
        } catch {
          // Fall through to the plain error toast.
        }
      }
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function removeGroupMember(groupId: string, userId: string) {
    if (!(await run(() => api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${userId}`), "remove", "group member"))) return;
    reload();
  }

  const [nestSelections, setNestSelections] = useState<Record<string, string>>({});
  const [nestErrors, setNestErrors] = useState<Record<string, string | null>>({});

  async function addNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    setNestErrors((prev) => ({ ...prev, [groupId]: null }));
    try {
      await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { member_org_group_id: memberOrgGroupId });
      showToast(strings.mutation.success("nested group", strings.mutation.past.add));
      setNestSelections((prev) => ({ ...prev, [groupId]: "" }));
      reload();
    } catch (err) {
      setNestErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
  }

  async function removeNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    if (!(await run(() => api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${memberOrgGroupId}`), "remove", "nested group member"))) return;
    reload();
  }

  const [idpSyncEdits, setIdpSyncEdits] = useState<Record<string, string>>({});
  // Granted-role edits are saved with the sync name above by one button: a role is meaningful only with a sync name, and separate saves could
  // represent the "role with no sync target" state the backend rejects.
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
      // Principle 7: feedback on every mutation.
      showToast(strings.orgAdmin.groupSyncUpdated);
      reload();
    } catch (err) {
      setIdpSyncErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
  }

  /** The SSO-sync enable/disable checkbox: checking it only reveals the name and role fields (no request until "Save sync settings"); unchecking
   * clears both through the `PATCH` Save uses, since nothing is left to edit once sync is off. */
  async function toggleGroupSync(groupId: string, enabled: boolean) {
    setSyncEnabledEdits((prev) => ({ ...prev, [groupId]: enabled }));
    if (!enabled) {
      await saveIdpSync(groupId, "", "");
    }
  }

  async function saveBranding() {
    setBrandingError(null);
    try {
      await api.put<Organization>(`/api/v1/orgs/${orgId}/branding`, {
        accent_color_hex: useOwnAccentColor ? accentColorInput : null,
        logo_band_color_hex: logoBandInput || null,
        logo_band_text_color_hex: logoBandTextInput || null,
        footer_position: footerPositionInput || null,
        report_accent_color_hex: useOwnReportAccent ? reportAccentInput : null,
        report_include_logo: reportIncludeLogo,
        report_colour_scheme: reportColourScheme,
        header_title: headerTitleInput || null,
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
      await api.postFile(`/api/v1/orgs/${orgId}/branding-image`, file, { kind: "login_background" });
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
      await api.delete(`/api/v1/orgs/${orgId}/branding-image?kind=login_background`);
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
    try {
      const saved = await api.put<OrgSsoConfig>(`/api/v1/orgs/${orgId}/sso-config`, {
        slug: slugInput || null,
        sso_enabled: ssoEnabled,
        sso_only: ssoOnly,
        oidc_issuer_url: oidcIssuerUrl || null,
        oidc_client_id: oidcClientId || null,
        oidc_client_secret: oidcClientSecret || null,
        oidc_required_group: oidcRequiredGroup || null,
        oidc_allow_account_creation: oidcAllowAccountCreation,
      });
      setSsoConfig(saved);
      setOidcClientSecret("");
      showToast(strings.mutation.success(strings.orgAdmin.ssoSettingsNoun, strings.mutation.past.save));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function regenerateScimToken() {
    try {
      const created = await api.post<ScimTokenCreated>(`/api/v1/orgs/${orgId}/scim-token`);
      setScimGeneratedToken(created.token);
      setScimStatus({ enabled: true, token_prefix: created.token_prefix });
      showToast(strings.mutation.success(strings.orgAdmin.scimTokenNoun, strings.mutation.past.generate));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeScimToken() {
    try {
      await api.delete(`/api/v1/orgs/${orgId}/scim-token`);
      showToast(strings.mutation.success(strings.orgAdmin.scimTokenNoun, strings.mutation.past.revoke));
      setScimGeneratedToken(null);
      setScimStatus({ enabled: false, token_prefix: null });
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Toggles one user's display-name lock and updates just that row, with a toast; a full `reload()` (~15 requests) would re-render the users
   * table and close a menu the administrator just reopened. */
  async function toggleDisplayNameLock(user: OrgUser) {
    const locked = !user.display_name_locked;
    try {
      await api.put(`/api/v1/orgs/${orgId}/users/${user.user_id}/display-name-lock`, { display_name_locked: locked });
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
      return;
    }
    setUsers((prev) => prev.map((u) => (u.user_id === user.user_id ? { ...u, display_name_locked: locked } : u)));
    showToast(strings.orgAdmin.displayNameLockSaved(user.display_name, locked));
  }

  /** Users table Actions column, "Remove from {org}": the admin-initiated `DELETE /{organization_id}/users/{user_id}/membership`, confirmed by
   * `ConfirmDialog` (`confirmRemoveUser`) before this is called. It is not offered on the caller's own row, where the Actions `ActionMenu` routes
   * self-removal to "Leave organisation" on `PreferencesPage.tsx` (the endpoint's self-targeting guard). */
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
  const [importMergeFilesPrompt, setImportMergeFilesPrompt] = useState<UploadsDisabledInfo | null>(null);
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

  async function confirmImportMerge(skipFiles = false) {
    if (!orgId || !importMergeFile) return;
    setImportMergeError(null);
    setImportMergeSubmitting(true);
    try {
      const result = await api.postFile<OrgMergeResult>(`/api/v1/orgs/${orgId}/import/merge`, importMergeFile, {
        resolutions: JSON.stringify(importMergeResolutions), ...(skipFiles ? { skip_files: "true" } : {}),
      });
      setImportMergeFilesPrompt(null);
      setImportMergeResult(result);
      setImportMergeFile(null);
      setImportMergeConflicts(null);
      setImportMergeResolutions({});
      reload();
    } catch (err) {
      const filesInfo = skipFiles ? null : uploadsDisabledInfo(err);
      if (filesInfo) setImportMergeFilesPrompt(filesInfo);
      else setImportMergeError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setImportMergeSubmitting(false);
    }
  }

  function cancelImportMerge() {
    setImportMergeFilesPrompt(null);
    setImportMergeFile(null);
    setImportMergeConflicts(null);
    setImportMergeResolutions({});
    setImportMergeError(null);
  }

  const orgIsDisabled = loadError?.toLowerCase().includes("disabled") ?? false;

  if (loadError && orgIsDisabled && user?.is_server_admin) {
    // A server administrator reaching a disabled organisation (possibly already a member of it): the one useful action is re-enabling it, then
    // the page reloads as normal for anyone with a role.
    return (
      <div className="stack">
        <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
          <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
          {/* An escape from the degraded page: the organisation is disabled, but a server administrator can jump to a working one. */}
          {orgId && <EntitySwitcher label="Switch organisation" currentId={orgId} loadOptions={() => loadOrgSwitcherOptions("admin")} />}
        </div>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.serverOrgs.disabled}</h2>
          <p className="text-muted">{loadError}</p>
          <InlineMessage>{enableError}</InlineMessage>
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
    // Plain, non-actionable error: a disabled organisation for a non-server-administrator, or any organisation they are not a member of.
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
    // I-M-05's carve-out: a server administrator has no automatic role here but can become its admin (self-hosting) or create an admin user
    // for someone else (hosting company, whether or not the organisation has users); both are server-administrator-only at the API.
    return (
      <div className="stack">
        <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
          <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
          {/* The same escape: a server administrator who is not a member here can jump to another organisation they administer. */}
          {orgId && <EntitySwitcher label="Switch organisation" currentId={orgId} loadOptions={() => loadOrgSwitcherOptions("admin")} />}
        </div>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.notAMemberTitle(orgLabel)}</h2>
          <p className="text-muted">{strings.orgAdmin.notAMemberHint}</p>
          <InlineMessage>{joinError}</InlineMessage>
          <button className="btn btn-primary" onClick={joinAsAdmin} disabled={joining} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.joinAsAdmin(orgLabel)}
          </button>
        </div>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.createInitialAdmin}</h2>
          <FormGrid minColumn="14rem">
            <TextField helpNotNeeded required label={strings.orgAdmin.email} value={bootstrapEmail} onChange={setBootstrapEmail} />
            <TextField helpNotNeeded required label={strings.orgAdmin.name} value={bootstrapName} onChange={setBootstrapName} />
            <TextField helpNotNeeded required
              label={strings.orgAdmin.password}
              value={bootstrapPassword}
              onChange={setBootstrapPassword}
              inputProps={{ type: "password" }}
            />
          </FormGrid>
          <InlineMessage>{bootstrapError}</InlineMessage>
          {bootstrapCreated && <InlineMessage tone="success">{strings.orgAdmin.initialAdminCreated(orgLabel)}</InlineMessage>}
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

  // sso_only and allow_self_signup are mutually exclusive (an SSO-only organisation cannot create native-password accounts); the backend rejects
  // the combination (test_sso_only_enforcement.py), and this surfaces the conflict before the round trip.
  const selfSignupConflict = allowSelfSignup && ssoOnly;

  // Every enabled installed module's `orgAdminSections` (`modules/types.ts`), flattened: the dynamic tail merged onto the ten core groups.
  // Filtered by this organisation's module enablement (`modules`, from `GET /orgs/{id}/modules`), not merely installed, so disabling a module
  // removes its navigation entries.
  const enabledModuleKeys = new Set(modules.filter((m) => m.enabled).map((m) => m.module_key));
  const coreGroupKeys: readonly string[] = CORE_ORG_ADMIN_GROUP_KEYS;
  const moduleAdminSections = installedModules
    .filter((m) => enabledModuleKeys.has(m.key))
    .flatMap((m) => (m.orgAdminSections ?? []).filter((section) => {
      // A section tied to a sub-component is left out once that sub-component is known to be off for the organisation.
      const subs = orgModuleSubComponents[m.key];
      return !section.subComponent || !subs || subs.some((s) => s.subcomponent_key === section.subComponent && s.enabled);
    }))
    // Defensive: a module section whose `key` collides with a core group is dropped instead of shadowing or duplicating it in the navigation
    // (a collision between two modules is no worse than one with a core group, so it is not checked).
    .filter((section) => {
      if (coreGroupKeys.includes(section.key) || (section.group && coreGroupKeys.includes(section.group.key))) {
        console.error(`Module-contributed org-admin section "${section.key}" collides with a core group key; ignoring it.`);
        return false;
      }
      return true;
    });
  const adminBasePath = `/orgs/${orgId}/admin`;
  const moduleRoute = resolveAdminSection(moduleAdminSections, adminBasePath, groupParam, sectionParam);

  const orgAdminGroups: ResourceMenuGroupDef<OrgAdminGroupKey>[] = [
    { key: "overview", label: strings.orgAdmin.groupOverview, href: `/orgs/${orgId}/admin/overview` },
    { key: "details", label: strings.orgAdmin.groupOrganisationDetails(orgLabelCap), href: `/orgs/${orgId}/admin/details` },
    { key: "users", label: strings.orgAdmin.groupUsers, href: `/orgs/${orgId}/admin/users` },
    { key: "groups", label: strings.orgAdmin.groupGroups, href: `/orgs/${orgId}/admin/groups` },
    { key: "projects", label: strings.orgAdmin.groupProjects, href: `/orgs/${orgId}/admin/projects` },
    { key: "workflow", label: strings.orgAdmin.groupWorkflow, href: `/orgs/${orgId}/admin/workflow` },
    { key: "lifecycles", label: strings.orgAdmin.groupLifecycles, href: `/orgs/${orgId}/admin/lifecycles` },
    { key: "branding-defaults", label: strings.orgAdmin.groupBrandingDefaults, href: `/orgs/${orgId}/admin/branding-defaults` },
    { key: "oauth-sso", label: strings.orgAdmin.groupOauthSso, href: `/orgs/${orgId}/admin/oauth-sso` },
    { key: "email", label: strings.orgAdmin.groupEmail, href: `/orgs/${orgId}/admin/email` },
    { key: "security", label: strings.orgAdmin.groupSecurity, href: `/orgs/${orgId}/admin/security` },
    { key: "modules", label: strings.orgAdmin.groupModules, href: `/orgs/${orgId}/admin/modules` },
    { key: "messages", label: strings.announcements.heading, href: `/orgs/${orgId}/admin/messages` },
    { key: "policies", label: strings.policies.heading, href: `/orgs/${orgId}/admin/policies` },
    { key: "role-management", label: strings.orgAdmin.groupRoleManagement, href: `/orgs/${orgId}/admin/role-management` },
    ...buildAdminMenuEntries(moduleAdminSections, adminBasePath),
  ];
  // The active entry is a core group key or a module section key; the menu opens the group holding a section.
  const activeGroup: OrgAdminGroupKey = moduleRoute.section
    ? moduleRoute.section.key
    : (CORE_ORG_ADMIN_GROUP_KEYS as readonly string[]).includes(groupParam ?? "")
      ? (groupParam as OrgAdminGroupKey)
      : "overview";

  // Users table row merge: pending org-only invites are merged client-side into the same `DirectoryTable` as real users, `kind: "user" | "invited"`.
  // They come from a separate unpaginated endpoint, so they render ahead of the sorted, paginated user rows. Search applies (against the invite's
  // email); the stale/no-2FA/no-project-access/role filters do not, since the account does not exist yet; only "Show invited" hides them.
  const filteredOrgInvites = showInvitedUsers
    ? orgInvites.filter((invite) => !userSearch || invite.email.toLowerCase().includes(userSearch.toLowerCase()))
    : [];
  const usersRows: UsersRow[] = [
    ...filteredOrgInvites.map((invite): UsersRow => ({ kind: "invited", invite })),
    ...users.map((u): UsersRow => ({ kind: "user", user: u })),
  ];
  // Resolves a module role definition's `module_key` to the module's display `name` (from `modules`) for the Roles option label "<role name>
  // (<module name>)"; falls back to the raw key only if `modules` has not resolved.
  function moduleDisplayNameFor(moduleKey: string): string {
    return modules.find((m) => m.module_key === moduleKey)?.name ?? moduleKey;
  }
  const usersColumns: DirectoryColumn<UsersRow>[] = [
    {
      key: "email", label: strings.orgAdmin.email, sortable: true,
      render: (row) => {
        if (row.kind === "invited") return row.invite.email;
        // A service user with no address of its own has only a generated one, which is never shown.
        if (row.user.has_deliverable_email === false) return <span className="text-muted">—</span>;
        return row.user.email;
      },
    },
    {
      // For an invited row there is no display name yet (the invitee sets it at signup), so this shows who sent the invite.
      key: "display_name", label: strings.orgAdmin.name, sortable: true,
      render: (row) =>
        row.kind === "user" ? (
          <OrgUserNameCell user={row.user} onOpenServiceUser={serviceUserDialogs.openDetail} />
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
                // A user cannot revoke their own organisation role here (the backend's self-targeting block; an organisation cannot reach zero admins
                // through this control). Granting oneself a role is allowed, so only the uncheck direction is disabled.
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
              // Merged in beside the three core roles in the same dropdown, never disabled (module roles have no self-targeting restriction). The label is
              // the role definition's `name` (human-readable API data) plus the owning module's name, e.g. "Compliance Officer (Compliance)".
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
              // Fine-Grained Access Control (core): org-scoped custom roles, merged as module roles are; a project-scoped custom role is not offered here
              // (see `grantOrgScopedCustomRoleToUser`) but from the Role Management grant/revoke picker.
              ...customRoles
                .filter((role) => role.scope === "org")
                .map((role) => {
                  const checked = u.custom_roles.some((g) => g.custom_role_id === role.id);
                  return {
                    value: `custom:${role.id}`,
                    label: role.name,
                    checked,
                    optionLabel: checked
                      ? strings.orgAdmin.revokeRole(role.name, u.display_name)
                      : strings.orgAdmin.grantRole(role.name, u.display_name),
                    onToggle: () =>
                      checked
                        ? revokeOrgScopedCustomRoleFromUser(u, role)
                        : grantOrgScopedCustomRoleToUser(u, role),
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
            <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
              <Badge>{PENDING_INVITE_STATUS_LABEL[invite.status]}</Badge>
              <button
                className="btn"
                disabled={resendingOrgInviteId === invite.id}
                onClick={() => resendOrgInvite(invite)}
                title={strings.admin.resendInviteAria(invite.email)}
                aria-label={strings.admin.resendInviteAria(invite.email)}
              >
                <Send /> {strings.admin.resendInvite}
              </button>
            </div>
          );
        }
        const u = row.user;
        if (u.is_archived) return strings.orgAdmin.statusArchived;
        if (!u.is_active) return strings.orgAdmin.statusDeactivated;
        return <Tooltip label={strings.orgAdmin.statusActiveHint} wrap>{strings.orgAdmin.statusActive}</Tooltip>;
      },
    },
    {
      // For an invited row this shows when the invite was sent, since there is no last login yet.
      key: "last_login_at", label: strings.orgAdmin.lastLogin, sortable: true,
      render: (row) => {
        if (row.kind === "invited") {
          return (
            <span className="text-muted">
              {strings.orgAdmin.invitedSentOn(new Date(row.invite.created_at).toLocaleDateString())}
            </span>
          );
        }
        // A service user has no sign-in; its last use is the token's, shown in its dialog.
        if (row.user.is_service_account) return <span className="text-muted">{strings.serviceUsers.notApplicable}</span>;
        return row.user.last_login_at ? new Date(row.user.last_login_at).toLocaleDateString() : strings.orgAdmin.never;
      },
    },
    {
      key: "2fa", label: strings.orgAdmin.twoFactor,
      render: (row) =>
        row.kind === "invited"
          ? ""
          : row.user.is_service_account
            ? strings.serviceUsers.notApplicable
            : row.user.is_2fa_enabled ? strings.common.yes : strings.common.no,
    },
    {
      // Users table Actions column (docs/decisions.md): one `ActionMenu` (View access, lock/unlock display name, "Remove from {org}"). "Add to group" is
      // a separate small control beside it because `AddToGroupControl` needs its own anchored `Popover`, which a single-`onSelect` menu item cannot host.
      key: "actions", label: "",
      render: (row) => {
        if (row.kind === "invited") return null;
        const u = row.user;
        const isSelf = u.user_id === user?.id;
        return (
          <div className="row" style={{ gap: "var(--space-1)" }}>
            <ActionMenu
              triggerLabel={strings.orgAdmin.usersActionsFor(u.display_name)}
              items={[
                { label: strings.orgAdmin.viewAccess(u.display_name), icon: <Eye size={14} />, onSelect: () => openUserAccess(u) },
                {
                  label: u.display_name_locked ? strings.orgAdmin.unlockDisplayName : strings.orgAdmin.lockDisplayName,
                  icon: u.display_name_locked ? <Lock size={14} /> : <Unlock size={14} />,
                  onSelect: () => toggleDisplayNameLock(u),
                },
                // Emails the person a single-use reset link; the admin never sees it. Not offered on the
                // caller's own row (they use the sign-in page's "Forgot your password?").
                ...(isSelf || u.is_service_account
                  ? []
                  : [{ label: strings.passwordReset.sendLinkAction, icon: <KeyRound size={14} />, onSelect: () => setResetLinkUser(u) }]),
                // Not offered on the caller's own row: self-removal has its own guarded path ("Leave organisation" on Preferences), matching
                // the endpoint's self-targeting guard (see `remove_org_user`).
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
            <AddToGroupControl user={u} groups={allGroups} onAdd={(groupId, userId) => run(() => addGroupMember(groupId, userId), "add", "group member")} />
          </div>
        );
      },
    },
  ];

  // Org Groups `DirectoryTable`: `groups` is already sorted server-side (`applyGroupSort`/`loadGroups`' `order`), so no client re-sort.
  const orgGroupColumns: DirectoryColumn<OrgGroup>[] = [
    { key: "name", label: strings.orgAdmin.name, sortable: true, render: (g) => g.name },
    {
      key: "members", label: strings.orgAdmin.groupMembersColumn,
      render: (g) => strings.admin.memberCount(g.member_user_ids.length),
    },
  ];

  // A partial module address (`/admin/<section>`, `/admin/<group>`) is replaced by the full one.
  if (moduleRoute.redirectTo) return <Navigate to={moduleRoute.redirectTo} replace />;
  // The combined "Projects & workflow" address lands on Projects (workflow settings have their own entry).
  if (groupParam === "projects-workflow") return <Navigate to={`${adminBasePath}/projects`} replace />;

  return (
    <div className="stack">
      <ResourceMenu
        title={org.name}
        subtitle={strings.orgAdmin.adminSubtitle(orgLabelCap)}
        titleAdornment={orgId && <EntitySwitcher label="Switch organisation" currentId={orgId} loadOptions={() => loadOrgSwitcherOptions("admin")} />}
        ariaLabel={strings.orgAdmin.sectionsNav}
        groups={orgAdminGroups}
        active={activeGroup}
      >
        {activeGroup === "overview" && (
          <div className="stack">
            {orgId && <OrgUsageTable orgId={orgId} />}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <div className="row">
                {org.logo_file_id && (
                  <img src={fileUrl(org.logo_file_id)} alt={`${org.name} logo`} style={{ height: 40 }} />
                )}
                {/* Style guide "Pattern: action menu": rename and export are behind one kebab trigger. Rename is offered only when `advanced` has loaded
                    (the organisation-admin-only gate; a non-admin 403s on advanced-settings); export is available to every member. */}
                <ActionMenu
                  triggerLabel={strings.orgAdmin.orgActions(orgLabelCap)}
                  disabled={exportingOrg}
                  items={[
                    {
                      label: strings.orgAdmin.exportBundle(orgLabel),
                      icon: <Download size={14} />,
                      onSelect: exportOrg,
                    },
                  ]}
                />
              </div>
            </div>

            <CollapsibleSection sectionKey="orgAdmin.importMerge" title={strings.importMerge.action(orgLabel)} defaultCollapsed help={strings.importMerge.hint(orgLabel)}>
              {!importMergeConflicts && !importMergeResult && (
                <div className="stack">
                  <FileField helpNotNeeded label={strings.importMerge.chooseFile} accept=".zip,application/zip" onChange={setImportMergeFile} />
                  <button
                    className="btn btn-primary" onClick={previewImportMerge}
                    disabled={!importMergeFile || importMergePreviewing} style={{ alignSelf: "flex-start" }}
                  >
                    <Upload /> {importMergePreviewing ? strings.importMerge.previewing : strings.importMerge.preview}
                  </button>
                </div>
              )}
              {importMergeConflicts && !importMergeResult && importMergeFilesPrompt && (
                <UploadsDisabledPrompt
                  info={importMergeFilesPrompt} onCancel={cancelImportMerge} onContinue={() => confirmImportMerge(true)}
                  busy={importMergeSubmitting}
                />
              )}
              {importMergeConflicts && !importMergeResult && !importMergeFilesPrompt && (
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
                      className="btn btn-primary" onClick={() => confirmImportMerge()} disabled={importMergeSubmitting}
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
                  </ul>
                  <ImportWarnings warnings={importMergeResult.warnings} />
                  <button className="btn" onClick={() => setImportMergeResult(null)} style={{ alignSelf: "flex-start" }}>
                    {strings.common.close}
                  </button>
                </div>
              )}
              <InlineMessage>{importMergeError}</InlineMessage>
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "users" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.users" collapsible={false} title={strings.orgAdmin.users(orgLabelCap)}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-3)" }}>
                <AddUserMenu onInvite={() => setInviteUserModalOpen(true)} onNewUser={() => setNewUserModalOpen(true)} onNewServiceUser={serviceUserDialogs.openCreate} />
                {advanced?.auto_accept_email_domain && (
                  <button
                    className={`btn${outsideDomainUsers !== null ? " btn-primary" : ""}`}
                    onClick={toggleOutsideDomainUsers}
                  >
                    {strings.orgAdmin.showOutsideDomainUsers}
                  </button>
                )}
              </div>
              <InlineMessage>{outsideDomainError}</InlineMessage>
              {outsideDomainUsers !== null && (
                <div className="card stack">
                  <span className="row" style={{ gap: "var(--space-2)" }}>
                    <strong>{strings.orgAdmin.outsideDomainUsers(orgLabel)}</strong>
                    <FieldHelp label={strings.orgAdmin.outsideDomainUsers(orgLabel)} help={strings.orgAdmin.outsideDomainUsersHint(orgLabel)} />
                  </span>
                    <DirectoryTable
                      ariaLabel={strings.orgAdmin.outsideDomainUsers(orgLabel)}
                      rows={outsideDomainUsers}
                      rowKey={(u) => u.user_id}
                      columns={[
                        { key: "email", label: strings.orgAdmin.email, render: (u) => u.email },
                        { key: "name", label: strings.orgAdmin.name, render: (u) => u.display_name },
                      ]}
                      emptyState={<p className="text-muted">{strings.orgAdmin.noOutsideDomainUsers(orgLabel)}</p>}
                    />
                </div>
              )}

              {/* Shared `DirectoryTable` with `FilterPanel` as a full-width bar above the table (`layout="top"`) instead of the standard `.side-grid`
                  layout (docs/ux-style-guide.md "Pattern: filter panel placement — side vs. top"): the 6 columns (Email, Name, Role, Last login,
                  2FA, Actions) are too wide for a 240px side sidebar. */}
              <div className="stack">
                <FilterPanel
                  layout="top"
                  sectionKey="orgAdminUsersFilters"
                  search={userSearch}
                  onSearchChange={handleUserSearchChange}
                  searchPlaceholder={strings.orgAdmin.searchUsers}
                >
                  {/* `strings.orgAdmin.orgRole` is deliberately distinct from the "New user" modal's "Role" label: the modal renders through a portal while this
                      page stays mounted, so an unscoped `getByLabel("Role")` would be ambiguous. */}
                  <FilterSelect
                    label={strings.orgAdmin.orgRole(orgLabelCap)}
                    value={userRoleFilter}
                    onChange={(v) => applyUserFilters({ role: v })}
                    allLabel={strings.orgAdmin.allRoles}
                    options={[{ value: "member", label: ORG_ROLE_LABEL.member }, { value: "project_creator", label: ORG_ROLE_LABEL.project_creator }, { value: "org_admin", label: ORG_ROLE_LABEL.org_admin }]}
                  />
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
                    label={strings.orgAdmin.filterServiceUsers}
                    checked={userFilterService}
                    onChange={(checked) => applyUserFilters({ service: checked })}
                  />
                  <FilterCheckbox
                    label={strings.orgAdmin.filterIncludeArchived}
                    checked={userFilterArchived}
                    onChange={(checked) => applyUserFilters({ archived: checked })}
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
              <Modal title={strings.orgAdmin.newUser} onClose={() => setNewUserModalOpen(false)} size="lg">
                <div className="stack">
                  <NewUserFields pointToServiceUser values={newUser} onChange={(patch) => setNewUser((prev) => ({ ...prev, ...patch }))} />
                  <FormActions
                    onCancel={() => setNewUserModalOpen(false)}
                    onSave={createUser}
                    saveLabel={strings.common.create}
                    saveDisabled={!newUser.email || !newUser.displayName || !newUser.password}
                  />
                </div>
              </Modal>
            )}

            {inviteUserModalOpen && (
              <Modal title={strings.orgAdmin.inviteUser} onClose={() => setInviteUserModalOpen(false)}>
                <div className="stack">
                  <TextField required help={strings.orgAdmin.inviteUserModalHint}
                    label={strings.orgAdmin.email}
                    value={inviteUserEmail}
                    onChange={setInviteUserEmail}
                    inputProps={{ autoFocus: true, type: "email" }}
                  />
                  <FormActions
                    onCancel={() => setInviteUserModalOpen(false)}
                    onSave={inviteOrgUser}
                    saveLabel={strings.orgAdmin.sendInvite}
                    saveDisabled={!inviteUserEmail}
                  />
                </div>
              </Modal>
            )}

            {viewingUser && (
              <SidePanel title={strings.orgAdmin.userAccessTitle(viewingUser.display_name)} onClose={() => setViewingUser(null)}>
                <InlineMessage>{userAccessError}</InlineMessage>
                {!userAccess && !userAccessError && <Spinner />}
                {userAccess && (
                  <div className="stack">
                    <div className="stack" style={{ gap: "var(--space-1)" }}>
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
                    <div className="stack" style={{ gap: "var(--space-1)" }}>
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
                            <div key={p.project_id} className="card stack" style={{ gap: "var(--space-2)" }}>
                              <Link to={`/projects/${p.project_id}`}>{p.project_name}</Link>
                              <div className="row" style={{ gap: "var(--space-1)", flexWrap: "wrap", alignItems: "center" }}>
                                {shownRoles.map((r) => (
                                  <Badge key={r}>{PROJECT_ROLE_LABEL[r]}</Badge>
                                ))}
                                {canExpand && (
                                  <button
                                    type="button"
                                    className="btn"
                                    style={{ fontSize: "0.75rem", padding: "0.15rem var(--space-3)" }}
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
            {serviceUserDialogs.dialogs}
            <CollapsibleSection sectionKey="orgAdmin.importedPeople" title={strings.importPeople.panelTitle}>
              {orgId && <ImportedPeoplePanel orgId={orgId} />}
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "groups" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.groups" collapsible={false} title={strings.orgAdmin.groups(orgLabelCap)}>
              <button
                className="btn btn-primary"
                style={{ alignSelf: "flex-start" }}
                onClick={() => setNewGroupModalOpen(true)}
              >
                <Plus /> {strings.orgAdmin.newGroup}
              </button>
              {newGroupModalOpen && (
                // Style guide "Pattern: modal dialog for entity create/rename": a new entity opens in a Modal; the Popover-vs-Modal decision tree
                // reserves Popover for a quick action on something that exists.
                <Modal title={strings.orgAdmin.newGroup} onClose={() => setNewGroupModalOpen(false)}>
                  <TextField helpNotNeeded required
                    label={strings.admin.name}
                    value={newGroupName}
                    onChange={setNewGroupName}
                    placeholder={strings.orgAdmin.groupNamePlaceholder}
                    inputProps={{ autoFocus: true, onKeyDown: (e) => {
                        if (e.key === "Enter" && newGroupName) createGroup();
                      } }}
                  />
                  <FormActions
                    onCancel={() => setNewGroupModalOpen(false)}
                    onSave={createGroup}
                    saveLabel={strings.common.create}
                    saveDisabled={!newGroupName}
                  />
                </Modal>
              )}

              {/* `FilterPanel` as a full-width bar above the table, like Users: search is its only control, so a side
                  column would waste the width (style guide "Pattern: filter panel placement — side vs. top"). Each
                  row opens a `SidePanel` ("Pattern: entity detail panel"). */}
              <div className="stack">
                <FilterPanel
                  layout="top"
                  sectionKey="orgAdminGroupsFilters"
                  search={groupSearch}
                  onSearchChange={handleGroupSearchChange}
                  searchPlaceholder={strings.orgAdmin.searchGroups}
                >
                  {null}
                </FilterPanel>
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
            </CollapsibleSection>

            {openOrgGroupId && (() => {
              const g = groups.find((x) => x.id === openOrgGroupId);
              if (!g) return null;
              const memberIds = new Set(g.member_user_ids);
              const members = users.filter((u) => memberIds.has(u.user_id));
              const nonMembers = users.filter((u) => !memberIds.has(u.user_id));
              const nestedGroupIds = new Set(g.member_org_group_ids);
              // Resolved against `allGroups` (every group, unpaginated), not the paginated/searched `groups`: a nested group's name, or a candidate to
              // nest, can fall outside the page or search the Groups list shows.
              const nestedGroups = allGroups.filter((og) => nestedGroupIds.has(og.id));
              const nestableGroups = allGroups.filter((og) => og.id !== g.id && !nestedGroupIds.has(og.id));
              // SSO-sync gating: the name input, role select and Save action all sit behind this check, so none shows when SSO is not configured.
              const ssoConfigured = !!(ssoConfig?.oidc_issuer_url && ssoConfig?.oidc_client_id);
              const syncEnabled = syncEnabledEdits[g.id] ?? g.idp_synced_group_name != null;
              return (
                <SidePanel title={strings.orgAdmin.groupDetails(g.name)} onClose={() => setOpenOrgGroupId(null)}>
                  <div className="stack">
                    {members.length > 0 && (
                      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {members.map((u) => (
                          <li key={u.user_id} style={{ listStyle: "disc" }}>
                            <span className="row" style={{ justifyContent: "space-between", gap: "var(--space-3)" }}>
                              <span>
                                {u.display_name} <span className="text-muted">({u.email})</span>
                              </span>
                              <button
                                className="btn"
                                title={strings.admin.removeMember(u.display_name)}
                                aria-label={strings.admin.removeMember(u.display_name)}
                                onClick={() => removeGroupMember(g.id, u.user_id)}
                              >
                                <Trash2 />
                              </button>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <UserAutocomplete
                      users={nonMembers}
                      placeholder={strings.admin.addMemberPlaceholder}
                      onSelect={(userId) => run(() => addGroupMember(g.id, userId), "add", "group member")}
                    />
                    {nestedGroups.length > 0 && (
                      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {nestedGroups.map((og) => (
                          <li key={og.id} style={{ listStyle: "circle" }}>
                            <span className="row" style={{ justifyContent: "space-between", gap: "var(--space-3)" }}>
                              <span>{strings.orgAdmin.nestedGroupLabel(og.name)}</span>
                              <button
                                className="btn"
                                title={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                                aria-label={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                                onClick={() => removeNestedGroupMember(g.id, og.id)}
                              >
                                <Trash2 />
                              </button>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {nestableGroups.length > 0 && (
                      <div className="row">
                        <InlineSelect
                          ariaLabel={strings.orgAdmin.addNestedGroup}
                          placeholder={strings.orgAdmin.addNestedGroup}
                          value={nestSelections[g.id] ?? ""}
                          options={nestableGroups.map((og) => ({ value: og.id, label: og.name }))}
                          onChange={(next) => setNestSelections((prev) => ({ ...prev, [g.id]: next }))}
                        />
                        <button
                          className="btn"
                          disabled={!nestSelections[g.id]}
                          title={strings.orgAdmin.addNestedGroup}
                          aria-label={strings.orgAdmin.addNestedGroup}
                          onClick={() => addNestedGroupMember(g.id, nestSelections[g.id])}
                        >
                          <Plus />
                        </button>
                      </div>
                    )}
                    <InlineMessage>{nestErrors[g.id]}</InlineMessage>

                    {/* SSO sync sub-section, fully gated on `ssoConfigured`: with no SSO configured only the muted hint renders. */}
                    {ssoConfigured ? (
                      <div className="stack" style={{ gap: "var(--space-3)" }}>
                        <CheckboxField help={strings.help.ssoGroupSync}
                          label={strings.orgAdmin.syncFromSso}
                          checked={syncEnabled}
                          onChange={(next) => toggleGroupSync(g.id, next)}
                        />
                        {syncEnabled && (
                          <>
                            <FormGrid minColumn="16rem">
                              <TextField help={strings.help.ssoGroupName}
                                label={strings.orgAdmin.idpSyncedGroupName}
                                placeholder={strings.orgAdmin.idpSyncedGroupNamePlaceholder}
                                value={idpSyncEdits[g.id] ?? g.idp_synced_group_name ?? ""}
                                onChange={(next) => setIdpSyncEdits((prev) => ({ ...prev, [g.id]: next }))}
                              />
                              <LabeledSelect help={strings.help.grantedOrgRole}
                                label={strings.orgAdmin.grantedOrgRole}
                                value={grantedRoleEdits[g.id] ?? g.granted_org_role ?? ""}
                                onChange={(next) => setGrantedRoleEdits((prev) => ({ ...prev, [g.id]: next as OrgRole | "" }))}
                                options={[
                                  { value: "member", label: ORG_ROLE_LABEL.member },
                                  { value: "project_creator", label: ORG_ROLE_LABEL.project_creator },
                                  { value: "org_admin", label: ORG_ROLE_LABEL.org_admin },
                                ]}
                                placeholder={strings.orgAdmin.grantedOrgRoleNone}
                              />
                            </FormGrid>
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
                            <InlineMessage>{idpSyncErrors[g.id]}</InlineMessage>
                          </>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.ssoNotConfiguredHint(orgLabel)}</span>
                    )}
                    <button
                      className="btn btn-danger"
                      style={{ alignSelf: "flex-start" }}
                      onClick={() => setDeletingOrgGroupId(g.id)}
                    >
                      <Trash2 /> {strings.admin.deleteGroup}
                    </button>
                  </div>
                </SidePanel>
              );
            })()}
            {deletingOrgGroupId && (
              <ConfirmDialog
                title={strings.admin.deleteGroupTitle(
                  (groups.find((x) => x.id === deletingOrgGroupId) ?? allGroups.find((x) => x.id === deletingOrgGroupId))?.name ?? ""
                )}
                message={strings.orgAdmin.deleteGroupMessage}
                confirmLabel={strings.admin.deleteGroup}
                onConfirm={() => deleteOrgGroup(deletingOrgGroupId)}
                onCancel={() => setDeletingOrgGroupId(null)}
              />
            )}
            {inUseOrgGroup && orgId && (
              <GroupInUseDialog
                groupName={(groups.find((x) => x.id === inUseOrgGroup.id) ?? allGroups.find((x) => x.id === inUseOrgGroup.id))?.name ?? ""}
                groupId={inUseOrgGroup.id}
                usage={inUseOrgGroup.usage}
                organizationId={orgId}
                orgUsers={users}
                kinds={["user", "org_group"]}
                onReplace={(replacement) => deleteOrgGroup(inUseOrgGroup.id, replacement)}
                onClear={() => deleteOrgGroup(inUseOrgGroup.id, undefined, true)}
                onClose={() => setInUseOrgGroup(null)}
              />
            )}
          </div>
        )}

        {activeGroup === "lifecycles" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.lifecycles" title={strings.lifecycleSettings.heading} help={strings.help.lifecyclesOrganization} defaultCollapsed={false}>
              <OrgLifecyclesPanel organizationId={org.id} />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "projects" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.projectCodes" title={strings.orgAdmin.projectCodes} help={strings.orgAdmin.codePolicyHint}>
              <ProjectCodePolicyPanel org={org} onSaved={setOrg} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.recordCodePrefixes" title={strings.codePrefixes.heading}>
              <RecordCodePrefixPanel scope={{ kind: "organization", organizationId: org.id }} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.requirementAliases" title={strings.requirementAliases.settings.heading}>
              <RequirementAliasSettingsPanel scope={{ kind: "organization", organizationId: org.id }} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.organizationCode" title={strings.orgAdmin.organizationCode} help={strings.orgAdmin.organizationCodeHint}>
              <OrganizationCodePanel org={org} onSaved={setOrg} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.overviewDefault" title={strings.overviewWidgets.orgHeading} help={strings.overviewWidgets.orgHint}>
              <OrgOverviewDefaultPanel organizationId={org.id} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.projectStatuses" title={strings.orgAdmin.projectStatuses} help={strings.orgAdmin.projectStatusesHint}>
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

            <CollapsibleSection sectionKey="orgAdmin.externalSystems" title={strings.externalSystems.heading} help={strings.externalSystems.orgHelp}>
              <OrgExternalSystemsPanel orgId={org.id} />
            </CollapsibleSection>

          </div>
        )}

        {activeGroup === "workflow" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.stageWorkflows" title={strings.stageWorkflows.heading}>
              <StageWorkflowsPanel scope={{ kind: "organisation", organizationId: org.id }} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.linkTypes" title={strings.orgAdmin.linkTypes}>
              <LinkTypesPanel scope={{ kind: "organization", orgId: org.id }} />
            </CollapsibleSection>

            <CollapsibleSection sectionKey="orgAdmin.navLabels" title={strings.navLabels.heading}>
              <NavLabelsPanel scope={{ kind: "organisation", organizationId: org.id }} />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "details" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.details" title={strings.orgAdmin.groupOrganisationDetails(orgLabelCap)} collapsible={false}>
              <OrganisationDetailsPanel org={org} platformBranding={platformBranding} onOrgChange={setOrg} />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "branding-defaults" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.branding" title={strings.orgAdmin.branding}>
              {/* The login background sits beside the logo (style guide "Branding — logo, colour, footer"), not in the SSO section. */}
              <BrandingImageField
                id="org-login-background-input"
                label={strings.orgAdmin.loginBackground}
                fileId={org.login_background_file_id ?? null}
                platformFileId={platformBranding?.default_login_background_file_id ?? null}
                busy={loginBackgroundUploading}
                onSelect={uploadLoginBackground}
                onRemove={removeLoginBackground}
                error={loginBackgroundError}
                uploaded={loginBackgroundUploaded ? strings.orgAdmin.loginBackgroundUploaded : null}
                height={100}
              />

              <TextField help={strings.help.orgHeaderTitle}
                label={strings.orgAdmin.headerTitle}
                placeholder={platformBranding?.default_header_title || strings.appName}
                value={headerTitleInput}
                onChange={setHeaderTitleInput}
                inputProps={{ id: "org-header-title" }}
              />
              <CheckboxField help={strings.help.orgOwnAccentColor}
                label={strings.orgAdmin.useOwnAccentColor(orgLabel)}
                checked={useOwnAccentColor}
                onChange={setUseOwnAccentColor}
              />
              {useOwnAccentColor && (
                <ColorField help={strings.help.orgAccentColor} label={strings.admin.accentColor} value={accentColorInput} onChange={setAccentColorInput} />
              )}
              <LogoBandField
                value={logoBandInput} onChange={setLogoBandInput}
                textValue={logoBandTextInput} onTextChange={setLogoBandTextInput}
                logoFileId={org.logo_file_id ?? platformBranding?.default_logo_file_id ?? null}
                title={org.name}
                platformHex={platformBranding?.logo_band_color_hex ?? null}
                platformTextHex={platformBranding?.logo_band_text_color_hex ?? null}
              />
              <LabeledSelect
                help={strings.help.orgFooterPosition} label={strings.serverSettings.footerPosition}
                placeholder={strings.footerPosition.followPlatform(FOOTER_POSITION_LABEL[platformBranding?.footer_position ?? "after_content"])}
                value={footerPositionInput} onChange={(value) => setFooterPositionInput(value as FooterPosition | "")}
                options={labelOptions(FOOTER_POSITION_LABEL)} autoWidth
              />
              <CheckboxField
                help={strings.help.reportAccentColor}
                label={strings.orgAdmin.useOwnReportAccent}
                checked={useOwnReportAccent}
                onChange={setUseOwnReportAccent}
              />
              {useOwnReportAccent && (
                <ColorField help={strings.help.reportAccentColor} label={strings.orgAdmin.reportAccentColor} value={reportAccentInput} onChange={setReportAccentInput} />
              )}
              <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend><strong>{strings.orgAdmin.reportColourScheme}</strong> <FieldHelp label={strings.orgAdmin.reportColourScheme} help={strings.help.reportColourScheme} /></legend>
                <ReportColourSchemeEditor
                  mode="organization" value={reportColourScheme} onChange={setReportColourScheme}
                  context={{
                    ...DEFAULT_COLOUR_CONTEXT, accent: useOwnReportAccent ? reportAccentInput : useOwnAccentColor ? accentColorInput : DEFAULT_COLOUR_CONTEXT.accent,
                  }}
                />
              </fieldset>
              <CheckboxField
                help={strings.help.reportIncludeLogo}
                label={strings.admin.includeLogo(orgLabel)}
                checked={reportIncludeLogo}
                onChange={setReportIncludeLogo}
              />
              <InlineMessage>{brandingError}</InlineMessage>
              <button className="btn btn-primary" onClick={saveBranding} style={{ alignSelf: "flex-start" }}>
                {strings.orgAdmin.saveBranding}
              </button>
            </CollapsibleSection>

            {defaultTemplateOptions.length > 0 && (
              <div className="card">
                <LabeledSelect
                  label={strings.orgAdmin.defaultTemplate}
                  help={strings.help.orgDefaultTemplate}
                  placeholder={strings.projects.noTemplate}
                  value={org.default_template_project_id ?? ""}
                  options={defaultTemplateOptions.map((p) => ({ value: p.id, label: p.name }))}
                  onChange={setDefaultTemplate}
                  autoWidth
                />
              </div>
            )}
          </div>
        )}

        {activeGroup === "oauth-sso" && (
          <div className="stack">
            {ssoConfig && (
              <CollapsibleSection sectionKey="orgAdmin.sso" collapsible={false} title={strings.orgAdmin.ssoConfig} help={strings.orgAdmin.ssoMappingsMovedHint}>
                <TextField help={strings.help.organizationSlug(orgLabel)}
                  label={strings.orgAdmin.slug}
                  value={slugInput}
                  onChange={setSlugInput}
                />
                <CheckboxField help={strings.help.ssoEnable} label={strings.orgAdmin.ssoEnabled} checked={ssoEnabled} onChange={setSsoEnabled} />
                <CheckboxField help={strings.help.ssoNativeFormHidden} label={strings.orgAdmin.ssoOnly} checked={ssoOnly} onChange={setSsoOnly} />
                <TextField help={strings.help.ssoIssuerUrl} label={strings.orgAdmin.oidcIssuerUrl} value={oidcIssuerUrl} onChange={setOidcIssuerUrl} />
                <TextField help={strings.help.ssoClientId} label={strings.orgAdmin.oidcClientId} value={oidcClientId} onChange={setOidcClientId} />
                <TextField help={strings.help.ssoClientSecret}
                  label={strings.orgAdmin.oidcClientSecret}
                  value={oidcClientSecret}
                  onChange={setOidcClientSecret}
                  inputProps={{ type: "password" }}
                />
                <TextField help={strings.help.ssoRequiredGroup}
                  label={strings.orgAdmin.oidcRequiredGroup}
                  value={oidcRequiredGroup}
                  onChange={setOidcRequiredGroup}
                />
                <CheckboxField help={strings.help.ssoAllowAccountCreation} label={strings.orgAdmin.oidcAllowAccountCreation}
                  checked={oidcAllowAccountCreation} onChange={setOidcAllowAccountCreation} />

                {/* The SSO group-to-role mapping is a property of the organisation group being synced into (`OrgGroup.granted_org_role` beside
                    `idp_synced_group_name`), managed from the Groups section. */}

                <button className="btn btn-primary" onClick={saveSso} style={{ alignSelf: "flex-start" }}>
                  {strings.orgAdmin.saveSso}
                </button>
              </CollapsibleSection>
            )}

            {scimStatus && (
              <CollapsibleSection sectionKey="orgAdmin.scim" collapsible={false} title={strings.orgAdmin.scimProvisioning} help={strings.orgAdmin.scimHint}>
                <div className="row">
                  <span>
                    {scimStatus.enabled
                      ? strings.orgAdmin.scimEnabledWithPrefix(scimStatus.token_prefix ?? "")
                      : strings.orgAdmin.scimDisabled}
                  </span>
                </div>
                {scimGeneratedToken && (
                  <TextField help={strings.help.scimTokenLabel}
                    label={strings.orgAdmin.scimTokenLabel}
                    hint={strings.orgAdmin.scimTokenShownOnce}
                    value={scimGeneratedToken}
                    onChange={() => undefined}
                    inputProps={{ readOnly: true, onFocus: (e) => e.target.select() }}
                  />
                )}
                <div className="row">
                  <button className="btn btn-primary" onClick={() => (scimStatus.enabled ? setScimConfirm("regenerate") : void regenerateScimToken())}>
                    {scimStatus.enabled ? strings.orgAdmin.scimRegenerate : strings.orgAdmin.scimGenerate}
                  </button>
                  {scimStatus.enabled && (
                    <button className="btn btn-danger" onClick={() => setScimConfirm("revoke")}>
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
              <CollapsibleSection sectionKey="orgAdmin.smtpEmail" collapsible={false} title={strings.orgAdmin.smtpEmailTitle}>
                <FormGrid minColumn="14rem">
                  <TextField help={strings.help.smtpHost}
                    label={strings.orgAdmin.smtpHost}
                    value={smtpHost}
                    onChange={(next) => {
                      advancedDirtyRef.current.email = true;
                      setSmtpHost(next);
                    }}
                  />
                  <TextField help={strings.help.smtpPort}
                    label={strings.orgAdmin.smtpPort}
                    value={smtpPort}
                    onChange={(next) => {
                      advancedDirtyRef.current.email = true;
                      setSmtpPort(next);
                    }}
                  />
                  <TextField help={strings.help.smtpUsername}
                    label={strings.orgAdmin.smtpUsername}
                    value={smtpUsername}
                    onChange={(next) => {
                      advancedDirtyRef.current.email = true;
                      setSmtpUsername(next);
                    }}
                  />
                  <TextField help={strings.help.smtpPassword}
                    label={strings.orgAdmin.smtpPassword}
                    value={smtpPassword}
                    onChange={(next) => {
                      advancedDirtyRef.current.email = true;
                      setSmtpPassword(next);
                    }}
                    inputProps={{ type: "password" }}
                  />
                  <FormGridFull>
                    <CheckboxField help={strings.help.smtpUseTls}
                      label={strings.orgAdmin.smtpUseTls}
                      checked={smtpUseTls}
                      onChange={(next) => {
                        advancedDirtyRef.current.email = true;
                        setSmtpUseTls(next);
                      }}
                    />
                  </FormGridFull>
                </FormGrid>

                <div className="stack" style={{ gap: "var(--space-2)" }}>
                  <span className="row" style={{ gap: "var(--space-2)" }}>
                    <strong>{strings.orgAdmin.testEmail}</strong>
                    <FieldHelp label={strings.orgAdmin.testEmail} help={strings.orgAdmin.testEmailHint(orgLabel)} />
                  </span>
                  <div className="row" style={{ alignItems: "flex-end" }}>
                    <TextField help={strings.help.testEmailRecipient}
                      label={strings.orgAdmin.testEmailRecipient}
                      value={testEmailRecipient}
                      onChange={setTestEmailRecipient}
                      inputProps={{ type: "email" }}
                    />
                    <button className="btn" onClick={sendOrgTestEmail} disabled={!smtpHost || sendingTestEmail}>
                      {sendingTestEmail ? strings.orgAdmin.testEmailSending : strings.orgAdmin.testEmail}
                    </button>
                  </div>
                  {!smtpHost && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.testEmailNoSmtp}</span>}
                  <InlineMessage>{testEmailError}</InlineMessage>
                  {testEmailSuccess && <InlineMessage tone="success">{strings.orgAdmin.testEmailSent}</InlineMessage>}
                </div>
                <InlineMessage>{advancedError}</InlineMessage>
                <button
                  className="btn btn-primary"
                  onClick={() => void saveAdvanced("email")}
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
                <ToggleField help={strings.help.requireTwoFactor(orgLabel)}
                  label={strings.orgAdmin.require2fa}
                  checked={require2fa}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setRequire2fa(next);
                  }}
                />

                <ToggleField help={strings.help.allowSelfSignup(orgLabel)}
                  label={strings.orgAdmin.allowSelfSignup}
                  checked={allowSelfSignup}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setAllowSelfSignup(next);
                  }}
                />

                {selfSignupConflict && (
                  <InlineMessage>{strings.orgAdmin.selfSignupSsoConflict(orgLabel)}</InlineMessage>
                )}

                <TextField help={strings.help.acceptedEmailDomain}
                  label={strings.orgAdmin.autoAcceptEmailDomain}
                  value={autoAcceptEmailDomain}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setAutoAcceptEmailDomain(next);
                  }}
                  placeholder="acme.com"
                />

                <LabeledSelect help={strings.help.externalUserPolicy}
                  label={strings.orgAdmin.externalUserPolicy}
                  value={externalUserPolicy}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setExternalUserPolicy(next as ExternalUserPolicy);
                  }}
                  options={[{ value: "disabled", label: strings.orgAdmin.externalUserPolicyDisabled(orgLabel) }, { value: "org_domain_only", label: strings.orgAdmin.externalUserPolicyDomainOnly }, { value: "anyone", label: strings.orgAdmin.externalUserPolicyAnyone }]}
                  placeholder={null}
                />

                <ToggleField help={strings.help.allowRelaxedChildProjectCreation}
                  label={strings.orgAdmin.allowRelaxedChildProjectCreation}
                  checked={allowRelaxedChildProjectCreation}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setAllowRelaxedChildProjectCreation(next);
                  }}
                />

                <ToggleField help={strings.help.forceChangeRequestForLinks}
                  label={strings.orgAdmin.forceRequireChangeRequestForApprovedLinks}
                  checked={forceRequireCrForLinks}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setForceRequireCrForLinks(next);
                  }}
                />

                <ToggleField help={strings.help.allowImportedApprovalState}
                  label={strings.orgAdmin.allowImportedApprovalState}
                  checked={allowImportedApprovalState}
                  onChange={(next) => {
                    advancedDirtyRef.current.security = true;
                    setAllowImportedApprovalState(next);
                  }}
                />

                {/* AI approval via MCP (docs/decisions.md) */}
                <ToggleField help={strings.help.orgAllowAiApprovals}
                  label={strings.orgAdmin.allowAiApprovals}
                  checked={allowAiApprovals}
                  onChange={(next) => {
                    if (next) {
                      setAiApprovalsAckChecked(false);
                      setAiApprovalsAckPending(true);
                    } else {
                      advancedDirtyRef.current.security = true;
                      setAllowAiApprovals(false);
                    }
                  }}
                />

                <InlineMessage>{advancedError}</InlineMessage>
                <button
                  className="btn btn-primary"
                  onClick={() => void saveAdvanced("security")}
                  disabled={selfSignupConflict}
                  style={{ alignSelf: "flex-start" }}
                >
                  {strings.orgAdmin.saveAdvanced}
                </button>
              </CollapsibleSection>
            )}

            {advanced && (
              <CollapsibleSection sectionKey="orgAdmin.pats" title={strings.orgAdmin.pats}>
                <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)" }}>
                  <TextField help={strings.help.patMaxLifetime}
                    label={strings.orgAdmin.patMaxLifetime}
                    value={patMaxLifetimeDays}
                    onChange={(next) => {
                      advancedDirtyRef.current.pats = true;
                      setPatMaxLifetimeDays(next);
                    }}
                    inputProps={{ type: "number", min: 1, max: 3650, style: { maxWidth: 160 } }}
                  />
                  <button className="btn btn-primary" onClick={() => void saveAdvanced("pats")}>
                    {strings.orgAdmin.savePatLifetime}
                  </button>
                </div>
                <InlineMessage>{advancedError}</InlineMessage>

                  <DirectoryTable
                    ariaLabel={strings.orgAdmin.pats}
                    rows={orgPats}
                    rowKey={(p) => p.id}
                    columns={[
                      {
                        key: "user", label: strings.orgAdmin.patUser,
                        render: (p) => (
                          <>
                            <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
                              <span>{p.user_display_name}</span>
                              {p.is_service_account ? <ServiceBadge /> : <span className="text-muted">({p.user_email})</span>}
                            </span>
                            {p.created_by_display_name && (
                              <div className="text-muted">{strings.orgAdmin.patIssuedBy(p.created_by_display_name)}</div>
                            )}
                          </>
                        ),
                      },
                      {
                        key: "name", label: strings.orgAdmin.patName,
                        render: (p) => (
                          <>
                            {p.name}
                            {p.other_org_count > 0 && (
                              <div className="text-muted">{strings.orgAdmin.patOtherOrgs(p.other_org_count, orgLabelPlural)}</div>
                            )}
                          </>
                        ),
                      },
                      { key: "expires", label: strings.orgAdmin.patExpires, render: (p) => new Date(p.expires_at).toLocaleDateString() },
                      {
                        key: "lastUsed", label: strings.orgAdmin.patLastUsed,
                        render: (p) => (p.last_used_at ? new Date(p.last_used_at).toLocaleString() : strings.orgAdmin.never),
                      },
                      {
                        key: "actions", label: "",
                        render: (p) => (
                          <div className="row">
                            {p.other_org_count > 0 && (
                              <button className="btn" onClick={() => setPatToDescope(p.id)}>
                                {strings.orgAdmin.patDescope}
                              </button>
                            )}
                            <button className="btn btn-danger" onClick={() => setPatToRevoke(p.id)}>
                              {strings.orgAdmin.patRevoke}
                            </button>
                          </div>
                        ),
                      },
                    ]}
                    emptyState={<p className="text-muted">{strings.orgAdmin.patNone(orgLabel)}</p>}
                  />

                {orgPats.length > 0 && (
                  <button className="btn btn-danger" onClick={() => setRevokeAllPatsOpen(true)} style={{ alignSelf: "flex-start" }}>
                    {strings.orgAdmin.patRevokeAll(orgLabel)}
                  </button>
                )}
                {patBulkResult && <InlineMessage tone="success">{patBulkResult}</InlineMessage>}
              </CollapsibleSection>
            )}

            {orgId && (
              <CollapsibleSection sectionKey="orgAdmin.personalData" title={strings.personalDataPolicy.title} help={strings.personalDataPolicy.orgHint(orgLabel)}>
                <PersonalDataPolicyPanel scope={{ kind: "organization", organizationId: orgId }} />
              </CollapsibleSection>
            )}
          </div>
        )}

        {activeGroup === "messages" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.messages" collapsible={false} title={strings.announcements.heading}>
              <AnnouncementsPanel scope={{ kind: "organisation", organizationId: org.id }} />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "policies" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.policies" collapsible={false} title={strings.policies.orgHeading}>
              <PoliciesPanel scope={{ kind: "organisation", organizationId: org.id }} />
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "modules" && (
          <div className="stack">
            <CollapsibleSection sectionKey="orgAdmin.modules" collapsible={false} title={strings.orgAdmin.modulesTitle} help={strings.orgAdmin.modulesDescription}>
              {modules.length === 0 ? (
                <p className="text-muted">{strings.orgAdmin.modulesEmpty}</p>
              ) : (
                <ModuleSettingsList
                  items={modules.map((m) => {
                    // Non-entitled and not-yet-implemented modules stay listed (unavailable, with a hint) instead of hidden, for visibility.
                    const disabled = !m.entitled || !m.implemented;
                    const subComponents = orgModuleSubComponents[m.module_key] ?? [];
                    return {
                      key: m.module_key,
                      name: m.name,
                      version: m.version,
                      description: m.description,
                      hint: !m.entitled
                        ? strings.orgAdmin.moduleNotEntitledHint
                        : !m.implemented
                          ? strings.orgAdmin.moduleNotImplementedHint
                          : null,
                      muted: !m.entitled,
                      control: (
                        <ModuleAvailabilitySelect
                          value={toModuleAvailability(m.enabled, m.default_project_enabled)}
                          disabled={disabled}
                          label={strings.orgAdmin.moduleAvailabilityLabel(m.name)}
                          onChange={(next) => setModuleAvailability(m.module_key, next)}
                        />
                      ),
                      subSummary: strings.orgAdmin.moduleSubComponentsSummary(
                        subComponents.length, subComponents.filter((sub) => !sub.enabled).length,
                      ),
                      subItems: subComponents.map((sub) => ({
                        key: sub.subcomponent_key,
                        name: sub.name,
                        control: (
                          <ModuleAvailabilitySelect
                            value={toModuleAvailability(sub.enabled, sub.default_project_enabled)}
                            disabled={disabled || !m.enabled}
                            label={strings.orgAdmin.moduleSubComponentAvailabilityLabel(m.name, sub.name)}
                            onChange={(next) => setSubComponentAvailability(m.module_key, sub.subcomponent_key, next)}
                          />
                        ),
                      })),
                    };
                  })}
                />
              )}
            </CollapsibleSection>
          </div>
        )}

        {activeGroup === "role-management" && (
          <div className="stack">
            {/* Role definition: ORG_ADMIN-only, never delegable. Gated on `advanced !== null`, the signal every ORG_ADMIN-only section here uses
                (`GET .../advanced-settings` is `require_org_role(ORG_ADMIN)` with no server-admin or grant_roles bypass; style guide Principle 4). A
                `grant_roles` holder who is not an ORG_ADMIN sees the assignment half below but not this one. */}
            {advanced !== null && (
              <CollapsibleSection sectionKey="orgAdmin.roleManagement.definitions" collapsible={false} title={strings.orgAdmin.customRolesTitle} help={strings.orgAdmin.customRolesHint}>
                <button
                  className="btn btn-primary"
                  style={{ alignSelf: "flex-start" }}
                  onClick={openCreateCustomRoleModal}
                >
                  <Plus /> {strings.orgAdmin.newCustomRole}
                </button>
                <DirectoryTable
                  ariaLabel={strings.orgAdmin.customRolesTitle}
                  rowKey={(r) => r.id}
                  emptyState={<p className="text-muted">{strings.orgAdmin.noCustomRoles}</p>}
                  rows={customRoles}
                  columns={[
                    { key: "name", label: strings.orgAdmin.customRoleName, render: (r) => <strong>{r.name}</strong> },
                    {
                      key: "description", label: strings.orgAdmin.customRoleDescription,
                      render: (r) => <span className="text-muted">{r.description}</span>,
                    },
                    {
                      key: "scope", label: strings.orgAdmin.customRoleScope,
                      render: (r) => customRoleScopeLabel(r.scope),
                    },
                    {
                      key: "permissions", label: strings.orgAdmin.customRolePermissionsLabel,
                      render: (r) => strings.orgAdmin.customRolePermissionsCount(r.permissions.length),
                    },
                    {
                      key: "actions", label: "",
                      render: (r) => (
                        <div className="row" style={{ gap: "var(--space-1)" }}>
                          <button
                            className="btn"
                            aria-label={strings.orgAdmin.editCustomRole(r.name)}
                            title={strings.orgAdmin.editCustomRole(r.name)}
                            onClick={() => openEditCustomRoleModal(r)}
                          >
                            <Pencil />
                          </button>
                          <button
                            className="btn"
                            aria-label={strings.orgAdmin.deleteCustomRole(r.name)}
                            title={strings.orgAdmin.deleteCustomRole(r.name)}
                            onClick={() => setConfirmDeleteCustomRole(r)}
                          >
                            <Trash2 />
                          </button>
                        </div>
                      ),
                    },
                  ]}
                />
                {customRoleModalOpen && (
                  // Style guide "Pattern: modal dialog for entity create/rename" (Principle 3): a role's full field set, new or edited, is not detail about
                  // anything already showing.
                  <Modal
                    title={editingCustomRoleId ? strings.orgAdmin.editCustomRoleModalTitle : strings.orgAdmin.newCustomRole}
                    onClose={closeCustomRoleModal}
                    size="lg"
                  >
                    <div className="stack">
                      <FormGrid minColumn="18rem">
                        {!editingCustomRoleId && customRolePresets.length > 0 && (
                          <FormGridFull>
                            <LabeledSelect help={strings.help.customRolePreset}
                              label={strings.orgAdmin.customRolePreset}
                              value=""
                              onChange={applyCustomRolePreset}
                              options={customRolePresets.map((p) => ({ value: p.key, label: p.name }))}
                              placeholder={strings.orgAdmin.customRolePresetNone}
                            />
                          </FormGridFull>
                        )}
                        <TextField helpNotNeeded required
                          label={strings.orgAdmin.customRoleName}
                          value={customRoleFormName}
                          onChange={setCustomRoleFormName}
                          inputProps={{ autoFocus: true }}
                        />
                        <LabeledSelect help={strings.help.customRoleScope}
                          label={strings.orgAdmin.customRoleScope}
                          value={customRoleFormScope}
                          onChange={setCustomRoleFormScope}
                          placeholder={null}
                          options={[
                            { value: "org", label: strings.orgAdmin.customRoleScopeOrg },
                            { value: "project", label: strings.orgAdmin.customRoleScopeProject },
                            // Fine-Grained Access Control (core): every registered module-owned entity scope,
                            // rendered generically rather than a hardcoded per-module option.
                            ...entityScopes.map((s) => ({ value: s.key, label: s.label })),
                          ]}
                        />
                        <FormGridFull>
                          <TextField helpNotNeeded
                            label={strings.orgAdmin.customRoleDescription}
                            value={customRoleFormDescription}
                            onChange={setCustomRoleFormDescription}
                          />
                        </FormGridFull>
                        <FormGridFull>
                          <div className="stack" style={{ gap: "var(--space-1)" }}>
                            <span>{strings.orgAdmin.customRolePermissionsLabel}</span>
                            <PermissionPicker
                              permissions={permissions}
                              selected={customRoleFormPermissions}
                              onChange={setCustomRoleFormPermissions}
                              disabled={customRoleFormSaving}
                            />
                          </div>
                        </FormGridFull>
                      </FormGrid>
                      <FormActions
                        error={customRoleFormError}
                        onCancel={closeCustomRoleModal}
                        onSave={saveCustomRole}
                        saveDisabled={!customRoleFormName.trim() || customRoleFormSaving}
                      />
                    </div>
                  </Modal>
                )}
              </CollapsibleSection>
            )}

            {/* Role assignment: ORG_ADMIN or a `grant_roles` holder. Shown to anyone who reaches the page, like the Users table's role controls;
                authorization is enforced server-side (403 + toast), not by hiding the control. */}
            <CollapsibleSection sectionKey="orgAdmin.roleManagement.assignment" collapsible={false} title={strings.orgAdmin.customRoleAssignmentTitle} help={strings.orgAdmin.customRoleAssignmentHint}>
              {customRoles.length === 0 ? (
                <p className="text-muted">{strings.orgAdmin.noCustomRoles}</p>
              ) : (
                <div className="stack">
                  {customRoles.map((role) => {
                    const projectId = customRoleGrantProjectId[role.id] ?? "";
                    const matchingEntityScope = entityScopes.find((s) => s.key === role.scope);
                    const entityId = customRoleGrantEntityId[role.id] ?? "";
                    const canPickTarget =
                      role.scope === "org" || !!projectId || (matchingEntityScope !== undefined && !!entityId);
                    const selectScopeFirstPlaceholder = matchingEntityScope
                      ? strings.orgAdmin.customRoleSelectScopeFirst(matchingEntityScope.label)
                      : strings.orgAdmin.customRoleSelectProjectFirst;
                    return (
                      <div className="card stack" key={role.id} style={{ gap: "var(--space-3)" }}>
                        <div className="row" style={{ justifyContent: "space-between" }}>
                          <strong>{role.name}</strong>
                          <Badge>{customRoleScopeLabel(role.scope)}</Badge>
                        </div>
                        {role.scope === "project" && (
                          <LabeledSelect helpNotNeeded
                            label={strings.orgAdmin.projects}
                            value={projectId}
                            onChange={(next) => setCustomRoleGrantProjectId((prev) => ({ ...prev, [role.id]: next }))}
                            // `orgProjects` (every project in the org) when available — ORG_ADMIN only; a
                            // `grant_roles` holder who isn't an ORG_ADMIN falls back to `thisOrgVisibleProjects`
                            // (their own visible projects) rather than an empty picker.
                            options={(orgProjects ?? thisOrgVisibleProjects).map((p) => ({ value: p.id, label: p.name }))}
                            placeholder={strings.common.selectOption}
                          />
                        )}
                        {/* Fine-Grained Access Control (core): the project picker's generalisation for a role scoped to a registered module-owned entity scope
                            (e.g. compliance's "standard"), populated from that scope's `entities` list. */}
                        {matchingEntityScope !== undefined && (
                          <LabeledSelect helpNotNeeded
                            label={matchingEntityScope.label}
                            value={entityId}
                            onChange={(next) => setCustomRoleGrantEntityId((prev) => ({ ...prev, [role.id]: next }))}
                            options={matchingEntityScope.entities.map((entity) => ({ value: entity.id, label: entity.name }))}
                            placeholder={strings.common.selectOption}
                          />
                        )}
                        <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap" }}>
                          <RecordFieldGroup helpNotNeeded label={strings.orgAdmin.customRoleGrantFieldLabel}>
                            <UserAutocomplete
                              users={users}
                              groups={allGroups}
                              organizationId={orgId}
                              ariaLabel={strings.orgAdmin.customRoleGrantToUserOrGroup(role.name)}
                              placeholder={canPickTarget ? undefined : selectScopeFirstPlaceholder}
                              onSelect={(userId) => {
                                if (!canPickTarget) return;
                                const target = users.find((u) => u.user_id === userId);
                                grantCustomRoleToUserById(role, userId, target?.display_name ?? userId);
                              }}
                              onSelectGroup={(groupId) => {
                                if (!canPickTarget) return;
                                const target = allGroups.find((g) => g.id === groupId);
                                grantCustomRoleToGroupById(role, groupId, target?.name ?? groupId);
                              }}
                            />
                          </RecordFieldGroup>
                          <RecordFieldGroup helpNotNeeded label={strings.orgAdmin.customRoleRevokeFieldLabel}>
                            <UserAutocomplete
                              users={users}
                              groups={allGroups}
                              organizationId={orgId}
                              ariaLabel={strings.orgAdmin.customRoleRevokeFromUserOrGroup(role.name)}
                              placeholder={canPickTarget ? undefined : selectScopeFirstPlaceholder}
                              onSelect={(userId) => {
                                if (!canPickTarget) return;
                                const target = users.find((u) => u.user_id === userId);
                                revokeCustomRoleFromUserById(role, userId, target?.display_name ?? userId);
                              }}
                              onSelectGroup={(groupId) => {
                                if (!canPickTarget) return;
                                const target = allGroups.find((g) => g.id === groupId);
                                revokeCustomRoleFromGroupById(role, groupId, target?.name ?? groupId);
                              }}
                            />
                          </RecordFieldGroup>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CollapsibleSection>
          </div>
        )}

        {/* One generic lookup for every module-contributed org-admin section; a new module's `orgAdminSections` entry needs no edit here. */}
        {moduleAdminSections
          .filter((section) => section.key === activeGroup)
          .map((section) => (
            <div className="stack" key={section.key}>
              {section.render({ orgId: org.id })}
            </div>
          ))}
      </ResourceMenu>

      {resetLinkUser && (
        <SendPasswordResetDialog
          userName={resetLinkUser.display_name}
          endpoint={`/api/v1/orgs/${org.id}/users/${resetLinkUser.user_id}/password-reset`}
          onClose={() => setResetLinkUser(null)}
        />
      )}
      {confirmRemoveUser && (
        <ConfirmDialog
          title={strings.orgAdmin.removeFromOrgConfirmTitle(confirmRemoveUser.display_name)}
          message={strings.orgAdmin.removeFromOrgConfirmMessage(confirmRemoveUser.display_name, orgLabel)}
          confirmLabel={strings.orgAdmin.removeFromOrgConfirmButton}
          onConfirm={() => removeOrgUser(confirmRemoveUser)}
          onCancel={() => setConfirmRemoveUser(null)}
        />
      )}
      {confirmDeleteCustomRole && (
        // Style guide "Pattern: confirmation, in two tiers" (Principle 6): a Tier 1 confirm (no typed name), since a custom role's grants cascade-delete
        // but the role can be recreated, unlike an organisation-destroying action.
        <ConfirmDialog
          title={strings.orgAdmin.confirmDeleteCustomRoleTitle}
          message={strings.orgAdmin.confirmDeleteCustomRoleMessage(confirmDeleteCustomRole.name)}
          confirmLabel={strings.common.delete}
          onConfirm={() => deleteCustomRole(confirmDeleteCustomRole)}
          onCancel={() => setConfirmDeleteCustomRole(null)}
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
      {scimConfirm && (
        <ConfirmDialog
          title={scimConfirm === "regenerate" ? strings.orgAdmin.scimRegenerateTitle : strings.orgAdmin.scimRevokeTitle}
          message={scimConfirm === "regenerate" ? strings.orgAdmin.scimRegenerateConfirm : strings.orgAdmin.scimRevokeConfirm}
          confirmLabel={scimConfirm === "regenerate" ? strings.orgAdmin.scimRegenerate : strings.orgAdmin.scimRevoke}
          onConfirm={() => {
            const action = scimConfirm;
            setScimConfirm(null);
            void (action === "regenerate" ? regenerateScimToken() : revokeScimToken());
          }}
          onCancel={() => setScimConfirm(null)}
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
      {aiApprovalsAckPending && (
        <ConfirmDialog
          title={strings.orgAdmin.allowAiApprovalsAckTitle}
          message={
            <span className="stack" style={{ gap: "var(--space-3)" }}>
              <span>{strings.orgAdmin.allowAiApprovalsAckBody}</span>
              <CheckboxField helpNotNeeded
                label={strings.orgAdmin.allowAiApprovalsAckCheckbox}
                checked={aiApprovalsAckChecked}
                onChange={setAiApprovalsAckChecked}
              />
            </span>
          }
          confirmLabel={strings.orgAdmin.allowAiApprovalsAckConfirm}
          confirmDisabled={!aiApprovalsAckChecked}
          onConfirm={() => {
            advancedDirtyRef.current.security = true;
            setAllowAiApprovals(true);
            setAiApprovalsAckPending(false);
          }}
          onCancel={() => setAiApprovalsAckPending(false)}
        />
      )}
    </div>
  );
}
