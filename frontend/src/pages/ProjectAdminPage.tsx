import { useMutation } from "../hooks/useMutation";
import { usePhaseMove } from "../hooks/usePhaseMove";
import { Download, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type {
  ActionTypeDefinition,
  AssignByEmailOutcome,
  CustomFieldDefinition,
  EffectiveMember,
  MaterializeResult,
  ModuleRoleDefinition,
  OrgGroup,
  OrgGroupProjectRoleSummary,
  Organization,
  OrgUser,
  PendingInvite,
  Project,
  ProjectCodePolicy,
  ProjectGroup,
  ProjectListItem,
  ProjectMemberSource,
  ProjectModuleEnablement,
  PrincipalRef,
  PrincipalUsage,
  ProjectModuleSubComponent,
  ProjectRole,
  ProjectRoleInheritanceMode,
  ProjectStage,
  StageWorkflow,
  ProjectStatusDefinition,
} from "../api/types";
import { CUSTOM_FIELD_TYPE_LABEL, MAX_PROJECT_REPORT_NAME_LENGTH, PROJECT_ROLE_INHERITANCE_MODE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { stagePhaseLabel } from "../utils/stageBadge";
import type { StagedMember } from "../components/AddMembersModal";
import { AddMembersModal } from "../components/AddMembersModal";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { LinkTypesPanel } from "../components/LinkTypesPanel";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Tooltip } from "../components/Tooltip";
import { StageWorkflowEditor, type StageWorkflowValues } from "../components/StageWorkflowEditor";
import { StageWorkflowsPanel } from "../components/StageWorkflowsPanel";
import { ComponentPhasesPanel } from "../components/ComponentPhasesPanel";
import { NavLabelsPanel } from "../components/NavLabelsPanel";
import { ProjectExternalSystemsPanel } from "../components/ExternalSystemsPanels";
import { RecordCodePrefixPanel } from "../components/RecordCodePrefixPanel";
import { StructurePanel } from "../components/StructurePanel";
import { ProjectLifecyclesPanel } from "../components/ProjectLifecyclesPanel";
import { RequirementAliasSettingsPanel } from "../components/RequirementAliasSettingsPanel";
import { PhaseSchedulePanel } from "../components/PhaseSchedulePanel";
import { GroupInUseDialog } from "../components/GroupInUseDialog";
import { ModuleSettingsList } from "../components/ModuleSettingsList";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { DefinitionList } from "../components/DefinitionList";
import { ProjectTagsPanel } from "../components/ProjectTagsPanel";
import { DeleteInUseDialog } from "../components/DeleteInUseDialog";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { FilterPanel } from "../components/FilterPanel";
import { CustomFieldCreateModal, type CustomFieldDraft } from "../components/CustomFieldCreateModal";
import { Modal } from "../components/Modal";
import { StageCreateModal } from "../components/StageCreateModal";
import { MultiSelectDropdown } from "../components/MultiSelectDropdown";
import { ProjectMembersTable } from "../components/ProjectMembersTable";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { SidePanel } from "../components/SidePanel";
import { cycleSort, type SortState } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { useOrgLabel } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { refreshProjectEnabledModules, useProjectEnabledModules } from "../hooks/useProjectEnabledModules";
import type { ProjectAdminSectionDef } from "../modules/types";
import { buildAdminMenuEntries, resolveAdminSection } from "../modules/adminMenu";
import { installedModules } from "../modules/registry";
import { loadProjectSwitcherOptions } from "../utils/entitySwitcherLoaders";
import { describeCodePolicy, normaliseProjectCode } from "../utils/codePolicy";
import { downloadBlob } from "../utils/download";
import { sortRows } from "../utils/sortRows";
import { reportLayoutApi } from "../api/reportLayouts";
import { reportPackApi } from "../api/reportPacks";
import { reportPlacementApi } from "../api/reportPlacements";
import { Badge } from "../components/Badge";
import { ReportSetupPanel } from "../components/ReportSetupPanel";
import { ReportSnippetsPanel } from "../components/ReportSnippetsPanel";
import { CheckboxField, InlineTextInput, TextAreaField, TextField, ToggleField } from "../components/FormFields";
import { InlineSelect, LabeledSelect } from "../components/LabeledSelect";
import { FormActions } from "../components/FormActions";
import { FormDivider, FormGrid, FormGridFull } from "../components/FormGrid";
import { RecordFieldGroup } from "../components/RecordDetailParts";
import { ProjectNestingFields } from "../components/ProjectNestingFields";
import { MODES_NEEDING_CONFIRMATION } from "../utils/projectInheritance";

const TERMINOLOGY_KEYS = ["project", "stage", "component", "category", "requirement", "change_request"] as const;

// The four project roles a group's per-row `MultiSelectDropdown` (Groups tab and the group's `SidePanel`) offers; the same
// list `ProjectMembersTable.tsx`'s Role column iterates for a user.
const PROJECT_GROUP_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder", "member"];

/** The Groups tab's sortable columns. */
type ProjectGroupSortKey = "name" | "type" | "role" | "members";

/** The `sort` value `list_project_groups` takes for each column it orders; Type has none. */
const GROUP_SERVER_SORT_KEY: Partial<Record<ProjectGroupSortKey, string>> = { name: "name", role: "roles", members: "members" };

/**
 * The `ResourceMenu` groups. Each key is the route segment under `/projects/:projectId/admin/:group?` (App.tsx), so a
 * selection is a real navigation; an unrecognised or absent `:group` falls back to "overview". The page uses `ResourceMenu`
 * like the other admin-tier pages (`docs/ux-style-guide.md` Principle 1).
 *
 * "members" is one `ProjectMembersTable` (`components/ProjectMembersTable.tsx`) over `GET /effective-members` provenance, with
 * pending invites as a per-row status; "groups" lists the project groups, each opening a `SidePanel` (docs/decisions.md).
 */
type CoreProjectAdminGroupKey =
  | "overview" | "structure" | "stagesPhases" | "lifecycles" | "fieldsActions" | "members" | "groups" | "reportSetup" | "tags" | "modules";

/** Admits a module-contributed section's key, as `OrgAdminGroupKey` does for `OrgAdminPage.tsx`'s `moduleAdminSections`. */
type ProjectAdminGroupKey = CoreProjectAdminGroupKey | string;

const PROJECT_ADMIN_GROUP_KEYS: CoreProjectAdminGroupKey[] = [
  "overview",
  "structure",
  "stagesPhases",
  "lifecycles",
  "fieldsActions",
  "members",
  "groups",
  "reportSetup",
  "tags",
  "modules",
];

/**
 * Project administration: settings (C-U-13, C-C-03, C-P-01) including the status picked from the organisation's status list,
 * stages/approval (C-G-08, C-G-10), components and categories with ordering (C-G-07, C-E-01/C-E-02), project-scoped action
 * types (project-scoped like custom fields, `docs/decisions.md`) and project groups (C-U-11).
 */
export function ProjectAdminPage() {
  const run = useMutation();
  const strings = useStrings();
  const { projectId, group: groupParam, section: sectionParam } = useParams<{ projectId: string; group?: string; section?: string }>();
  const layoutApi = useMemo(() => (projectId ? reportLayoutApi({ kind: "project", id: projectId }) : null), [projectId]);
  const snippetScope = useMemo(() => ({ kind: "project" as const, id: projectId ?? "" }), [projectId]);
  const packApi = useMemo(() => (projectId ? reportPackApi({ kind: "project", id: projectId }) : null), [projectId]);
  const placementApi = useMemo(() => (projectId ? reportPlacementApi({ kind: "project", id: projectId }) : null), [projectId]);
  const navigate = useNavigate();
  const orgLabel = useOrgLabel();
  const { showToast } = useToast();
  // Installed modules' `projectAdminSections`, filtered to the project's enabled modules (as `OrgAdminPage.tsx`). Computed
  // before `activeGroup` because that fallback must recognise a module-contributed group key.
  const { modules: projectEnabledModules } = useProjectEnabledModules(projectId ?? null);
  const [projectModuleSubComponents, setProjectModuleSubComponents] = useState<Record<string, ProjectModuleSubComponent[]>>({});
  const enabledProjectModuleKeys = new Set(projectEnabledModules.map((m) => m.module_key));
  const moduleAdminSections: ProjectAdminSectionDef[] = installedModules
    .filter((m) => enabledProjectModuleKeys.has(m.key))
    .flatMap((m) => (m.projectAdminSections ?? []).filter((section) => {
      // A section tied to a sub-component is left out once that sub-component is known to be off here.
      const subs = projectModuleSubComponents[m.key];
      return !section.subComponent || !subs || subs.some((s) => s.subcomponent_key === section.subComponent && s.effective_enabled);
    }))
    .filter((section) => {
      const coreKeys = PROJECT_ADMIN_GROUP_KEYS as readonly string[];
      if (coreKeys.includes(section.key) || (section.group && coreKeys.includes(section.group.key))) {
        console.error(`Module-contributed project-admin section "${section.key}" collides with a core group key; ignoring it.`);
        return false;
      }
      return true;
    });
  const adminBasePath = `/projects/${projectId}/admin`;
  const moduleRoute = resolveAdminSection(moduleAdminSections, adminBasePath, groupParam, sectionParam);
  const [project, setProject] = useState<Project | null>(null);
  // The Modules tab: every module's effective whole-module state (`projectModules`) and, for a module with
  // sub-components, the per-sub-component state (`projectModuleSubComponents`, keyed by `module_key`; see `reload()`).
  const [projectModules, setProjectModules] = useState<ProjectModuleEnablement[]>([]);
  const [stages, setStages] = useState<ProjectStage[] | null>(null);
  const [stageWorkflows, setStageWorkflows] = useState<StageWorkflow[]>([]);
  const [newStageWorkflowId, setNewStageWorkflowId] = useState("");
  const [creatingWorkflow, setCreatingWorkflow] = useState(false);
  const [newWorkflowError, setNewWorkflowError] = useState<string | null>(null);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [groupsTotal, setGroupsTotal] = useState(0);
  const [groupSearch, setGroupSearch] = useState("");
  // The Groups `DirectoryTable` is paginated (`list_project_groups` takes `limit`/`offset`), so Name, Role and Members sort is a
  // backend `sort`/`order` refetch, not a client sort of the loaded page (style guide "Pattern: sortable column header"). Type has
  // one value across the groups, so it only places the fully loaded member-source rows before or after them.
  const [groupSort, setGroupSort] = useState<SortState<ProjectGroupSortKey> | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [orgGroups, setOrgGroups] = useState<OrgGroup[]>([]);
  const [orgGroupSelections, setOrgGroupSelections] = useState<Record<string, string>>({});
  const [sourceProjectSelections, setSourceProjectSelections] = useState<Record<string, string>>({});
  // "New group" create `Modal` (style guide "Pattern: modal dialog for entity create/rename") against the project-scoped
  // endpoint. `ProjectGroupCreate` takes no role: a group is created bare and roles are granted afterwards from the row's
  // `MultiSelectDropdown` (`groupsTabColumns`' "role" column).
  const [newGroupModalOpen, setNewGroupModalOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [creatingStage, setCreatingStage] = useState(false);
  const [deadlineInputs, setDeadlineInputs] = useState<Record<string, string>>({});

  // Rename/delete state. Each "edits" map is keyed by item id and filled only once the user types; the input falls back to
  // the item's current name/prefix, so a reload never shows a stale half-typed rename.
  const [stageNameEdits, setStageNameEdits] = useState<Record<string, string>>({});
  const [deletingStageId, setDeletingStageId] = useState<string | null>(null);
  const [structureError, setStructureError] = useState<string | null>(null);

  const [settingsName, setSettingsName] = useState("");
  const [settingsCode, setSettingsCode] = useState("");
  const [codePolicy, setCodePolicy] = useState<ProjectCodePolicy | null>(null);
  // Manual assignment, and not locked for this person (the organisation may lock codes after creation).
  const codeEditable = codePolicy?.assignment === "manual" && !project?.code_change_locked;
  const [settingsSummary, setSettingsSummary] = useState("");
  const [settingsReportName, setSettingsReportName] = useState("");
  const [allowMemberCr, setAllowMemberCr] = useState(true);
  // See `Project.require_change_request_for_approved_links`/`exempt_from_org_link_lock` and
  // `Organization.force_require_change_request_for_approved_links` for the resolution. `orgForceLinksLocked` is
  // best-effort: if the organisation fetch fails it stays false and the project's checkbox is never shown forced.
  const [requireCrForLinks, setRequireCrForLinks] = useState(false);
  const [exemptFromOrgLinkLock, setExemptFromOrgLinkLock] = useState(false);
  const [orgForceLinksLocked, setOrgForceLinksLocked] = useState(false);
  // AI approval via MCP (docs/decisions.md): the project half of the two-level opt-in gate (`Organization.allow_ai_approvals`
  // is the organisation half). Enabling it requires acknowledging the accountability trade-off first.
  const [allowAiApprovals, setAllowAiApprovals] = useState(false);
  const [aiApprovalsAckPending, setAiApprovalsAckPending] = useState(false);
  const [aiApprovalsAckChecked, setAiApprovalsAckChecked] = useState(false);
  const [isTemplate, setIsTemplate] = useState(false);
  const [visibility, setVisibility] = useState<"only_specified" | "org_wide">("only_specified");
  const [statusId, setStatusId] = useState("");
  const [orgProjectStatuses, setOrgProjectStatuses] = useState<ProjectStatusDefinition[]>([]);
  const [terminology, setTerminology] = useState<Record<string, string>>({});
  // Hierarchical projects (docs/decisions.md).
  const [parentProjectId, setParentProjectId] = useState("");
  const [roleInheritanceMode, setRoleInheritanceMode] = useState<ProjectRoleInheritanceMode>("none");
  const [roleInheritanceFilterRole, setRoleInheritanceFilterRole] = useState<ProjectRole>("project_manager");
  // Whether this project may be selected as a parent; off by default, a manager opts in (`Project.can_be_parent`, docs/decisions.md).
  const [canBeParent, setCanBeParent] = useState(false);
  const [pendingInheritMode, setPendingInheritMode] = useState<ProjectRoleInheritanceMode | null>(null);
  const [orgProjects, setOrgProjects] = useState<ProjectListItem[]>([]);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [memberSources, setMemberSources] = useState<ProjectMemberSource[]>([]);
  const [addSourceId, setAddSourceId] = useState("");
  // Member sources may be any same-organisation project and can mirror more than baseline MEMBER: the same
  // mode/filter-role vocabulary as the forward mechanism (`roleInheritanceMode`/`roleInheritanceFilterRole`), in reverse.
  const [addMirrorMode, setAddMirrorMode] = useState<ProjectRoleInheritanceMode>("member_only");
  const [addMirrorFilterRole, setAddMirrorFilterRole] = useState<ProjectRole>("project_manager");
  const [effectiveMembers, setEffectiveMembers] = useState<EffectiveMember[] | null>(null);
  // Organisation groups with a direct `OrgGroupProjectRole` grant on this project, shown as `ProjectMembersTable`'s `kind: "group"` rows.
  const [groupRoles, setGroupRoles] = useState<OrgGroupProjectRoleSummary[]>([]);
  const [materializing, setMaterializing] = useState(false);
  // Module-contributed role definitions available to grant on this project, offered in `ProjectMembersTable`'s Role column
  // beside the four core roles; `[]` until `reload()` resolves or when no module registers roles.
  const [availableModuleRoles, setAvailableModuleRoles] = useState<ModuleRoleDefinition[]>([]);

  // --- Members section --------
  // `ProjectMembersTable`'s two sources, effective members (with provenance) and pending invites, are fetched unpaginated:
  // small enough to load whole and let the shared table search, filter and paginate client-side. `memberTableGroups` is only the
  // Groups section's lookup for a deep-linked `?openGroup=` id that is not on the loaded page (see `openGroupId`).
  const [memberTableGroups, setMemberTableGroups] = useState<ProjectGroup[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);
  const [resendingInviteId, setResendingInviteId] = useState<string | null>(null);
  // Style guide "Pattern: modal dialog for entity create/rename" (Principle 3): the add-member form is behind this button and
  // `Modal`, as the Groups tab's "New group". One button serves users and organisation groups because `UserAutocomplete`
  // matches both (see its module docstring).
  const [addMemberModalOpen, setAddMemberModalOpen] = useState(false);
  // The same autocomplete also matches this project's groups. Picking one grants no role (a group's roles are separate
  // grants); it moves the modal to a second step, "add someone to this group", reusing `addGroupMember`/`addOrgGroupMember`
  // (`POST /{project_id}/groups/{group_id}/members`). `null` means the first step (user or organisation-group search).
  const [addMemberTargetGroup, setAddMemberTargetGroup] = useState<ProjectGroup | null>(null);

  // --- Groups section: per-group SidePanel ---------------------
  // An id, not a boolean, so at most one group's panel is open at a time.
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [deletingGroupId, setDeletingGroupId] = useState<string | null>(null);
  const [inUseGroup, setInUseGroup] = useState<{ id: string; usage: PrincipalUsage } | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // Guards the two field groups above against `reload()`, which runs after every unrelated mutation (33 call sites) and is not
  // awaited: a still-running `reload()` could overwrite the user's edit with the last-saved value before Save (the race
  // OrgAdminPage.tsx's advancedDirtyRef guards; docs/decisions.md). Separate refs because `saveSettings()` and
  // `saveTerminology()` are independent saves.
  const settingsDirtyRef = useRef(false);
  const terminologyDirtyRef = useRef(false);

  // --- Action types (project-scoped, docs/decisions.md) ------------
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);

  const [customFields, setCustomFields] = useState<CustomFieldDefinition[]>([]);
  const [creatingField, setCreatingField] = useState(false);
  const [deletingFieldId, setDeletingFieldId] = useState<string | null>(null);

  const GROUPS_PAGE_SIZE = 20;

  // `reload()` starts `loadGroups` after a long chain of awaits, so a stale, slower response could overwrite a newer filtered
  // one. Each call claims the next id and a response is applied only if no newer call has started. The id is claimed when the
  // caller decides to search (`reload()` claims it up front through the optional `requestId`), not when the request fires:
  // claiming late let an earlier call with an older search term outrank a later explicit search (docs/decisions.md).
  const loadGroupsRequestIdRef = useRef(0);

  async function loadGroups(
    search: string, offset: number, append: boolean, sort: typeof groupSort = groupSort, requestId?: number
  ) {
    if (!projectId) return;
    const id = requestId ?? ++loadGroupsRequestIdRef.current;
    const params = new URLSearchParams({ limit: String(GROUPS_PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    const serverKey = sort ? GROUP_SERVER_SORT_KEY[sort.key] : undefined;
    if (sort && serverKey) {
      params.set("sort", serverKey);
      params.set("order", sort.direction);
    }
    const page = await api.getPage<ProjectGroup>(`/api/v1/projects/${projectId}/groups?${params.toString()}`);
    if (id !== loadGroupsRequestIdRef.current) return;
    setGroups((prev) => (append ? [...prev, ...page.items] : page.items));
    setGroupsTotal(page.total);
  }

  async function reload() {
    if (!projectId) return;
    // Claimed before the long chain of awaits below so the call's place in the ordering reflects when it was invoked
    // (see `loadGroupsRequestIdRef`).
    const groupsRequestId = ++loadGroupsRequestIdRef.current;
    const [p, s, wf, cf, at] = await Promise.all([
      api.get<Project>(`/api/v1/projects/${projectId}`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<StageWorkflow[]>(`/api/v1/projects/${projectId}/stage-workflows`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields`),
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
    ]);
    setProject(p);
    if (!settingsDirtyRef.current) {
      setSettingsName(p.name);
      setSettingsCode(p.code);
      setSettingsSummary(p.summary);
      setSettingsReportName(p.report_name ?? "");
      setAllowMemberCr(p.allow_member_change_requests);
      setRequireCrForLinks(p.require_change_request_for_approved_links);
      setExemptFromOrgLinkLock(p.exempt_from_org_link_lock);
      setAllowAiApprovals(p.allow_ai_approvals);
      setIsTemplate(p.is_template);
      setVisibility(p.visibility);
      setStatusId(p.status_id);
      setParentProjectId(p.parent_project_id ?? "");
      setRoleInheritanceMode(p.role_inheritance_mode);
      if (p.role_inheritance_filter_role) setRoleInheritanceFilterRole(p.role_inheritance_filter_role);
      setCanBeParent(p.can_be_parent);
    }
    if (!terminologyDirtyRef.current) setTerminology(p.terminology);
    setStages(s);
    setStageWorkflows(wf);
    await loadGroups(groupSearch, 0, false, groupSort, groupsRequestId);
    setCustomFields(cf);
    setActionTypes(at);

    // The page's other data sources are independent GETs (keyed on `projectId`/`p.organization_id`), batched into one
    // `Promise.all` so `reload()`, which runs after nearly every mutation, is not a serial network waterfall (docs/decisions.md).
    const [
      orgUsers, orgGroups, orgForOrgSettings, orgProjectStatuses,
      orgProjects, memberSources, memberTableGroups, effectiveMembers, groupRoles,
      pendingInvites, availableModuleRoles, projectModulesLoaded,
    ] = await Promise.all([
      // Group membership stores only user ids; names need the organisation's member directory. Any organisation role can call it
      // unfiltered (`routers/orgs.py::list_org_users`) and project access implies organisation membership.
      api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`),
      api.get<OrgGroup[]>(`/api/v1/orgs/${p.organization_id}/groups`),
      // Readable by any organisation member, so the same "project access implies organisation membership" reasoning applies.
      api.get<Organization>(`/api/v1/orgs/${p.organization_id}`),
      api.get<ProjectStatusDefinition[]>(`/api/v1/orgs/${p.organization_id}/project-statuses`),
      // Hierarchical projects (docs/decisions.md). Parent options are already restricted server-side to the caller's accessible
      // set (`list_projects`); this is the organisation-wide accessible list ProjectListPage's "New project" modal uses.
      api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&organization_id=${p.organization_id}`),
      api.get<ProjectMemberSource[]>(`/api/v1/projects/${projectId}/member-sources`),
      // The Groups section's `?openGroup=` deep-link lookup (unpaginated, no `limit`) and the source of its "last manager" hint
      // (`directRoleManagerSourceCount`), which needs `effectiveMembers` loaded whichever tab is open, so effective members and
      // pending invites are fetched eagerly.
      api.get<ProjectGroup[]>(`/api/v1/projects/${projectId}/groups`),
      api.get<EffectiveMember[]>(`/api/v1/projects/${projectId}/effective-members`),
      api.get<OrgGroupProjectRoleSummary[]>(`/api/v1/projects/${projectId}/group-roles`),
      api.get<PendingInvite[]>(`/api/v1/projects/${projectId}/pending-invites`),
      // Fetched with the rest of `reload()`, like the other Members-section sources above.
      api.get<ModuleRoleDefinition[]>(`/api/v1/projects/${projectId}/module-roles`),
      // The Modules tab's bulk discovery endpoint: every registered module with this project's effective or override state.
      api.get<ProjectModuleEnablement[]>(`/api/v1/projects/${projectId}/modules`),
    ]);
    setOrgUsers(orgUsers);
    setOrgGroups(orgGroups);
    setOrgForceLinksLocked(orgForOrgSettings.force_require_change_request_for_approved_links);
    setCodePolicy(orgForOrgSettings.project_code_policy);
    setOrgProjectStatuses(orgProjectStatuses);
    setOrgProjects(orgProjects);
    setMemberSources(memberSources);
    setMemberTableGroups(memberTableGroups);
    setEffectiveMembers(effectiveMembers);
    setGroupRoles(groupRoles);
    setProjectModules(projectModulesLoaded);
    // Sub-components, one level below the module list: `GET .../subcomponents` returns `[]` for a module with none,
    // so it is called for every module (as Org Admin does).
    const subComponentEntries = await Promise.all(
      projectModulesLoaded.map(async (m) => [
        m.module_key,
        await api.get<ProjectModuleSubComponent[]>(
          `/api/v1/projects/${projectId}/modules/${m.module_key}/subcomponents`,
        ),
      ] as const),
    );
    setProjectModuleSubComponents(Object.fromEntries(subComponentEntries));
    setPendingInvites(pendingInvites);
    setAvailableModuleRoles(availableModuleRoles);
  }

  const stageMove = usePhaseMove(
    { title: strings.admin.completeStage, cascade: strings.admin.cascadeToRequirements, cascadeHelp: strings.help.cascadeToRequirementsStage },
    "move", () => void reload(),
  );

  // A whole-module enablement change cascades into the sub-components' effective state (whole-module-disabled always wins,
  // `is_module_subcomponent_enabled`), so it is re-fetched after either mutation below instead of waiting for `reload()`.
  async function refreshProjectModuleSubComponents(moduleKey: string) {
    const subs = await api.get<ProjectModuleSubComponent[]>(
      `/api/v1/projects/${projectId}/modules/${moduleKey}/subcomponents`,
    );
    setProjectModuleSubComponents((prev) => ({ ...prev, [moduleKey]: subs }));
  }

  // This project's whole-module enablement override: an immediate PUT plus a local-state patch, as `toggleModuleEnabled` in
  // `OrgAdminPage.tsx` one tier up; a toggle changes only this module's row.
  async function toggleProjectModuleEnabled(moduleKey: string, enabled: boolean) {
    try {
      const updated = await api.put<ProjectModuleEnablement>(
        `/api/v1/projects/${projectId}/modules/${moduleKey}/enablement`, { enabled },
      );
      setProjectModules((prev) => prev.map((m) => (m.module_key === moduleKey ? updated : m)));
      if (projectId) refreshProjectEnabledModules(projectId);
      await refreshProjectModuleSubComponents(moduleKey);
      showToast(enabled ? strings.admin.moduleEnabledToast(updated.name) : strings.admin.moduleDisabledToast(updated.name));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function toggleProjectSubComponentEnabled(moduleKey: string, subcomponentKey: string, enabled: boolean) {
    try {
      const updated = await api.put<ProjectModuleSubComponent>(
        `/api/v1/projects/${projectId}/modules/${moduleKey}/subcomponents/${subcomponentKey}`, { enabled },
      );
      setProjectModuleSubComponents((prev) => ({
        ...prev,
        [moduleKey]: (prev[moduleKey] ?? []).map((s) => (s.subcomponent_key === subcomponentKey ? updated : s)),
      }));
      if (projectId) refreshProjectEnabledModules(projectId);
      showToast(
        enabled
          ? strings.admin.moduleSubComponentEnabledToast(updated.name)
          : strings.admin.moduleSubComponentDisabledToast(updated.name),
      );
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function reloadEffectiveMembers() {
    if (!projectId) return;
    setEffectiveMembers(await api.get<EffectiveMember[]>(`/api/v1/projects/${projectId}/effective-members`));
  }

  /** `ProjectMembersTable`'s third data source, re-fetched on its own like `reloadEffectiveMembers`; called from `reload()` and after
   * every group-role mutation. */
  async function reloadGroupRoles() {
    if (!projectId) return;
    setGroupRoles(await api.get<OrgGroupProjectRoleSummary[]>(`/api/v1/projects/${projectId}/group-roles`));
  }

  async function reloadPendingInvites() {
    if (!projectId) return;
    setPendingInvites(await api.get<PendingInvite[]>(`/api/v1/projects/${projectId}/pending-invites`));
  }

  async function resendProjectInvite(invite: PendingInvite) {
    if (!projectId) return;
    setResendingInviteId(invite.id);
    try {
      await api.post(`/api/v1/projects/${projectId}/pending-invites/${invite.id}/resend`);
      showToast(strings.admin.resendInviteSuccess(invite.email));
      await reloadPendingInvites();
    } catch (err) {
      showToast(toErrorMessage(err, strings.admin.resendInviteError), "error");
    } finally {
      setResendingInviteId(null);
    }
  }

  /** Creates a custom field from the dialog's draft; resolves true when it exists (failure is toasted by `run`). */
  async function addCustomField(draft: CustomFieldDraft): Promise<boolean> {
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/custom-fields`, {
      entity_kind: draft.entityKind,
      name: draft.name,
      field_type: draft.fieldType,
      options: draft.fieldType === "list" ? draft.options.split(",").map((s) => s.trim()).filter(Boolean) : null,
      required: draft.required,
    }), "add", "custom field"))) return false;
    reload();
    return true;
  }

  async function deleteCustomField(fieldId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/custom-fields/${fieldId}`), "delete", "custom field"))) return;
    reload();
  }

  async function saveSettings() {
    setSettingsError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}`, {
        name: settingsName, summary: settingsSummary, report_name: settingsReportName.trim() || null,
        ...(codeEditable && settingsCode !== project?.code ? { code: normaliseProjectCode(settingsCode) } : {}),
        allow_member_change_requests: allowMemberCr,
        // `requireCrForLinks` always carries the project's stored opt-in, even while the organisation force renders the checkbox
        // checked and disabled; the stored value stays what it was if the organisation later lifts the force.
        require_change_request_for_approved_links: requireCrForLinks,
        exempt_from_org_link_lock: exemptFromOrgLinkLock,
        allow_ai_approvals: allowAiApprovals,
        is_template: isTemplate,
        visibility, status_id: statusId || null,
        parent_project_id: parentProjectId || null,
        role_inheritance_mode: roleInheritanceMode,
        role_inheritance_filter_role: roleInheritanceMode === "mirror_role" ? roleInheritanceFilterRole : null,
        can_be_parent: canBeParent,
      });
      settingsDirtyRef.current = false;
      showToast(strings.mutation.success("{project} settings", strings.mutation.past.save));
      reload();
    } catch (err) {
      // Surfaces the C-U-08 ("only manager is inherited") and parent_required ("must remain nested under a parent") 400s from
      // update_project inline, like the form's other save-time validation.
      setSettingsError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  function requestInheritModeChange(mode: ProjectRoleInheritanceMode) {
    settingsDirtyRef.current = true;
    if (MODES_NEEDING_CONFIRMATION.includes(mode)) {
      setPendingInheritMode(mode);
    } else {
      setRoleInheritanceMode(mode);
    }
  }

  // Gated by can_be_parent (docs/decisions.md), but the currently attached parent stays selectable even if its eligibility
  // was turned off, so an established relationship never shows as blank.
  const parentOptions = orgProjects.filter(
    (p) => !p.is_archived && p.id !== projectId && (p.can_be_parent || p.id === parentProjectId),
  );
  const selectedParent = orgProjects.find((p) => p.id === parentProjectId);
  // Nothing to show: no eligible candidate and no current parent (a field with nothing meaningful is not rendered;
  // docs/decisions.md visibility-boundary rule).
  const showParentField = parentOptions.length > 0 || parentProjectId !== "";
  // Any other project in the organisation is a valid source, not only a direct child (docs/decisions.md); `orgProjects` is
  // the full organisation project list used for the parent picker.
  const sourceCandidates = orgProjects.filter(
    (p) => !p.is_archived && p.id !== projectId && !memberSources.some((ms) => ms.source_project_id === p.id),
  );

  async function addMemberSource() {
    if (!addSourceId) return;
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/member-sources`, {
      source_project_id: addSourceId, mirror_mode: addMirrorMode,
      mirror_filter_role: addMirrorMode === "mirror_role" ? addMirrorFilterRole : null,
    }), "add", "member source"))) return;
    setAddSourceId("");
    setAddMirrorMode("member_only");
    reload();
  }

  async function removeMemberSource(sourceProjectId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/member-sources/${sourceProjectId}`), "remove", "member source"))) return;
    reload();
  }

  async function materializeInheritedAccess() {
    setMaterializing(true);
    try {
      const result = await api.post<MaterializeResult>(`/api/v1/projects/${projectId}/materialize-inherited-access`);
      showToast(strings.admin.materializedCount(result.created.length));
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setMaterializing(false);
    }
  }

  async function saveTerminology() {
    if (!(await run(() => api.put(`/api/v1/projects/${projectId}/terminology`, { terminology }), "save", "terminology"))) return;
    terminologyDirtyRef.current = false;
    reload();
  }

  async function toggleArchive() {
    const action = project?.is_archived ? "unarchive" : "archive";
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/${action}`), {
      success: action === "archive" ? "Project archived." : "Project restored.",
      failure: `Could not ${action} the project.`,
    }))) return;
    reload();
  }

  const [exporting, setExporting] = useState(false);

  async function exportProject() {
    if (!projectId || !project) return;
    setExporting(true);
    try {
      const blob = await api.getForBlob(`/api/v1/projects/${projectId}/export`);
      const safeName = project.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${safeName}-export.zip`);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    // Documented false positive: every setState in `reload()` runs after its first `await`, so none is synchronous in this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  /** Creates a project workflow from the editor opened over the new-stage dialog and selects it for the new stage. */
  async function saveNewWorkflow(values: StageWorkflowValues) {
    setNewWorkflowError(null);
    try {
      const created = await api.post<StageWorkflow>(`/api/v1/projects/${projectId}/stage-workflows`, values);
      setNewStageWorkflowId(created.id);
    } catch (err) {
      setNewWorkflowError(toErrorMessage(err, strings.mutation.failure("save", strings.stageWorkflows.nounSingular)));
      return;
    }
    setCreatingWorkflow(false);
    reload();
  }

  /** Creates a stage from the dialog; resolves true when it exists (failure is toasted by `run`). */
  async function addStage(name: string, workflowId: string): Promise<boolean> {
    if (!name.trim()) return false;
    const body = { name, workflow_id: workflowId || undefined };
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/stages`, body), "add", "{stage}"))) return false;
    reload();
    return true;
  }

  /** Moves a stage to a phase of its workflow; a closed phase first asks whether to complete its requirements. */
  function requestStageMove(stage: ProjectStage, phaseId: string) {
    const phase = stageWorkflows.find((w) => w.id === stage.workflow_id)?.phases.find((p) => p.id === phaseId);
    if (!phase || phase.id === stage.phase_id) return;
    stageMove.requestMove({ path: `/api/v1/projects/${projectId}/stages/${stage.id}/transition`, phase, noun: "{stage}" });
  }

  async function changeStageWorkflow(stage: ProjectStage, workflowId: string) {
    if (!workflowId || workflowId === stage.workflow_id) return;
    if (!(await run(() => api.patch(`/api/v1/projects/${projectId}/stages/${stage.id}`, { name: stage.name, workflow_id: workflowId }), "change", "{stage} workflow"))) return;
    reload();
  }

  async function setReviewDeadline(stageId: string, isoDeadline: string) {
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-deadline`, {
      review_deadline: isoDeadline || null,
    }), "set", "review deadline"))) return;
    reload();
  }

  async function respondToStageReview(stageId: string, response: "approved" | "rejected") {
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-response`, { response }), "respond", "{stage} review"))) return;
    reload();
  }

  async function renameStage(stageId: string, name: string) {
    setStructureError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}/stages/${stageId}`, { name });
      setStageNameEdits((m) => {
        const next = { ...m };
        delete next[stageId];
        return next;
      });
      showToast(strings.mutation.success("{stage}", strings.mutation.past.rename));
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  /** Deletes a stage, moving everything targeting it to `reassignTo`. Throws on failure so
   * `DeleteInUseDialog` can show the error in place. */
  async function deleteStage(stageId: string, reassignTo: string) {
    await api.delete(`/api/v1/projects/${projectId}/stages/${stageId}?reassign_to=${reassignTo}`);
    showToast(strings.mutation.success("{stage}", strings.mutation.past.delete));
    reload();
  }

  async function addActionType(name: string) {
    await api.post(`/api/v1/projects/${projectId}/action-types`, { name });
    showToast(strings.mutation.success("action type", strings.mutation.past.add));
    reload();
  }

  async function moveActionType(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/action-types/${id}/move`, { direction });
    reload();
  }

  async function renameActionType(id: string, name: string) {
    await api.patch(`/api/v1/projects/${projectId}/action-types/${id}`, { name });
    showToast(strings.mutation.success("action type", strings.mutation.past.rename));
    reload();
  }

  /** Plain delete first (no `reassign_to_id`, §4.0's shared contract); a 409 means it is in use and `DefinitionList` opens the
   * reassignment picker with the server's count message (as OrgAdminPage's project-statuses/link-types delete). */
  async function deleteActionType(id: string, reassignToId?: string) {
    await api.delete(`/api/v1/projects/${projectId}/action-types/${id}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`);
    showToast(strings.mutation.success("action type", strings.mutation.past.delete));
    reload();
  }

  /** Creates a project group named `newGroupName` (`POST /projects/{id}/groups`); a group is created with no role. */
  function handleGroupSearchChange(value: string) {
    setGroupSearch(value);
    loadGroups(value, 0, false);
  }

  /** Backend-sorted refetch (see `groupSort`). */
  function applyGroupSort(key: ProjectGroupSortKey) {
    const next = cycleSort(groupSort, key);
    setGroupSort(next);
    loadGroups(groupSearch, 0, false, next);
  }

  async function createProjectGroup() {
    try {
      await api.post(`/api/v1/projects/${projectId}/groups`, { name: newGroupName });
      setNewGroupName("");
      setNewGroupModalOpen(false);
      showToast(strings.admin.groupCreated);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Grants or revokes one role on a project group; the row's `MultiSelectDropdown` and the group's `SidePanel` role editor
   * both call it, because a group can hold zero, one or several independently revocable roles. Re-fetches both group lists
   * on success, as `addGroupMember`/`removeGroupMember` do through `reload()`. */
  async function toggleProjectGroupRole(groupId: string, role: ProjectRole, checked: boolean) {
    try {
      if (checked) {
        await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/roles`, { role });
      } else {
        await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/roles/${role}`);
      }
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function addGroupMember(groupId: string, userId: string) {
    await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { user_id: userId });
    reload();
  }

  const [externalAddResult, setExternalAddResult] = useState<{ message: string; isError: boolean } | null>(null);

  /** Adds someone found by `UserAutocomplete`'s external search (not yet a member of the organisation, possibly with no account)
   * directly to the project with `role`: the by-email counterpart to `addGroupMember`. It grants a direct project role, not group
   * membership; from a group's `SidePanel` one of its held roles approximates the access (inexact for a multi-role group),
   * since `routers/projects.py::assign_project_role_by_email` grants a single role per call. */
  async function addExternalMember(email: string, role: string, options?: { rethrow?: boolean }) {
    setExternalAddResult(null);
    try {
      const result = await api.post<{ outcome: AssignByEmailOutcome }>(
        `/api/v1/projects/${projectId}/roles/by-email`,
        { email, role },
      );
      const messages: Record<AssignByEmailOutcome, (email: string, role: string, org: string) => string> = {
        added: strings.admin.externalAddedDirectly,
        invited: strings.admin.externalInvited,
        sso_provisioned: strings.admin.externalSsoProvisioned,
      };
      setExternalAddResult({
        message: messages[result.outcome](email, role, orgLabel),
        isError: false,
      });
      reload();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : strings.admin.externalAddError;
      setExternalAddResult({ message, isError: true });
      // `AddMembersModal` (`handleAddMembersEntry`) passes `{ rethrow: true }` so a failed invite shows on its own staged row, not
      // only in this shared banner (its `onAddEntry` contract). The original error is rethrown as-is, keeping type, stack and
      // cause; `AddMembersModal` falls back to a generic message for a non-`Error`. The Groups tab's quick-add-external control
      // does not pass `rethrow` and keeps the banner only.
      if (options?.rethrow) throw err;
    }
  }

  async function removeGroupMember(groupId: string, userId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${userId}`), "remove", "group member"))) return;
    reload();
  }

  async function addOrgGroupMember(groupId: string, orgGroupId: string) {
    await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { org_group_id: orgGroupId });
    setOrgGroupSelections((prev) => ({ ...prev, [groupId]: "" }));
    reload();
  }

  async function removeOrgGroupMember(groupId: string, orgGroupId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${orgGroupId}`), "remove", "org group member"))) return;
    reload();
  }

  // "This group's members = that project's direct members" (`models.project.ProjectGroupMember.source_project_id`). Authorised
  // by managing this project alone, like every group-membership mutation here; the referenced project's consent is not needed.
  async function addProjectRefMember(groupId: string, sourceProjectId: string) {
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { source_project_id: sourceProjectId }), "add", "member source"))) return;
    setSourceProjectSelections((prev) => ({ ...prev, [groupId]: "" }));
    reload();
  }

  async function removeProjectRefMember(groupId: string, sourceProjectId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${sourceProjectId}`), "remove", "member source"))) return;
    reload();
  }

  // --- Members section handlers (docs/decisions.md) ---------------------

  /** Toggles one direct role on an effective member (`ProjectMembersTable`'s `onToggleRole`, called only for an option whose
   * sole source is `direct_role`). Re-fetches just `effective-members`, which recomputes the member's `sources` and every other
   * member's "last manager" hint in one request instead of patching local state. */
  async function toggleProjectMemberRole(userId: string, role: ProjectRole, checked: boolean) {
    try {
      if (checked) {
        await api.post(`/api/v1/projects/${projectId}/roles`, { user_id: userId, role });
      } else {
        await api.delete(`/api/v1/projects/${projectId}/roles/${userId}/${role}`);
      }
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s `onToggleModuleRole`: re-fetches just effective-members like `toggleProjectMemberRole`; always
   * callable, since module roles are direct-grant-only. */
  async function toggleProjectMemberModuleRole(userId: string, moduleKey: string, roleKey: string, grant: boolean) {
    try {
      if (grant) {
        await api.post(`/api/v1/projects/${projectId}/members/${userId}/module-roles`, {
          module_key: moduleKey, role_key: roleKey,
        });
      } else {
        await api.delete(`/api/v1/projects/${projectId}/members/${userId}/module-roles/${moduleKey}/${roleKey}`);
      }
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** Grants a new direct role from the Members section's `AddMembersModal` (an existing organisation member). The external-invite
   * branch reuses `addExternalMember`, which also grants a direct role. The caller reloads: `onCommitted` fires once per commit
   * (`handleAddMembersCommitted`). */
  async function addProjectMember(userId: string, role: ProjectRole) {
    await api.post(`/api/v1/projects/${projectId}/roles`, { user_id: userId, role });
  }

  /** The Members section's group branch: `UserAutocomplete` calls this instead of `addProjectMember` when the match is an
   * organisation group, granting `role` directly (`OrgGroupProjectRole`), as `addProjectMember` grants a `UserProjectRole`. No
   * `ProjectGroup` wrapper is created; nesting stays on the per-group `SidePanel`. Reloading is left to
   * `handleAddMembersCommitted`. */
  async function addProjectGroupRole(orgGroupId: string, role: ProjectRole) {
    await api.post(`/api/v1/projects/${projectId}/group-roles`, { org_group_id: orgGroupId, role });
  }

  /** `AddMembersModal`'s `onAddEntry`: dispatches a staged entry to the handler for its `kind`. The external branch rethrows on
   * failure so a failed invite shows on its own staged row. */
  async function handleAddMembersEntry(entry: StagedMember) {
    if (entry.kind === "user") await addProjectMember(entry.id, entry.role);
    else if (entry.kind === "group") await addProjectGroupRole(entry.id, entry.role);
    else await addExternalMember(entry.id, entry.role, { rethrow: true });
  }

  /** `AddMembersModal`'s `onCommitted`: fires once per commit pass and re-fetches effective members and group roles (a newly
   * granted group needs its `ProjectMembersTable` row). `addExternalMember` also calls `reload()`, a harmless extra refresh. */
  async function handleAddMembersCommitted() {
    await reloadEffectiveMembers();
    await reloadGroupRoles();
  }

  /** `ProjectMembersTable`'s `onToggleGroupRole`: grants or revokes one role on a `kind: "group"` row through the `POST`/`DELETE
   * .../group-roles[...]` calls. Re-fetches group roles and effective members, since a role change also changes the members'
   * Source provenance. */
  async function toggleProjectMemberOrgGroupRole(orgGroupId: string, role: ProjectRole, checked: boolean) {
    try {
      if (checked) {
        await api.post(`/api/v1/projects/${projectId}/group-roles`, { org_group_id: orgGroupId, role });
      } else {
        await api.delete(`/api/v1/projects/${projectId}/group-roles/${orgGroupId}/${role}`);
      }
      await reloadGroupRoles();
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s "Remove group": loops `DELETE .../group-roles/{org_group_id}/{role}` over every role the group holds
   * (as `removeAllProjectMemberAccess` does per user); the table confirms through `ConfirmDialog` first. */
  async function removeProjectMemberOrgGroup(orgGroupId: string) {
    const group = groupRoles.find((g) => g.org_group_id === orgGroupId);
    if (!group) return;
    try {
      await Promise.all(
        group.roles.map((role) => api.delete(`/api/v1/projects/${projectId}/group-roles/${orgGroupId}/${role}`))
      );
      showToast(strings.membersTable.removeGroupSuccess(group.org_group_name));
      await reloadGroupRoles();
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s "Remove all access" (Actions column): called only for a member whose sources are all `direct_role`,
   * so looping `DELETE /roles/{user_id}/{role}` over the member's roles is a full revocation; the table confirms first. */
  async function removeAllProjectMemberAccess(userId: string) {
    const member = effectiveMembers?.find((m) => m.user_id === userId);
    if (!member) return;
    try {
      const roles = [...new Set(member.sources.map((s) => s.role))];
      await Promise.all(roles.map((role) => api.delete(`/api/v1/projects/${projectId}/roles/${userId}/${role}`)));
      showToast(strings.membersTable.removeAllAccessSuccess(member.display_name));
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** `ProjectMembersTable`'s "Convert inherited access to direct roles": the per-user counterpart to `materializeInheritedAccess`,
   * calling `POST /{project_id}/materialize-inherited-access/{user_id}` (same idempotency and rank logic) for one member. */
  async function convertProjectMemberToDirect(userId: string) {
    const member = effectiveMembers?.find((m) => m.user_id === userId);
    try {
      const result = await api.post<MaterializeResult>(
        `/api/v1/projects/${projectId}/materialize-inherited-access/${userId}`
      );
      const name = member?.display_name ?? "";
      showToast(
        result.created.length > 0
          ? strings.membersTable.convertToDirectSuccess(name)
          : strings.membersTable.convertToDirectNoOp(name)
      );
      await reloadEffectiveMembers();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // The "last manager" hint `ProjectMembersTable` computes from its `members` prop, recomputed here because the per-group
  // `SidePanel` role `<select>` needs the count for its disabled state: every project-manager-role group plus every
  // direct-role project-manager grant.
  const groupManagerSourceCount =
    memberTableGroups.filter((g) => g.roles.includes("project_manager")).length +
    (effectiveMembers ?? []).filter((m) => m.sources.some((s) => s.role === "project_manager" && s.kind === "direct_role")).length;

  // Groups: Overview (with Terminology as a sub-block), Structure (stages, components, categories), Fields & Actions (custom
  // fields, action types), Members, Groups and Report Setup (docs/decisions.md).
  // The active entry is a core group key or a module section key; the menu opens the group holding a section.
  const activeGroup: ProjectAdminGroupKey = moduleRoute.section
    ? moduleRoute.section.key
    : (PROJECT_ADMIN_GROUP_KEYS as readonly string[]).includes(groupParam ?? "")
      ? (groupParam as ProjectAdminGroupKey)
      : "overview";

  // --- Groups section: per-group SidePanel + ?openGroup= deep link -------
  // (docs/decisions.md) "click a group in Members, see its members" is a URL, not client state. `memberTableGroups`
  // (unpaginated) is searched first so a deep-linked group not on the loaded page is still found.
  const openGroupParam = activeGroup === "groups" ? searchParams.get("openGroup") : null;
  // The deep link is consumed once: opening the panel is derived state (set while rendering, guarded by the
  // last param seen, per React's "adjusting state when a prop changes"), and the effect below only strips the
  // param from the URL so closing the panel does not reopen it.
  const [seenOpenGroupParam, setSeenOpenGroupParam] = useState<string | null>(null);
  if (openGroupParam !== seenOpenGroupParam && (openGroupParam || seenOpenGroupParam)) {
    setSeenOpenGroupParam(openGroupParam);
    if (openGroupParam) setOpenGroupId(openGroupParam);
  }
  useEffect(() => {
    if (!openGroupParam) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("openGroup");
      return next;
    }, { replace: true });
  }, [openGroupParam, setSearchParams]);

  async function deleteGroup(groupId: string, replacement?: PrincipalRef, clearOptional = false) {
    const query = new URLSearchParams();
    if (replacement) {
      query.set("replacement_type", replacement.type);
      query.set("replacement_id", replacement.id);
    }
    if (clearOptional) query.set("clear_optional", "true");
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    try {
      await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}${suffix}`);
      setDeletingGroupId(null);
      setInUseGroup(null);
      if (openGroupId === groupId) setOpenGroupId(null);
      showToast(strings.admin.groupDeleted);
      reload();
    } catch (err) {
      setDeletingGroupId(null);
      // From the in-use dialog: let it show the error itself.
      if (replacement || clearOptional) throw err;
      // Records still name the group: show what, and offer to hand them over (or clear them).
      if (err instanceof ApiError && err.status === 409) {
        try {
          const usage = await api.get<PrincipalUsage>(`/api/v1/projects/${projectId}/groups/${groupId}/usage`);
          if (usage.total > 0) {
            setInUseGroup({ id: groupId, usage });
            return;
          }
        } catch {
          // Fall through to the plain error toast.
        }
      }
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (!stages || !project) return <Spinner />;

  // Project Groups `DirectoryTable`: `groups` is already sorted server-side (`applyGroupSort`/`loadGroups`' `order`), so no
  // client re-sort. Rows are a frontend `kind`-discriminated union, as in `ProjectMembersTable.tsx`: a `ProjectGroup` beside a
  // `ProjectMemberSource`, a different mechanism that is shown here as a type-badged mixed row (docs/ux-style-guide.md
  // "Pattern: type-badged mixed rows in a single directory"). Member-source rows are a fixed, fully loaded set and render first,
  // so "Load more" only appends groups. A member-source row is read-only detail (mirror mode/filter role, a Remove action) and
  // has no "click to open" affordance.
  type GroupsTabRow = { kind: "group"; group: ProjectGroup } | { kind: "member_source"; source: ProjectMemberSource };
  const memberSourceLabel = (source: ProjectMemberSource) =>
    source.mirror_mode === "mirror_role" && source.mirror_filter_role
      ? strings.admin.memberSourceModeRole(PROJECT_ROLE_LABEL[source.mirror_filter_role])
      : PROJECT_ROLE_INHERITANCE_MODE_LABEL[source.mirror_mode];
  // The member-source rows are fully loaded, so the page orders them by the active column, by the text each cell shows; the groups
  // arrive in the server's order. They precede the groups, except that a descending Type sort places them after the loaded groups
  // ("{Project} group" follows "{Project}" in ascending order).
  const memberSourceRows = sortRows(
    memberSources.map((source): GroupsTabRow => ({ kind: "member_source", source })),
    groupSort,
    {
      name: (row) => (row.kind === "member_source" ? row.source.source_project_name : null),
      type: (row) => (row.kind === "member_source" ? strings.admin.groupTypeBadgeMemberSource : null),
      role: (row) => (row.kind === "member_source" ? memberSourceLabel(row.source) : null),
      members: () => null,
    },
  );
  const groupRows = groups.map((group): GroupsTabRow => ({ kind: "group", group }));
  const sourcesAfterGroups = groupSort?.key === "type" && groupSort.direction === "desc";
  const groupsTabRows: GroupsTabRow[] = sourcesAfterGroups ? [...groupRows, ...memberSourceRows] : [...memberSourceRows, ...groupRows];
  const groupsTabColumns: DirectoryColumn<GroupsTabRow>[] = [
    {
      key: "name", label: strings.admin.name, sortable: true,
      render: (row) => (row.kind === "group" ? row.group.name : row.source.source_project_name),
    },
    {
      key: "type", label: strings.admin.groupTypeColumn, sortable: true,
      render: (row) => (
        <Badge>
          {row.kind === "group" ? strings.admin.groupTypeBadgeGroup : strings.admin.groupTypeBadgeMemberSource}
        </Badge>
      ),
    },
    {
      key: "role", label: strings.admin.groupRole, sortable: true,
      render: (row) =>
        row.kind === "group" ? (
          // A group's role is a MultiSelectDropdown over zero to several independently revocable grants, like `ProjectMembersTable`'s Role column.
          <MultiSelectDropdown
            triggerLabel={strings.admin.groupRolesFor(row.group.name)}
            emptyLabel={strings.admin.noRolesAssigned}
            options={PROJECT_GROUP_ROLES.map((role) => {
              const checked = row.group.roles.includes(role);
              const isLastManager = checked && role === "project_manager" && groupManagerSourceCount <= 1;
              return {
                value: role,
                label: PROJECT_ROLE_LABEL[role],
                checked,
                disabled: isLastManager,
                title: isLastManager ? strings.membersTable.cannotRemoveLastManager : undefined,
                optionLabel: checked
                  ? strings.membersTable.revokeRole(PROJECT_ROLE_LABEL[role], row.group.name)
                  : strings.membersTable.grantRole(PROJECT_ROLE_LABEL[role], row.group.name),
                onToggle: () => toggleProjectGroupRole(row.group.id, role, !checked),
              };
            })}
          />
        ) : (
          <Badge>
            {memberSourceLabel(row.source)}
          </Badge>
        ),
    },
    {
      key: "members", label: strings.admin.groupMembersColumn, sortable: true,
      render: (row) =>
        row.kind === "group" ? strings.admin.memberCount(row.group.member_user_ids.length) : <span className="text-muted">—</span>,
    },
    {
      key: "actions", label: "",
      render: (row) =>
        row.kind === "member_source" ? (
          <button className="btn" onClick={() => removeMemberSource(row.source.source_project_id)}>
            {strings.admin.removeMemberSource}
          </button>
        ) : null,
    },
  ];

  // The title is rendered by the header row below, not `ResourceMenu`'s `title` prop: this page has other chrome beside the h1
  // (the "Add sub-project" button), so passing `project.name` to `ResourceMenu` too would duplicate it.
  const projectAdminGroups: ResourceMenuGroupDef<ProjectAdminGroupKey>[] = [
    { key: "overview", label: strings.admin.settings, href: `/projects/${projectId}/admin/overview` },
    { key: "structure", label: strings.admin.structure, href: `/projects/${projectId}/admin/structure` },
    { key: "stagesPhases", label: strings.admin.stagesPhases, href: `/projects/${projectId}/admin/stagesPhases` },
    { key: "lifecycles", label: strings.admin.lifecyclesNav, href: `/projects/${projectId}/admin/lifecycles` },
    { key: "fieldsActions", label: strings.admin.fieldsAndActions, href: `/projects/${projectId}/admin/fieldsActions` },
    { key: "members", label: strings.admin.membersNav, href: `/projects/${projectId}/admin/members` },
    { key: "groups", label: strings.admin.groups, href: `/projects/${projectId}/admin/groups` },
    { key: "reportSetup", label: strings.admin.reportSetup, href: `/projects/${projectId}/admin/reportSetup` },
    { key: "tags", label: strings.admin.tagsNav, href: `/projects/${projectId}/admin/tags` },
    { key: "modules", label: strings.admin.modulesNav, href: `/projects/${projectId}/admin/modules` },
    ...buildAdminMenuEntries(moduleAdminSections, adminBasePath),
  ];

  // An earlier or partial module address (`/admin/<section>`, `/admin/<group>`) is replaced by the current one.
  if (moduleRoute.redirectTo) return <Navigate to={moduleRoute.redirectTo} replace />;

  // Unavailable until this project has opted in to being a parent; its explanation is a tooltip on the button.
  const addSubProjectButton = (
    <button
      className="btn"
      disabled={!project.can_be_parent}
      onClick={() => navigate(`/projects?parentProjectId=${project.id}&organizationId=${project.organization_id}`)}
    >
      <Plus /> {strings.projects.addSubProject}
    </button>
  );

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: "0.15rem" }}>
          <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
            <h1 style={{ margin: 0 }}>{project.name}</h1>
            <EntitySwitcher
              label="Switch project"
              currentId={project.id}
              loadOptions={() => loadProjectSwitcherOptions("admin")}
            />
          </div>
          <p className="text-muted" style={{ margin: 0 }}>{strings.nav.admin}</p>
        </div>
        {/* "Add sub-project" (docs/decisions.md): the create flow is on ProjectListPage, so this navigates there with the parent
            pre-filled and locked. Disabled until the project has opted in to being a parent (can_be_parent): the saved server
            value, not the unsaved checkbox edit, since a click leads straight to a create flow the backend would reject. */}
        {project.can_be_parent ? addSubProjectButton : <Tooltip label={strings.help.canBeParent} wrap>{addSubProjectButton}</Tooltip>}
      </div>

      <ResourceMenu ariaLabel={strings.admin.sectionsNav} groups={projectAdminGroups} active={activeGroup}>

      {activeGroup === "overview" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.settings}</h2>
        <FormGrid minColumn="18rem">
          <TextField helpNotNeeded
            label={strings.admin.name}
            value={settingsName}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setSettingsName(next);
            }}
          />
          <TextField help={strings.help.projectCode}
            label={strings.projects.code}
            value={settingsCode}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setSettingsCode(next.toUpperCase());
            }}
            inputProps={{ readOnly: !codeEditable, maxLength: codePolicy?.max_length, "aria-describedby": "project-code-hint" }}
          />
          <FormGridFull>
            <p id="project-code-hint" className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>
            {codeEditable && codePolicy
              ? strings.projects.codeEditHint(describeCodePolicy(codePolicy))
              : codePolicy?.assignment === "manual" ? strings.projects.codeLockedHint : strings.projects.codeFixedHint}
            </p>
          </FormGridFull>
          <TextField help={strings.help.projectReportName}
            label={strings.projects.reportName}
            value={settingsReportName}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setSettingsReportName(next);
            }}
            inputProps={{ maxLength: MAX_PROJECT_REPORT_NAME_LENGTH }}
          />
          <FormGridFull>
          <TextAreaField plainText="Shown in project cards and pickers, which are one-line plain-text surfaces" helpNotNeeded
            label={strings.admin.summary}
            value={settingsSummary}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setSettingsSummary(next);
            }}
            rows={2}
          />
          </FormGridFull>
        </FormGrid>
        <CheckboxField help={strings.help.projectAllowMemberChangeRequests}
          label={strings.admin.allowMemberChangeRequests}
          checked={allowMemberCr}
          onChange={(next) => {
            settingsDirtyRef.current = true;
            setAllowMemberCr(next);
          }}
        />
        {/* Checked and disabled (as in `ProjectMembersTable.tsx`) once the organisation's force is active and this project is not
            exempt; see `exemptFromOrgLinkLock` below for the exemption. */}
        <CheckboxField help={strings.help.requireChangeRequestForApprovedLinks}
          label={strings.admin.requireChangeRequestForApprovedLinks}
          checked={requireCrForLinks || (orgForceLinksLocked && !exemptFromOrgLinkLock)}
          onChange={(next) => {
            settingsDirtyRef.current = true;
            setRequireCrForLinks(next);
          }}
          disabled={orgForceLinksLocked && !exemptFromOrgLinkLock}
          title={orgForceLinksLocked && !exemptFromOrgLinkLock ? strings.admin.requireChangeRequestForApprovedLinksForcedByOrg : undefined}
        />
        {orgForceLinksLocked && !exemptFromOrgLinkLock && (
          <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>
            {strings.admin.requireChangeRequestForApprovedLinksForcedByOrg}
          </p>
        )}
        {orgForceLinksLocked && (
          <>
            <CheckboxField help={strings.help.exemptFromOrgLinkLock}
              label={strings.admin.exemptFromOrgLinkLock}
              checked={exemptFromOrgLinkLock}
              onChange={(next) => {
                settingsDirtyRef.current = true;
                setExemptFromOrgLinkLock(next);
              }}
            />
          </>
        )}
        {/* AI approval via MCP (docs/decisions.md): the shared ToggleSwitch, as OrgAdminPage's counterpart, not this page's
            plain-checkbox convention above (component reuse, UX style guide). */}
        <ToggleField help={strings.help.projectAllowAiApprovals}
          label={strings.admin.allowAiApprovals}
          checked={allowAiApprovals}
          onChange={(next) => {
            if (next) {
              setAiApprovalsAckChecked(false);
              setAiApprovalsAckPending(true);
            } else {
              settingsDirtyRef.current = true;
              setAllowAiApprovals(false);
            }
          }}
        />
        <CheckboxField help={strings.help.projectUsableAsTemplate}
          label={strings.admin.isTemplate}
          checked={isTemplate}
          onChange={(next) => {
            settingsDirtyRef.current = true;
            setIsTemplate(next);
          }}
        />
        <FormGrid minColumn="18rem">
          <LabeledSelect help={strings.help.projectVisibility(orgLabel)}
            label={strings.admin.visibility}
            value={visibility}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setVisibility(next as "only_specified" | "org_wide");
            }}
            options={[{ value: "only_specified", label: strings.admin.visibilityOnlySpecified }, { value: "org_wide", label: strings.admin.visibilityOrgWide }]}
            placeholder={null}
          />
          <LabeledSelect help={strings.help.projectStatus}
            label={strings.admin.projectStatus}
            value={statusId}
            onChange={(next) => {
              settingsDirtyRef.current = true;
              setStatusId(next);
            }}
            options={orgProjectStatuses.map((s) => ({ value: s.id, label: s.name }))}
            placeholder={null}
          />
        </FormGrid>

        {/* Hierarchical projects (docs/decisions.md). Always visible: it is the opt-in other projects' managers need before this
            project appears in their "Parent project" picker. */}
        <CheckboxField help={strings.help.canBeParent}
          label={strings.admin.canBeParent}
          checked={canBeParent}
          onChange={(next) => {
            settingsDirtyRef.current = true;
            setCanBeParent(next);
          }}
        />
        {/* The current parent's name is shown plainly (ProjectListPage's "Child of:" label redacts a parent the viewer cannot see)
            because a project's manager manages this relationship and holds the highest authority over it. Cycles are rejected by the
            server check, not by excluding descendants client-side. Hidden when there is nothing eligible and no parent set. */}
        {showParentField && (
          <ProjectNestingFields
            parentProjectId={parentProjectId}
            parentOptions={parentOptions}
            onParentChange={(next) => {
              settingsDirtyRef.current = true;
              setParentProjectId(next);
            }}
            mode={roleInheritanceMode}
            onModeChange={requestInheritModeChange}
            filterRole={roleInheritanceFilterRole}
            onFilterRoleChange={(next) => {
              settingsDirtyRef.current = true;
              setRoleInheritanceFilterRole(next);
            }}
          />
        )}
        {settingsError && <div style={{ color: "var(--color-danger)" }}>{settingsError}</div>}
        {pendingInheritMode && selectedParent && (
          <ConfirmDialog
            title={strings.projects.inheritConfirmTitle}
            message={
              pendingInheritMode === "mirror_role"
                ? strings.projects.inheritConfirmMirrorRole(selectedParent.name, PROJECT_ROLE_LABEL[roleInheritanceFilterRole])
                : strings.projects.inheritConfirmMirrorAll(selectedParent.name)
            }
            confirmLabel={strings.projects.inheritConfirmButton}
            onCancel={() => setPendingInheritMode(null)}
            onConfirm={() => {
              setRoleInheritanceMode(pendingInheritMode);
              setPendingInheritMode(null);
            }}
          />
        )}
        {aiApprovalsAckPending && (
          <ConfirmDialog
            title={strings.admin.allowAiApprovalsAckTitle}
            message={
              <span className="stack" style={{ gap: "var(--space-3)" }}>
                <span>{strings.admin.allowAiApprovalsAckBody}</span>
                <CheckboxField helpNotNeeded
                  label={strings.admin.allowAiApprovalsAckCheckbox}
                  checked={aiApprovalsAckChecked}
                  onChange={setAiApprovalsAckChecked}
                />
              </span>
            }
            confirmLabel={strings.admin.allowAiApprovalsAckConfirm}
            confirmDisabled={!aiApprovalsAckChecked}
            onConfirm={() => {
              settingsDirtyRef.current = true;
              setAllowAiApprovals(true);
              setAiApprovalsAckPending(false);
            }}
            onCancel={() => setAiApprovalsAckPending(false)}
          />
        )}

        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <button className="btn btn-primary" onClick={saveSettings}>
              {strings.admin.saveSettings}
            </button>
            <Tooltip label={strings.admin.exportProjectHint(orgLabel)} wrap>
              <button className="btn" onClick={exportProject} disabled={exporting}>
                <Download /> {exporting ? "Exporting…" : strings.admin.exportProject}
              </button>
            </Tooltip>
          </div>
          <button className="btn btn-danger" onClick={toggleArchive}>
            {project.is_archived ? strings.admin.unarchiveProject : strings.admin.archiveProject}
          </button>
        </div>

        {/* Terminology settings, shown in Overview. */}
        <FormDivider />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.terminology}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.terminologyHint}</p>
        <FormGrid minColumn="14rem">
          {TERMINOLOGY_KEYS.map((key) => (
            <TextField helpNotNeeded
              key={key}
              label={strings.admin.terminologyKeyLabel[key]}
              placeholder={key}
              value={terminology[key] ?? ""}
              onChange={(next) => {
                terminologyDirtyRef.current = true;
                setTerminology((t2) => ({ ...t2, [key]: next }));
              }}
            />
          ))}
        </FormGrid>
        <button className="btn btn-primary" onClick={saveTerminology} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveTerminology}
        </button>
        <FormDivider />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.navLabels.heading}</h2>
        {projectId && <NavLabelsPanel scope={{ kind: "project", projectId }} />}
        <FormDivider />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.codePrefixes.heading}</h2>
        {projectId && <RecordCodePrefixPanel scope={{ kind: "project", projectId }} />}
      </div>
      )}

      {activeGroup === "stagesPhases" && (
      <div className="stack">
        {structureError && <div style={{ color: "var(--color-danger)" }}>{structureError}</div>}
        <CollapsibleSection sectionKey="projectAdmin.stagesPhases.stageWorkflows" title={strings.stageWorkflows.heading} defaultCollapsed={false}>
          {projectId && <StageWorkflowsPanel scope={{ kind: "project", projectId }} onChanged={reload} />}
        </CollapsibleSection>

        <CollapsibleSection sectionKey="projectAdmin.stagesPhases.stages" title={strings.admin.stages} defaultCollapsed={false}>
        {stages.map((s) => {
          const nameEdit = stageNameEdits[s.id] ?? s.name;
          const otherStages = stages.filter((other) => other.id !== s.id);
          return (
          <div key={s.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="row">
                <InlineTextInput
                  maxWidth={220} value={nameEdit} ariaLabel={`${strings.admin.name}: ${s.name}`}
                  onChange={(next) => setStageNameEdits((m) => ({ ...m, [s.id]: next }))}
                />
                {nameEdit !== s.name && nameEdit && (
                  <button
                    className="btn"
                    onClick={() => renameStage(s.id, nameEdit)}
                    title={strings.admin.rename}
                    aria-label={strings.admin.rename}
                  >
                    <Pencil />
                  </button>
                )}
                <Badge>{stagePhaseLabel(s.phase_name, s.phase_kind)}</Badge>
                {s.review_deadline && <Badge>{strings.admin.reviewDeadline}: {new Date(s.review_deadline).toLocaleString()}</Badge>}
                {s.completed_at && <Badge>{strings.admin.stageCompletedAt}: {new Date(s.completed_at).toLocaleDateString()}</Badge>}
                <button
                  className="btn btn-danger"
                  disabled={otherStages.length === 0}
                  title={otherStages.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteStage}
                  aria-label={otherStages.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteStage}
                  onClick={() => setDeletingStageId(s.id)}
                >
                  <Trash2 />
                </button>
              </div>
              <div className="row">
                {stageWorkflows.length > 1 && (
                  <InlineSelect
                    ariaLabel={strings.stageWorkflows.changeWorkflowAria(s.name)} value={s.workflow_id} placeholder={null}
                    disabled={s.phase_kind !== "open"} maxWidth={200}
                    onChange={(next) => changeStageWorkflow(s, next)}
                    options={stageWorkflows.map((w) => ({ value: w.id, label: w.name }))}
                  />
                )}
                <InlineSelect
                  ariaLabel={strings.stageWorkflows.changePhaseAria(s.name)} value={s.phase_id} placeholder={null} maxWidth={220}
                  onChange={(next) => requestStageMove(s, next)}
                  options={(stageWorkflows.find((w) => w.id === s.workflow_id)?.phases ?? [{ id: s.phase_id, name: s.phase_name, kind: s.phase_kind }])
                    .map((p) => {
                      // Entering or leaving a locked phase needs a project manager: show the choice as unavailable, with why.
                      const locked = !s.can_lock && p.id !== s.phase_id && (p.kind === "locked" || s.phase_kind === "locked");
                      return { value: p.id, label: locked ? strings.stageWorkflows.lockedNeedsManager(p.name) : p.name, disabled: locked };
                    })}
                />
              </div>
            </div>
            {s.phase_kind === "review" && (
              <div className="row">
                <InlineTextInput
                  type="datetime-local" maxWidth={220} ariaLabel={`${strings.admin.reviewDeadline}: ${s.name}`}
                  value={deadlineInputs[s.id] ?? ""}
                  onChange={(next) => setDeadlineInputs((d) => ({ ...d, [s.id]: next }))}
                />
                <button
                  className="btn"
                  onClick={() => setReviewDeadline(s.id, deadlineInputs[s.id] ? new Date(deadlineInputs[s.id]).toISOString() : "")}
                >
                  {strings.admin.setReviewDeadline}
                </button>
                {s.review_deadline && (
                  <>
                    <button className="btn" onClick={() => respondToStageReview(s.id, "approved")}>
                      {strings.admin.respondApprove}
                    </button>
                    <button className="btn btn-danger" onClick={() => respondToStageReview(s.id, "rejected")}>
                      {strings.admin.respondReject}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          );
        })}
        <div>
          <button className="btn btn-primary" onClick={() => setCreatingStage(true)}>
            <Plus /> {strings.admin.newStage}
          </button>
        </div>
        </CollapsibleSection>

        <CollapsibleSection sectionKey="projectAdmin.stagesPhases.componentPhases" title={strings.componentPhases.heading} defaultCollapsed={false}>
          {projectId && project && (
            <ComponentPhasesPanel projectId={projectId} organizationId={project.organization_id} orgUsers={orgUsers} onChanged={reload} />
          )}
        </CollapsibleSection>

        <CollapsibleSection sectionKey="projectAdmin.stagesPhases.phaseSchedule" title={strings.phaseSchedule.heading} defaultCollapsed={false}>
          {projectId && project && (
            <PhaseSchedulePanel projectId={projectId} organizationId={project.organization_id} orgUsers={orgUsers} onChanged={reload} />
          )}
        </CollapsibleSection>

      </div>
      )}

      {activeGroup === "structure" && (
      <div className="stack">
        {structureError && <div style={{ color: "var(--color-danger)" }}>{structureError}</div>}
        <CollapsibleSection sectionKey="projectAdmin.structure.componentsCategories" title={strings.admin.componentsAndCategories} defaultCollapsed={false}>
          {projectId && <StructurePanel projectId={projectId} onChanged={reload} />}
        </CollapsibleSection>

        <CollapsibleSection sectionKey="projectAdmin.structure.requirementAliases" title={strings.requirementAliases.settings.heading}>
          {projectId && <RequirementAliasSettingsPanel scope={{ kind: "project", projectId }} />}
        </CollapsibleSection>
      </div>
      )}

      {activeGroup === "lifecycles" && (
      <div className="stack">
        <CollapsibleSection sectionKey="projectAdmin.lifecycles" title={strings.lifecycleSettings.heading} help={strings.help.lifecyclesProject} defaultCollapsed={false}>
          {projectId && <ProjectLifecyclesPanel projectId={projectId} />}
        </CollapsibleSection>
      </div>
      )}

      {activeGroup === "fieldsActions" && (
      <div className="stack">
        <CollapsibleSection sectionKey="projectAdmin.fieldsActions.customFields" title={strings.admin.customFields} defaultCollapsed={false}>
        {customFields.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {f.name} <Badge>{f.entity_kind === "requirement" ? strings.admin.entityKindRequirement : strings.admin.entityKindChangeRequest}</Badge> <Badge>{CUSTOM_FIELD_TYPE_LABEL[f.field_type]}</Badge>
              {f.required && <Badge>{strings.admin.required}</Badge>}
            </span>
            <button
              className="btn btn-danger"
              title={strings.admin.deleteCustomField(f.name)}
              aria-label={strings.admin.deleteCustomField(f.name)}
              onClick={() => setDeletingFieldId(f.id)}
            >
              <Trash2 />
            </button>
            {deletingFieldId === f.id && (
              <ConfirmDialog
                title={strings.admin.deleteCustomField(f.name)}
                message={strings.admin.deleteCustomFieldConfirm(f.name)}
                confirmLabel={strings.common.delete}
                onConfirm={() => { setDeletingFieldId(null); deleteCustomField(f.id); }}
                onCancel={() => setDeletingFieldId(null)}
              />
            )}
          </div>
        ))}
        <div>
          <button className="btn btn-primary" onClick={() => setCreatingField(true)}>
            <Plus /> {strings.admin.newCustomField}
          </button>
        </div>
        </CollapsibleSection>

        <CollapsibleSection sectionKey="projectAdmin.fieldsActions.actionTypes" title={strings.admin.actionTypes} defaultCollapsed={false}>
        <DefinitionList
          items={actionTypes}
          fields={[{ key: "name", getValue: (i) => i.name, placeholder: strings.admin.name, maxWidth: 220 }]}
          getReassignLabel={(i) => i.name}
          onMove={moveActionType}
          onRename={(id, values) => renameActionType(id, values.name)}
          onAdd={(values) => addActionType(values.name)}
          onDelete={deleteActionType}
          deleteLabel={strings.admin.deleteActionType}
          addLabel={strings.admin.newActionType}
        />
        </CollapsibleSection>

        {project && (
          <CollapsibleSection sectionKey="projectAdmin.fieldsActions.linkTypes" title={strings.orgAdmin.linkTypes} defaultCollapsed={false}>
            <LinkTypesPanel scope={{ kind: "project", orgId: project.organization_id, projectId: project.id }} />
          </CollapsibleSection>
        )}

        {projectId && (
          <CollapsibleSection sectionKey="projectAdmin.fieldsActions.externalSystems" title={strings.externalSystems.heading} help={strings.externalSystems.projectHelp} defaultCollapsed={false}>
            <ProjectExternalSystemsPanel projectId={projectId} />
          </CollapsibleSection>
        )}
      </div>
      )}

      {activeGroup === "members" && (
      <div className="stack">
        <div className="card stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap" }}>
            <div className="stack" style={{ gap: "0.15rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.effectiveMembers}</h2>
              <p className="text-muted" style={{ margin: 0 }}>{strings.admin.effectiveMembersHint}</p>
            </div>
            {/* Convert-inherited-to-direct (docs/decisions.md): a safety net before disabling inheritance elsewhere drops someone's
                access. It acts on the whole member set, so it is not a `ProjectMembersTable` row action. */}
            <button className="btn" onClick={materializeInheritedAccess} disabled={materializing}>
              {strings.admin.materializeAll}
            </button>
          </div>
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => setAddMemberModalOpen(true)}>
              <Plus /> {strings.admin.addMember}
            </button>
            {/* No sibling "Add group" button: the autocomplete below also matches organisation groups (see UserAutocomplete's module docstring). */}
          </div>
          {/* The shared staged multi-add component (`AddMembersModal`) in two configurations; see its module docstring for the
              project-group hand-off design. */}
          {addMemberModalOpen && addMemberTargetGroup && (
            // Second step after picking a project-group match: adds the picked person as a member of that group (`addGroupMember`/
            // `addOrgGroupMember`, `POST .../groups/{group_id}/members`) instead of granting a role. The group's own roles apply
            // to whoever joins, so `showRole={false}` hides the role picker.
            <AddMembersModal
              title={strings.admin.addMemberToGroupTitle(addMemberTargetGroup.name)}
              onClose={() => {
                setAddMemberModalOpen(false);
                setAddMemberTargetGroup(null);
              }}
              onBack={() => setAddMemberTargetGroup(null)}
              hint={strings.admin.addMemberToGroupHint(addMemberTargetGroup.name)}
              showRole={false}
              users={orgUsers.filter((u) => !addMemberTargetGroup.member_user_ids.includes(u.user_id))}
              groups={orgGroups.filter((og) => !addMemberTargetGroup.member_org_group_ids.includes(og.id))}
              onAddEntry={async (entry) => {
                if (entry.kind === "user") await addGroupMember(addMemberTargetGroup.id, entry.id);
                else if (entry.kind === "group") await addOrgGroupMember(addMemberTargetGroup.id, entry.id);
              }}
            />
          )}
          {addMemberModalOpen && !addMemberTargetGroup && (
            <AddMembersModal
              title={strings.admin.addMember}
              onClose={() => setAddMemberModalOpen(false)}
              users={orgUsers}
              groups={orgGroups}
              projectGroups={memberTableGroups}
              organizationId={project?.organization_id}
              projectId={project?.id}
              onSelectProjectGroup={(groupId) =>
                setAddMemberTargetGroup(memberTableGroups.find((g) => g.id === groupId) ?? null)
              }
              onAddEntry={handleAddMembersEntry}
              onCommitted={handleAddMembersCommitted}
            />
          )}
          {effectiveMembers === null ? (
            <Spinner />
          ) : (
            <ProjectMembersTable
              members={effectiveMembers}
              invites={pendingInvites}
              groupRoles={groupRoles}
              onToggleRole={toggleProjectMemberRole}
              onToggleGroupRole={toggleProjectMemberOrgGroupRole}
              onResendInvite={resendProjectInvite}
              resendingInviteId={resendingInviteId}
              onRemoveAllAccess={removeAllProjectMemberAccess}
              onConvertToDirect={convertProjectMemberToDirect}
              onRemoveGroup={removeProjectMemberOrgGroup}
              ariaLabel={strings.admin.membersNav}
              availableModuleRoles={availableModuleRoles}
              onToggleModuleRole={toggleProjectMemberModuleRole}
            />
          )}
          {externalAddResult && (
            <div style={{ color: externalAddResult.isError ? "var(--color-danger)" : "var(--color-accent)" }}>
              {externalAddResult.message}
            </div>
          )}
        </div>
      </div>
      )}

      {activeGroup === "groups" && (
      <div className="stack">
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.groups}</h2>
        <button
          className="btn btn-primary"
          style={{ alignSelf: "flex-start" }}
          onClick={() => setNewGroupModalOpen(true)}
        >
          <Plus /> {strings.admin.newGroup}
        </button>
        {newGroupModalOpen && (
          // Style guide "Pattern: modal dialog for entity create/rename": a new entity opens in a Modal, not a Popover (reserved for a
          // quick action on something that exists). `ProjectGroupCreate` takes no role, so a new group starts with zero roles,
          // shown as "No roles assigned" until one is granted from the row's `MultiSelectDropdown`.
          <Modal title={strings.admin.newGroup} onClose={() => setNewGroupModalOpen(false)}>
            <TextField helpNotNeeded required
              label={strings.admin.name}
              value={newGroupName}
              onChange={setNewGroupName}
              placeholder={strings.admin.groupNamePlaceholder}
              inputProps={{ autoFocus: true, onKeyDown: (e) => {
                  if (e.key === "Enter" && newGroupName) createProjectGroup();
                } }}
            />
            <FormActions
              onCancel={() => setNewGroupModalOpen(false)}
              onSave={createProjectGroup}
              saveLabel={strings.common.create}
              saveDisabled={!newGroupName}
            />
          </Modal>
        )}

        {/* Shared `DirectoryTable` in the `.side-grid` + `FilterPanel` layout (docs/decisions.md). `onRowClick`, not `rowHref`: a
            group named "Members" and this page's `ResourceMenu` "Members" link would both be `role="link"` with one accessible name,
            ambiguous for screen readers too, while `onRowClick`'s `role="button"` cannot collide with a nav `<Link>`. The
            `openGroupId`/`useSearchParams` handling below covers the `?openGroup=` deep link; `onRowClick` calls the same
            `setOpenGroupId`. */}
        <div className="side-grid">
          <div className="stack">
            <DirectoryTable
              ariaLabel={strings.admin.groups}
              columns={groupsTabColumns}
              rows={groupsTabRows}
              rowKey={(row) => (row.kind === "group" ? `group-${row.group.id}` : `member_source-${row.source.source_project_id}`)}
              sort={groupSort}
              onSort={(key) => applyGroupSort(key as ProjectGroupSortKey)}
              total={groupsTotal + memberSources.length}
              onLoadMore={() => loadGroups(groupSearch, groups.length, true)}
              onRowClick={(row) => {
                if (row.kind === "group") setOpenGroupId(row.group.id);
              }}
              emptyState={<p className="text-muted">{strings.admin.noGroupsFound}</p>}
            />
          </div>
          <FilterPanel
            sectionKey="projectAdminGroupsFilters"
            search={groupSearch}
            onSearchChange={handleGroupSearchChange}
            searchPlaceholder={strings.admin.searchGroups}
          >
            {/* Groups have no filter fields beyond search; `FilterPanel` is still the shell, as for Org Groups. */}
            {null}
          </FilterPanel>
        </div>
      </div>

      {/* Member sources (docs/decisions.md): the reverse (source to receiving) RBAC mechanism, not a field on the source's form;
          authorised by managing this (receiving) project only. Any same-organisation project is a valid source, with
          mirror_mode/mirror_filter_role using the vocabulary of the forward (Inherit from parent) controls on the Overview
          tab: "Member only" needs no confirmation (the risk of visibility=org_wide) but "Mirror all roles"/"Mirror one role"
          can convey an elevated role, as the forward modes can. The entries are rows of the `DirectoryTable` above; this card
          holds only the add affordance. */}
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.memberSources}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.memberSourcesHint}</p>
        {sourceCandidates.length > 0 ? (
          <div className="row" style={{ flexWrap: "wrap" }}>
            <InlineSelect
              maxWidth={280} value={addSourceId} ariaLabel={strings.admin.memberSourceProjectSelect}
              placeholder={strings.common.selectOption}
              options={sourceCandidates.map((c) => ({ value: c.id, label: c.name }))}
              onChange={setAddSourceId}
            />
            <InlineSelect
              maxWidth={200} value={addMirrorMode} ariaLabel={strings.admin.memberSourceModeSelect} placeholder={null}
              options={(Object.keys(PROJECT_ROLE_INHERITANCE_MODE_LABEL) as ProjectRoleInheritanceMode[])
                .filter((m) => m !== "none")
                .map((m) => ({ value: m, label: PROJECT_ROLE_INHERITANCE_MODE_LABEL[m] }))}
              onChange={(next) => setAddMirrorMode(next as ProjectRoleInheritanceMode)}
            />
            {addMirrorMode === "mirror_role" && (
              <InlineSelect
                maxWidth={200} value={addMirrorFilterRole} ariaLabel={strings.admin.memberSourceFilterRoleSelect} placeholder={null}
                options={(["project_manager", "project_administrator", "stakeholder"] as const).map((r) => ({ value: r, label: PROJECT_ROLE_LABEL[r] }))}
                onChange={(next) => setAddMirrorFilterRole(next as ProjectRole)}
              />
            )}
            <button className="btn" onClick={addMemberSource} disabled={!addSourceId}>
              {strings.admin.addMemberSource}
            </button>
          </div>
        ) : (
          memberSources.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.admin.noChildrenToAdd}</p>
        )}
      </div>

        {openGroupId && (() => {
          const g = memberTableGroups.find((x) => x.id === openGroupId) ?? groups.find((x) => x.id === openGroupId);
          if (!g) return null;
          const availableUsers = orgUsers.filter((u) => !g.member_user_ids.includes(u.user_id));
          const nestedOrgGroups = orgGroups.filter((og) => g.member_org_group_ids.includes(og.id));
          const nestableOrgGroups = orgGroups.filter((og) => !g.member_org_group_ids.includes(og.id));
          const referencedProjects = orgProjects.filter((p) => g.member_source_project_ids.includes(p.id));
          const referenceableProjects = orgProjects.filter(
            (p) => p.id !== projectId && !g.member_source_project_ids.includes(p.id),
          );
          return (
            <SidePanel title={strings.admin.groupDetails(g.name)} onClose={() => setOpenGroupId(null)}>
              <div className="stack">
                <RecordFieldGroup helpNotNeeded label={strings.admin.groupRoleAtTop}>
                  {/* The same per-row MultiSelectDropdown as the Groups tab's "role" column (`groupsTabColumns`): both read
                      `memberTableGroups`/`groups` and call `toggleProjectGroupRole`. */}
                  <MultiSelectDropdown
                    triggerLabel={strings.admin.groupRolesFor(g.name)}
                    emptyLabel={strings.admin.noRolesAssigned}
                    options={PROJECT_GROUP_ROLES.map((role) => {
                      const checked = g.roles.includes(role);
                      const isLastManager = checked && role === "project_manager" && groupManagerSourceCount <= 1;
                      return {
                        value: role,
                        label: PROJECT_ROLE_LABEL[role],
                        checked,
                        disabled: isLastManager,
                        title: isLastManager ? strings.membersTable.cannotRemoveLastManager : undefined,
                        optionLabel: checked
                          ? strings.membersTable.revokeRole(PROJECT_ROLE_LABEL[role], g.name)
                          : strings.membersTable.grantRole(PROJECT_ROLE_LABEL[role], g.name),
                        // False positive (react-hooks/refs): `toggleProjectGroupRole` reaches `loadGroupsRequestIdRef` through `reload()`, but
                        // this `onToggle` runs only from click handling, never during render, where ref access is allowed. The
                        // upstream fix (facebook/react#35062) is not shipped in `eslint-plugin-react-hooks` and does not cover a plain
                        // object field consumed by a custom component (docs/decisions.md, React 19/ESLint 10 upgrade entry).
                        // eslint-disable-next-line react-hooks/refs
                        onToggle: () => toggleProjectGroupRole(g.id, role, !checked),
                      };
                    })}
                  />
                </RecordFieldGroup>
                <button
                  className="btn btn-danger"
                  style={{ alignSelf: "flex-start" }}
                  title={strings.admin.deleteGroup}
                  onClick={() => setDeletingGroupId(g.id)}
                >
                  <Trash2 /> {strings.admin.deleteGroup}
                </button>

                {g.member_user_ids.length > 0 && (
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {g.member_user_ids.map((userId) => {
                      const u = orgUsers.find((ou) => ou.user_id === userId);
                      return (
                        <li key={userId} className="row" style={{ justifyContent: "space-between", listStyle: "disc" }}>
                          <span>{u ? `${u.display_name} (${u.email})` : userId}</span>
                          <button
                            className="btn btn-danger"
                            title={strings.admin.removeMember(u ? u.display_name : userId)}
                            aria-label={strings.admin.removeMember(u ? u.display_name : userId)}
                            // False positive (react-hooks/refs): runs only on click, not during render (see the onToggle comment above).
                            // eslint-disable-next-line react-hooks/refs
                            onClick={() => removeGroupMember(g.id, userId)}
                          >
                            <Trash2 />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <UserAutocomplete
                  users={availableUsers}
                  placeholder={strings.admin.addOrInviteMemberPlaceholder}
                  // False positive (react-hooks/refs): runs only when a result is selected; `UserAutocomplete` is a custom component, so
                  // facebook/react#35062 would not cover it (see the onToggle comment above).
                  // eslint-disable-next-line react-hooks/refs
                  onSelect={(userId) => run(() => addGroupMember(g.id, userId), "add", "group member")}
                  organizationId={project?.organization_id}
                  projectId={project?.id}
                  // A group may hold zero, one or several roles, and the by-email endpoint grants one role at a time (see
                  // `addExternalMember`), so this uses the group's first held role; with none, the invite affordance is withheld.
                  // False positive (react-hooks/refs): as `onSelect` above (a custom-component prop; see the onToggle comment above).
                  // eslint-disable-next-line react-hooks/refs
                  onSelectExternal={g.roles.length > 0 ? (email) => addExternalMember(email, g.roles[0]) : undefined}
                />
                {/* `externalAddResult` is shared with the Members section's add control (`addExternalMember`); this panel's invite-by-email
                    path sets the same state, so the outcome is rendered here too (Principle 7). */}
                {externalAddResult && (
                  <div style={{ color: externalAddResult.isError ? "var(--color-danger)" : "var(--color-accent)" }}>
                    {externalAddResult.message}
                  </div>
                )}
                {nestedOrgGroups.length > 0 && (
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {nestedOrgGroups.map((og) => (
                      <li key={og.id} className="row" style={{ justifyContent: "space-between", listStyle: "circle" }}>
                        <span>{strings.admin.viaOrgGroup(og.name, orgLabel)}</span>
                        <button
                          className="btn btn-danger"
                          title={strings.admin.removeNestedGroup(strings.admin.viaOrgGroup(og.name, orgLabel))}
                          aria-label={strings.admin.removeNestedGroup(strings.admin.viaOrgGroup(og.name, orgLabel))}
                          // False positive (react-hooks/refs): see the onToggle comment above.
                          // eslint-disable-next-line react-hooks/refs
                          onClick={() => removeOrgGroupMember(g.id, og.id)}
                        >
                          <Trash2 />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {nestableOrgGroups.length > 0 && (
                  <div className="row">
                    <InlineSelect
                      ariaLabel={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      placeholder={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      value={orgGroupSelections[g.id] ?? ""}
                      options={nestableOrgGroups.map((og) => ({ value: og.id, label: og.name }))}
                      onChange={(next) => setOrgGroupSelections((prev) => ({ ...prev, [g.id]: next }))}
                    />
                    <button
                      className="btn"
                      disabled={!orgGroupSelections[g.id]}
                      title={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      aria-label={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      // False positive (react-hooks/refs): see the onToggle comment above.
                      // eslint-disable-next-line react-hooks/refs
                      onClick={() => addOrgGroupMember(g.id, orgGroupSelections[g.id])}
                    >
                      <Plus />
                    </button>
                  </div>
                )}
                {referencedProjects.length > 0 && (
                  <>
                    <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                      {referencedProjects.map((p) => (
                        <li key={p.id} className="row" style={{ justifyContent: "space-between", listStyle: "circle" }}>
                          <span className="row" style={{ gap: "var(--space-2)" }}>
                            {strings.admin.viaProjectMembers(p.name)}
                            <Link to={`/projects/${p.id}/admin/members`}>{strings.admin.viaProjectMembersLinkLabel}</Link>
                          </span>
                          <button
                            className="btn btn-danger"
                            title={strings.admin.removeNestedGroup(strings.admin.viaProjectMembers(p.name))}
                            aria-label={strings.admin.removeNestedGroup(strings.admin.viaProjectMembers(p.name))}
                            // False positive (react-hooks/refs): see the onToggle comment above.
                            // eslint-disable-next-line react-hooks/refs
                            onClick={() => removeProjectRefMember(g.id, p.id)}
                          >
                            <Trash2 />
                          </button>
                        </li>
                      ))}
                    </ul>
                    <p className="text-muted" style={{ fontSize: "0.8rem", margin: 0 }}>{strings.admin.viaProjectMembersHint}</p>
                  </>
                )}
                {referenceableProjects.length > 0 && (
                  <div className="row">
                    <InlineSelect
                      value={sourceProjectSelections[g.id] ?? ""}
                      ariaLabel={strings.admin.projectReferenceSelect}
                      placeholder={strings.admin.addProjectReferenceToProjectGroup}
                      options={referenceableProjects.map((p) => ({ value: p.id, label: p.name }))}
                      onChange={(next) => setSourceProjectSelections((prev) => ({ ...prev, [g.id]: next }))}
                    />
                    <button
                      className="btn"
                      disabled={!sourceProjectSelections[g.id]}
                      title={strings.admin.addProjectReferenceToProjectGroup}
                      aria-label={strings.admin.addProjectReferenceToProjectGroup}
                      // False positive (react-hooks/refs): see the onToggle comment above.
                      // eslint-disable-next-line react-hooks/refs
                      onClick={() => addProjectRefMember(g.id, sourceProjectSelections[g.id])}
                    >
                      <Plus />
                    </button>
                  </div>
                )}
              </div>
            </SidePanel>
          );
        })()}

        {deletingGroupId && (
          <ConfirmDialog
            title={strings.admin.deleteGroupTitle(
              (memberTableGroups.find((x) => x.id === deletingGroupId) ?? groups.find((x) => x.id === deletingGroupId))?.name ?? ""
            )}
            message={strings.admin.deleteGroupMessage}
            confirmLabel={strings.admin.deleteGroup}
            onConfirm={() => deleteGroup(deletingGroupId)}
            onCancel={() => setDeletingGroupId(null)}
          />
        )}
        {inUseGroup && project && (
          <GroupInUseDialog
            groupName={(memberTableGroups.find((x) => x.id === inUseGroup.id) ?? groups.find((x) => x.id === inUseGroup.id))?.name ?? ""}
            groupId={inUseGroup.id}
            usage={inUseGroup.usage}
            organizationId={project.organization_id}
            projectId={project.id}
            orgUsers={orgUsers}
            kinds={["user", "org_group", "project_group"]}
            onReplace={(replacement) => deleteGroup(inUseGroup.id, replacement)}
            onClear={() => deleteGroup(inUseGroup.id, undefined, true)}
            onClose={() => setInUseGroup(null)}
          />
        )}
      </div>
      )}

      {activeGroup === "reportSetup" && (
      <div className="stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.reportSetup}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.reportSetupHint}</p>
        {layoutApi && packApi && placementApi && (
          <ReportSetupPanel layoutApi={layoutApi} packApi={packApi} placementApi={placementApi} />
        )}
        {projectId && (
          <CollapsibleSection sectionKey="projectAdmin.reportSnippets" title={strings.reportSnippetsPanel.sectionTitle}>
            <ReportSnippetsPanel scope={snippetScope} />
          </CollapsibleSection>
        )}
      </div>
      )}

      {/* The Modules group (below) overrides this project's effective enablement of a module or sub-component against the
          organisation default (the project-tier sibling of Org Admin's "Modules" section); it is separate from
          `moduleAdminSections`, a module's own admin panel. */}
      {activeGroup === "tags" && projectId && (
        <div className="stack">
          <CollapsibleSection sectionKey="projectAdmin.tags" title={strings.tags.admin.title}>
            <ProjectTagsPanel projectId={projectId} />
          </CollapsibleSection>
        </div>
      )}

      {activeGroup === "modules" && (
        <div className="stack">
          <CollapsibleSection sectionKey="projectAdmin.modules" title={strings.admin.modulesNav}>
            <p className="text-muted">{strings.admin.modulesDescription}</p>
            {projectModules.length === 0 ? (
              <p className="text-muted">{strings.admin.modulesEmpty}</p>
            ) : (
              <ModuleSettingsList
                items={projectModules.map((m) => {
                  const subComponents = projectModuleSubComponents[m.module_key] ?? [];
                  return {
                    key: m.module_key,
                    name: m.name,
                    // The API lists only modules the organisation has enabled, so a module here
                    // is always one this project may switch.
                    hint: m.effective_enabled !== m.org_default_enabled
                      ? strings.admin.moduleOrgDefaultHint(m.org_default_enabled)
                      : null,
                    control: (
                      <ToggleSwitch
                        checked={m.effective_enabled}
                        label={strings.admin.moduleToggleLabel(m.name)}
                        onChange={(next) => toggleProjectModuleEnabled(m.module_key, next)}
                      />
                    ),
                    subSummary: strings.admin.moduleSubComponentsSummary(
                      subComponents.length, subComponents.filter((sub) => sub.effective_enabled).length,
                    ),
                    subItems: subComponents.map((sub) => ({
                      key: sub.subcomponent_key,
                      name: sub.name,
                      control: (
                        <ToggleSwitch
                          checked={sub.effective_enabled}
                          disabled={!m.effective_enabled}
                          label={strings.admin.moduleSubComponentToggleLabel(m.name, sub.name)}
                          onChange={(next) => toggleProjectSubComponentEnabled(m.module_key, sub.subcomponent_key, next)}
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

      {/* One generic lookup for every module-contributed section, as `OrgAdminPage.tsx`'s `moduleAdminSections`; a new module's
          `projectAdminSections` entry needs no edit here. */}
      {moduleAdminSections
        .filter((section) => section.key === activeGroup)
        .map((section) => (
          <div className="stack" key={section.key}>
            {section.render({ projectId: project.id })}
          </div>
        ))}
      {stageMove.dialog}
      {creatingStage && (
        <StageCreateModal
          workflows={stageWorkflows} workflowId={newStageWorkflowId} onWorkflowChange={setNewStageWorkflowId}
          onNewWorkflow={() => { setNewWorkflowError(null); setCreatingWorkflow(true); }}
          onCreate={addStage} onClose={() => setCreatingStage(false)}
        />
      )}
      {creatingField && <CustomFieldCreateModal onCreate={addCustomField} onClose={() => setCreatingField(false)} />}
      {creatingWorkflow && (
        <StageWorkflowEditor workflow={null} error={newWorkflowError} onCancel={() => setCreatingWorkflow(false)} onSave={saveNewWorkflow} />
      )}
      {deletingStageId && stages.some((st) => st.id === deletingStageId) && (
        <DeleteInUseDialog
          title={strings.admin.deleteInUseTitle(stages.find((st) => st.id === deletingStageId)!.name)}
          summary={strings.admin.deleteStageReassignSummary}
          candidates={stages.filter((other) => other.id !== deletingStageId).map((other) => ({ id: other.id, label: other.name }))}
          onMove={(replacementId) => deleteStage(deletingStageId, replacementId)}
          onClose={() => setDeletingStageId(null)}
        />
      )}
      </ResourceMenu>
    </div>
  );
}
