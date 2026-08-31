import { ArrowDown, ArrowUp, Check, Download, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type {
  ActionTypeDefinition,
  AssignByEmailOutcome,
  Category,
  Component,
  CustomFieldDefinition,
  CustomFieldEntityKind,
  CustomFieldType,
  EffectiveMember,
  MaterializeResult,
  OrgGroup,
  OrgUser,
  PendingInvite,
  Project,
  ProjectGroup,
  ProjectListItem,
  ProjectMemberSource,
  ProjectReportConfig,
  ProjectRole,
  ProjectRoleInheritanceMode,
  ProjectStage,
  ProjectStatusDefinition,
  ReportChapter,
  ReportTemplate,
} from "../api/types";
import { CUSTOM_FIELD_TYPE_LABEL, PROJECT_ROLE_INHERITANCE_MODE_LABEL, PROJECT_ROLE_LABEL, STAGE_STATUS_LABEL } from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DefinitionList } from "../components/DefinitionList";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { FilterPanel } from "../components/FilterPanel";
import { Modal } from "../components/Modal";
import { ProjectMembersTable } from "../components/ProjectMembersTable";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { RichTextEditor } from "../components/RichTextEditor";
import { SidePanel } from "../components/SidePanel";
import { cycleSort, type SortState } from "../components/SortableHeader";
import { Spinner } from "../components/Spinner";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { useOrgLabel } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { downloadBlob } from "../utils/download";

// MIRROR_ALL/MIRROR_ROLE can convey manager/admin control (unlike
// MEMBER_ONLY, which caps at baseline MEMBER — parity with
// visibility=ORG_WIDE, no confirmation needed) — see docs/decisions.md.
const MODES_NEEDING_CONFIRMATION: ProjectRoleInheritanceMode[] = ["mirror_all", "mirror_role"];

const TERMINOLOGY_KEYS = ["project", "stage", "component", "category", "requirement", "change_request"] as const;

/**
 * The 5 resource-menu groups Project Admin's previous 5-tab bar (itself
 * consolidated down from 8 — see the removed tab-count-ceiling comment
 * this replaced) was converted into. Each key is also the route segment
 * under `/projects/:projectId/admin/:group?` (App.tsx), so a group
 * selection is a real navigation, not client-only state. An unrecognised
 * or absent `:group` (including the bare `/projects/:projectId/admin`
 * used by every existing link into this page) falls back to "overview".
 *
 * Converted from `Tabs` to `ResourceMenu` for cross-page consistency with
 * the other admin-tier pages (Org Admin, Server Admin, Preferences) —
 * a deliberate reversal of the original per-page ≤5-groups Tabs-vs-
 * ResourceMenu call recorded in the 2026-08 UX audit, since this page
 * never exceeded 5 tabs on its own. See `docs/ux-style-guide.md`
 * Principle 1 and `docs/decisions.md`.
 *
 * "groups" (the combined "Project groups" tab: effective-members audit
 * table, pending invites, and the groups list all on one screen) was later
 * split into "members" and "groups" (Phase 5, docs/decisions.md) — a group's
 * role being fixed at creation, with no way to add-then-assign, and an
 * org-admin membership UI duplicating a worse version of this one, were
 * both flagged directly; "groups" keeps the groups list itself, now opening
 * a `SidePanel` per group instead of an always-expanded accordion.
 *
 * "members" itself was rebuilt again in a later phase (Phase D, follow-up
 * UX batch, 2026-08-31, docs/decisions.md): once default project groups
 * were removed (Phase C) a group stopped being the common way to grant a
 * role, so the "editable users-and-groups table plus a separate effective-
 * members audit table plus a separate pending-invites section" shape that
 * phase built became three sections doing one job — `ProjectMembersTable`
 * (`components/ProjectMembersTable.tsx`) replaces all three with a single
 * table over `GET /effective-members`'s own provenance, with pending
 * invites folded in as a per-row status. See that component's own
 * docstring for the full rationale, including the `kind` split
 * (`direct_role` vs. group/nested-org-group/project-ref/org-wide) that
 * makes its inline role-toggle safe.
 */
type ProjectAdminGroupKey = "overview" | "structure" | "fieldsActions" | "members" | "groups" | "reportSetup";

const PROJECT_ADMIN_GROUP_KEYS: ProjectAdminGroupKey[] = [
  "overview",
  "structure",
  "fieldsActions",
  "members",
  "groups",
  "reportSetup",
];

/**
 * Project administration: settings (C-U-13, C-C-03, C-P-01) — including the
 * project's status, picked from the owning organisation's definable status
 * list (see OrgAdminPage's Project Statuses section) — stages/approval
 * (C-G-08, C-G-10), components and categories with ordering (C-G-07,
 * C-E-01/C-E-02), project-scoped action types (Action Types tab — the type
 * list requirement actions on this project pick from; project-scoped
 * rather than org-scoped, matching custom fields, per `docs/decisions.md`),
 * and project groups (C-U-11).
 */
export function ProjectAdminPage() {
  const strings = useStrings();
  const { projectId, group: groupParam } = useParams<{ projectId: string; group?: string }>();
  const navigate = useNavigate();
  const orgLabel = useOrgLabel();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [stages, setStages] = useState<ProjectStage[] | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [groupsTotal, setGroupsTotal] = useState(0);
  const [groupSearch, setGroupSearch] = useState("");
  // Groups tab `DirectoryTable` retrofit (Phase B, follow-up UX batch,
  // 2026-08-31) — `list_project_groups` already pages via `limit`/`offset`,
  // so Name sort is a backend-sorted refetch (its new `order` param), not a
  // client-side sort of only the loaded page — style guide "Pattern:
  // sortable column header"'s "already paginated -> backend sort/order
  // params" branch, same reasoning as Org Admin's own Groups table.
  type ProjectGroupSortKey = "name";
  const [groupSort, setGroupSort] = useState<SortState<ProjectGroupSortKey> | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [orgGroups, setOrgGroups] = useState<OrgGroup[]>([]);
  const [orgGroupSelections, setOrgGroupSelections] = useState<Record<string, string>>({});
  const [sourceProjectSelections, setSourceProjectSelections] = useState<Record<string, string>>({});
  // "New group" create Modal (style guide "Pattern: modal dialog for
  // entity create/rename" — mirrors OrgAdminPage's own "New group" modal,
  // just pointed at the project-scoped endpoint). Unlike the org-scoped
  // equivalent, `ProjectGroupCreate` also requires a role up front — this
  // stays true even though `PATCH .../groups/{id}` (Phase 5,
  // docs/decisions.md) now makes the role correctable afterward: creation
  // still shouldn't be made role-optional too, since a group briefly
  // existing with no role at all would be a meaningless intermediate
  // state — so this modal keeps a role select the org-scoped one doesn't
  // need.
  const [newGroupModalOpen, setNewGroupModalOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupRole, setNewGroupRole] = useState<ProjectRole>("member");
  const [newStageName, setNewStageName] = useState("");
  const [newComponentName, setNewComponentName] = useState("");
  const [newComponentPrefix, setNewComponentPrefix] = useState("");
  // Keyed by component id: each component's own inline "add category" form,
  // since a category is now created nested under one specific component
  // (the tree) rather than at project level.
  const [newCategoryInputs, setNewCategoryInputs] = useState<Record<string, { name: string; prefix: string }>>({});
  const [deadlineInputs, setDeadlineInputs] = useState<Record<string, string>>({});
  const [cascadeInputs, setCascadeInputs] = useState<Record<string, boolean>>({});

  // Rename/delete state for stages/components/categories. Each "edits" map
  // is keyed by item id and only populated once the user actually starts
  // typing — the input's displayed value falls back to the item's own
  // current name/prefix until then, so switching tabs never shows a stale
  // half-typed rename after a reload.
  const [stageNameEdits, setStageNameEdits] = useState<Record<string, string>>({});
  const [deletingStageId, setDeletingStageId] = useState<string | null>(null);
  const [reassignStageTo, setReassignStageTo] = useState("");
  const [componentEdits, setComponentEdits] = useState<Record<string, { name: string; prefix: string }>>({});
  const [deletingComponentId, setDeletingComponentId] = useState<string | null>(null);
  const [categoryEdits, setCategoryEdits] = useState<Record<string, { name: string; prefix: string }>>({});
  const [deletingCategoryId, setDeletingCategoryId] = useState<string | null>(null);
  const [reassignCategoryTo, setReassignCategoryTo] = useState("");
  const [structureError, setStructureError] = useState<string | null>(null);

  const [settingsName, setSettingsName] = useState("");
  const [settingsSummary, setSettingsSummary] = useState("");
  const [allowMemberCr, setAllowMemberCr] = useState(true);
  const [isTemplate, setIsTemplate] = useState(false);
  const [visibility, setVisibility] = useState<"only_specified" | "org_wide">("only_specified");
  const [statusId, setStatusId] = useState("");
  const [orgProjectStatuses, setOrgProjectStatuses] = useState<ProjectStatusDefinition[]>([]);
  const [terminology, setTerminology] = useState<Record<string, string>>({});
  // Hierarchical projects (docs/decisions.md).
  const [parentProjectId, setParentProjectId] = useState("");
  const [roleInheritanceMode, setRoleInheritanceMode] = useState<ProjectRoleInheritanceMode>("none");
  const [roleInheritanceFilterRole, setRoleInheritanceFilterRole] = useState<ProjectRole>("project_manager");
  // Whether *this* project may be selected as a parent for other projects —
  // defaults off; a project's own manager opts in explicitly (see
  // Project.can_be_parent's docstring, docs/decisions.md).
  const [canBeParent, setCanBeParent] = useState(false);
  const [pendingInheritMode, setPendingInheritMode] = useState<ProjectRoleInheritanceMode | null>(null);
  const [orgProjects, setOrgProjects] = useState<ProjectListItem[]>([]);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [memberSources, setMemberSources] = useState<ProjectMemberSource[]>([]);
  const [addSourceId, setAddSourceId] = useState("");
  // Generalized (docs/decisions.md): member sources are no longer
  // restricted to a direct child, and can mirror more than baseline
  // MEMBER — same mode/filter-role vocabulary as the forward
  // (`roleInheritanceMode`/`roleInheritanceFilterRole`) mechanism above,
  // just for the reverse direction.
  const [addMirrorMode, setAddMirrorMode] = useState<ProjectRoleInheritanceMode>("member_only");
  const [addMirrorFilterRole, setAddMirrorFilterRole] = useState<ProjectRole>("project_manager");
  const [effectiveMembers, setEffectiveMembers] = useState<EffectiveMember[] | null>(null);
  const [materializing, setMaterializing] = useState(false);

  // --- Members section (Phase D, follow-up UX batch, 2026-08-31) --------
  // `ProjectMembersTable`'s two data sources — effective members (with
  // provenance) and pending invites, both fetched unpaginated, same
  // "small enough to load whole and let the shared table search/filter/
  // paginate client-side" precedent `MemberRoleTable`'s own two sources
  // set before it. `memberTableGroups` (unrelated to the Members section
  // any more — groups stopped being rows in this table once default
  // groups were removed, Phase C) still exists purely as the Groups
  // section's own lookup source for a deep-linked `?openGroup=` id that
  // isn't on the currently-loaded paginated page (see `openGroupId`
  // below) — kept as-is, untouched by this phase.
  const [memberTableGroups, setMemberTableGroups] = useState<ProjectGroup[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);
  const [resendingInviteId, setResendingInviteId] = useState<string | null>(null);
  const [addMemberRole, setAddMemberRole] = useState<ProjectRole>("member");

  // --- Groups section: per-group SidePanel (Phase 5) ---------------------
  // Replaces the old always-expanded `CollapsibleSection` accordion. A real
  // id, not a boolean, so at most one group's panel is open at a time.
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [deletingGroupId, setDeletingGroupId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // Guards the two field groups above against `reload()` — called after
  // every unrelated mutation on this page (adding/deleting a custom
  // field, stage/component/category CRUD, action-type CRUD, ...; 33 call
  // sites) and not awaited by its callers, so it can still be mid-flight
  // when the user edits and saves one of these forms right after
  // triggering one of those other actions, clobbering the edit back to
  // its last-saved value before Save is even clicked. Same real,
  // CI-reproducible race as OrgAdminPage.tsx's advancedDirtyRef — see its
  // own comment and docs/decisions.md. Separate refs (not one shared
  // guard) since `saveSettings()` and `saveTerminology()` are independent
  // save actions on independent field groups.
  const settingsDirtyRef = useRef(false);
  const terminologyDirtyRef = useRef(false);

  // --- Action types (project-scoped, per docs/decisions.md) ------------
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);

  const [reportIntro, setReportIntro] = useState("");
  const [reportChapters, setReportChapters] = useState<ReportChapter[]>([]);
  const [reportAppendices, setReportAppendices] = useState<ReportChapter[]>([]);
  const [reportConfigDefaults, setReportConfigDefaults] = useState({
    intro: false,
    chapters: false,
    appendices: false,
  });
  const [reportTemplates, setReportTemplates] = useState<ReportTemplate[]>([]);
  const [defaultReportTemplateId, setDefaultReportTemplateId] = useState("");
  // Same reasoning as settingsDirtyRef/terminologyDirtyRef above, for the
  // fields `saveReportConfig()` submits.
  const reportConfigDirtyRef = useRef(false);

  const [customFields, setCustomFields] = useState<CustomFieldDefinition[]>([]);
  const [newFieldKind, setNewFieldKind] = useState<CustomFieldEntityKind>("requirement");
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("short_text");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [newFieldRequired, setNewFieldRequired] = useState(false);
  const [deletingFieldId, setDeletingFieldId] = useState<string | null>(null);

  const GROUPS_PAGE_SIZE = 20;

  async function loadGroups(
    search: string, offset: number, append: boolean, sort: typeof groupSort = groupSort
  ) {
    if (!projectId) return;
    const params = new URLSearchParams({ limit: String(GROUPS_PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (sort) params.set("order", sort.direction);
    const page = await api.getPage<ProjectGroup>(`/api/v1/projects/${projectId}/groups?${params.toString()}`);
    setGroups((prev) => (append ? [...prev, ...page.items] : page.items));
    setGroupsTotal(page.total);
  }

  async function reload() {
    if (!projectId) return;
    const [p, s, c, cat, cf, rc, at] = await Promise.all([
      api.get<Project>(`/api/v1/projects/${projectId}`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields`),
      api.get<ProjectReportConfig>(`/api/v1/projects/${projectId}/report-config`),
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
    ]);
    setProject(p);
    if (!settingsDirtyRef.current) {
      setSettingsName(p.name);
      setSettingsSummary(p.summary);
      setAllowMemberCr(p.allow_member_change_requests);
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
    setComponents(c);
    setCategories(cat);
    await loadGroups(groupSearch, 0, false);
    setCustomFields(cf);
    setActionTypes(at);
    // Group membership (below) only stores user ids — resolving those to
    // an email/display name needs the org's member directory. Any org
    // role (including plain "member") can call this endpoint unfiltered
    // (see `routers/orgs.py::list_org_users`), and project access already
    // implies org membership, so this is safe for whoever can reach this
    // page at all.
    setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`));
    setOrgGroups(await api.get<OrgGroup[]>(`/api/v1/orgs/${p.organization_id}/groups`));
    setReportTemplates(await api.get<ReportTemplate[]>(`/api/v1/orgs/${p.organization_id}/report-templates`));
    setOrgProjectStatuses(await api.get<ProjectStatusDefinition[]>(`/api/v1/orgs/${p.organization_id}/project-statuses`));
    if (!reportConfigDirtyRef.current) {
      setReportIntro(rc.intro);
      setReportChapters(rc.chapters);
      setReportAppendices(rc.appendices);
      setDefaultReportTemplateId(rc.default_report_template_id ?? "");
    }
    setReportConfigDefaults({
      intro: rc.intro_is_organisation_default,
      chapters: rc.chapters_is_organisation_default,
      appendices: rc.appendices_is_organisation_default,
    });

    // Hierarchical projects (docs/decisions.md). Parent selector options
    // are restricted server-side to the caller's own accessible set
    // already (list_projects); this is the same org-wide accessible list
    // ProjectListPage's "New project" modal uses for its own parent field.
    setOrgProjects(await api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&organization_id=${p.organization_id}`));
    setMemberSources(await api.get<ProjectMemberSource[]>(`/api/v1/projects/${projectId}/member-sources`));

    // Groups section's own `?openGroup=` deep-link lookup (unpaginated, no
    // `limit`) — see this state's own declaration comment. Also the source
    // of the Groups section's own "last manager" hint (`directRoleManager
    // SourceCount` below), which needs `effectiveMembers` to already be
    // loaded regardless of which tab is currently open — so, unlike the
    // old lazy "Show members" button this replaced, effective-members and
    // pending invites are fetched eagerly here too, not gated behind first
    // visiting the "members" group.
    setMemberTableGroups(await api.get<ProjectGroup[]>(`/api/v1/projects/${projectId}/groups`));
    await reloadEffectiveMembers();
    await reloadPendingInvites();
  }

  async function reloadEffectiveMembers() {
    if (!projectId) return;
    setEffectiveMembers(await api.get<EffectiveMember[]>(`/api/v1/projects/${projectId}/effective-members`));
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

  async function saveReportConfig() {
    await api.put(`/api/v1/projects/${projectId}/report-config`, {
      intro: reportIntro, chapters: reportChapters, appendices: reportAppendices,
      default_report_template_id: defaultReportTemplateId || null,
    });
    reportConfigDirtyRef.current = false;
    reload();
  }

  async function addCustomField() {
    await api.post(`/api/v1/projects/${projectId}/custom-fields`, {
      entity_kind: newFieldKind,
      name: newFieldName,
      field_type: newFieldType,
      options: newFieldType === "list" ? newFieldOptions.split(",").map((s) => s.trim()).filter(Boolean) : null,
      required: newFieldRequired,
    });
    setNewFieldName("");
    setNewFieldOptions("");
    setNewFieldRequired(false);
    reload();
  }

  async function deleteCustomField(fieldId: string) {
    await api.delete(`/api/v1/projects/${projectId}/custom-fields/${fieldId}`);
    reload();
  }

  async function saveSettings() {
    setSettingsError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}`, {
        name: settingsName, summary: settingsSummary,
        allow_member_change_requests: allowMemberCr, is_template: isTemplate,
        visibility, status_id: statusId || null,
        parent_project_id: parentProjectId || null,
        role_inheritance_mode: roleInheritanceMode,
        role_inheritance_filter_role: roleInheritanceMode === "mirror_role" ? roleInheritanceFilterRole : null,
        can_be_parent: canBeParent,
      });
      settingsDirtyRef.current = false;
      reload();
    } catch (err) {
      // Surfaces the C-U-08 ("only manager is inherited") and
      // parent_required ("must remain nested under a parent") 400s from
      // update_project inline, the same way other save-time validation in
      // this form already is.
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

  // can_be_parent-gated (docs/decisions.md) — but the project's *currently*
  // attached parent always stays selectable even if its own eligibility was
  // since turned off, so an already-established relationship never renders
  // as an unselectable/blank value.
  const parentOptions = orgProjects.filter(
    (p) => !p.is_archived && p.id !== projectId && (p.can_be_parent || p.id === parentProjectId),
  );
  const selectedParent = orgProjects.find((p) => p.id === parentProjectId);
  // Nothing to show: no eligible candidate to pick, and no parent currently
  // set to display/manage — matches this project's own "don't render a
  // field with nothing meaningful in it" principle (see docs/decisions.md's
  // visibility-boundary rule for the analogous "Child of:"/"Parent of:"
  // labels).
  const showParentField = parentOptions.length > 0 || parentProjectId !== "";
  // Generalized: any other project in the organisation is a valid source,
  // not just a direct child — see docs/decisions.md. `orgProjects` is
  // already the full org project list (used above for the parent picker).
  const sourceCandidates = orgProjects.filter(
    (p) => !p.is_archived && p.id !== projectId && !memberSources.some((ms) => ms.source_project_id === p.id),
  );

  async function addMemberSource() {
    if (!addSourceId) return;
    await api.post(`/api/v1/projects/${projectId}/member-sources`, {
      source_project_id: addSourceId, mirror_mode: addMirrorMode,
      mirror_filter_role: addMirrorMode === "mirror_role" ? addMirrorFilterRole : null,
    });
    setAddSourceId("");
    setAddMirrorMode("member_only");
    reload();
  }

  async function removeMemberSource(sourceProjectId: string) {
    await api.delete(`/api/v1/projects/${projectId}/member-sources/${sourceProjectId}`);
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
    await api.put(`/api/v1/projects/${projectId}/terminology`, { terminology });
    terminologyDirtyRef.current = false;
    reload();
  }

  async function toggleArchive() {
    const action = project?.is_archived ? "unarchive" : "archive";
    await api.post(`/api/v1/projects/${projectId}/${action}`);
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
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function addStage() {
    if (!newStageName.trim()) return;
    await api.post(`/api/v1/projects/${projectId}/stages`, { name: newStageName });
    setNewStageName("");
    reload();
  }

  async function startStageReview(stageId: string) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/transition?new_status=review`);
    reload();
  }

  async function approveStage(stageId: string) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/transition?new_status=approved`);
    reload();
  }

  async function setReviewDeadline(stageId: string, isoDeadline: string) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-deadline`, {
      review_deadline: isoDeadline || null,
    });
    reload();
  }

  async function respondToStageReview(stageId: string, response: "approved" | "rejected") {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/review-response`, { response });
    reload();
  }

  async function completeStage(stageId: string, cascade: boolean) {
    await api.post(`/api/v1/projects/${projectId}/stages/${stageId}/complete`, { cascade_to_requirements: cascade });
    reload();
  }

  async function addComponent() {
    await api.post(`/api/v1/projects/${projectId}/components`, { name: newComponentName, prefix: newComponentPrefix });
    setNewComponentName("");
    setNewComponentPrefix("");
    reload();
  }

  async function addCategory(componentId: string) {
    const input = newCategoryInputs[componentId];
    if (!input?.name || !input?.prefix) return;
    await api.post(`/api/v1/projects/${projectId}/categories`, {
      name: input.name, prefix: input.prefix, component_id: componentId,
    });
    setNewCategoryInputs((m) => ({ ...m, [componentId]: { name: "", prefix: "" } }));
    reload();
  }

  async function moveComponent(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/components/${id}/move`, { direction });
    reload();
  }

  async function moveCategory(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/categories/${id}/move`, { direction });
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
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function deleteStage(stageId: string) {
    if (!reassignStageTo) return;
    setStructureError(null);
    try {
      await api.delete(`/api/v1/projects/${projectId}/stages/${stageId}?reassign_to=${reassignStageTo}`);
      setDeletingStageId(null);
      setReassignStageTo("");
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function renameComponent(componentId: string, name: string, prefix: string) {
    setStructureError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}/components/${componentId}`, { name, prefix });
      setComponentEdits((m) => {
        const next = { ...m };
        delete next[componentId];
        return next;
      });
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function deleteComponent(componentId: string) {
    setStructureError(null);
    try {
      await api.delete(`/api/v1/projects/${projectId}/components/${componentId}`);
      setDeletingComponentId(null);
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function renameCategory(categoryId: string, name: string, prefix: string) {
    setStructureError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}/categories/${categoryId}`, { name, prefix });
      setCategoryEdits((m) => {
        const next = { ...m };
        delete next[categoryId];
        return next;
      });
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function deleteCategory(categoryId: string) {
    if (!reassignCategoryTo) return;
    setStructureError(null);
    try {
      await api.delete(`/api/v1/projects/${projectId}/categories/${categoryId}?reassign_to=${reassignCategoryTo}`);
      setDeletingCategoryId(null);
      setReassignCategoryTo("");
      reload();
    } catch (err) {
      setStructureError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function addActionType(name: string) {
    await api.post(`/api/v1/projects/${projectId}/action-types`, { name });
    reload();
  }

  async function moveActionType(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/action-types/${id}/move`, { direction });
    reload();
  }

  async function renameActionType(id: string, name: string) {
    await api.patch(`/api/v1/projects/${projectId}/action-types/${id}`, { name });
    reload();
  }

  /** Plain delete first (no `reassign_to_id`) per §4.0's shared contract —
   * a 409 means it's in use; `DefinitionList` opens the reassignment
   * picker itself with the server's own count message (mirrors
   * OrgAdminPage's project-statuses/link-types delete flow). */
  async function deleteActionType(id: string, reassignToId?: string) {
    await api.delete(`/api/v1/projects/${projectId}/action-types/${id}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`);
    reload();
  }

  /** Creates a new project group with `newGroupName`/`newGroupRole` — the
   * frontend gap the 2026-08 UX audit flagged (Groups tab could manage
   * membership but had no create form at all). `POST
   * /projects/{id}/groups` already existed and required no backend change. */
  function handleGroupSearchChange(value: string) {
    setGroupSearch(value);
    loadGroups(value, 0, false);
  }

  /** Backend-sorted refetch — see `groupSort`'s own declaration comment
   * for why this isn't a client-side sort of only the loaded page. */
  function applyGroupSort(key: ProjectGroupSortKey) {
    const next = cycleSort(groupSort, key);
    setGroupSort(next);
    loadGroups(groupSearch, 0, false, next);
  }

  async function createProjectGroup() {
    try {
      await api.post(`/api/v1/projects/${projectId}/groups`, { name: newGroupName, role: newGroupRole });
      setNewGroupName("");
      setNewGroupRole("member");
      setNewGroupModalOpen(false);
      showToast(strings.admin.groupCreated);
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

  /** Adds someone found via UserAutocomplete's external-search result (not
   * yet a member of this project's organisation, possibly no account at
   * all) directly to the project with `role` — the by-email counterpart to
   * `addGroupMember`. Grants a *direct* project role rather than group
   * membership (the group's own `role` is used so the effective access
   * matches what joining the group would have granted), since the by-email
   * endpoint has no notion of "this specific group" — see
   * `routers/projects.py::assign_project_role_by_email`. */
  async function addExternalMember(email: string, role: string) {
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
      setExternalAddResult({
        message: err instanceof ApiError ? err.message : strings.admin.externalAddError,
        isError: true,
      });
    }
  }

  async function removeGroupMember(groupId: string, userId: string) {
    await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${userId}`);
    reload();
  }

  async function addOrgGroupMember(groupId: string, orgGroupId: string) {
    await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { org_group_id: orgGroupId });
    setOrgGroupSelections((prev) => ({ ...prev, [groupId]: "" }));
    reload();
  }

  async function removeOrgGroupMember(groupId: string, orgGroupId: string) {
    await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${orgGroupId}`);
    reload();
  }

  // "This group's members = that project's own direct members" (see
  // models.project.ProjectGroupMember.source_project_id's docstring).
  // Authorized purely by managing *this* project, same as every other
  // group-membership mutation on this page — no consent needed from the
  // referenced project, mirroring the member-source mechanism above.
  async function addProjectRefMember(groupId: string, sourceProjectId: string) {
    await api.post(`/api/v1/projects/${projectId}/groups/${groupId}/members`, { source_project_id: sourceProjectId });
    setSourceProjectSelections((prev) => ({ ...prev, [groupId]: "" }));
    reload();
  }

  async function removeProjectRefMember(groupId: string, sourceProjectId: string) {
    await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}/members/${sourceProjectId}`);
    reload();
  }

  // --- Members section handlers (Phase 5, docs/decisions.md) ------------

  /** Toggles one direct role on an effective member (`ProjectMembersTable`'s
   * own `onToggleRole` — only ever called for an option whose sole source
   * is `direct_role`, per that component's own contract). Re-fetches just
   * `effective-members` afterward, not the full page `reload()` — a single,
   * light endpoint, unlike the old `MemberRoleTable`-era local-state patch
   * this replaces, and correctly recomputes both the toggled member's
   * `sources` and every other member's own "last manager" hint in one
   * request rather than hand-patching local state (a real, previously-easy-
   * to-get-wrong-in-edge-cases risk `MemberRoleTable`'s own local-patch
   * approach ran, e.g. `effective_role` going stale after a toggle). */
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

  /** Grants a brand-new direct role — the Members section's own
   * `addControl` (an existing-org-member `UserAutocomplete` result; the
   * external-invite branch reuses `addExternalMember` below unchanged,
   * since `assign_project_role_by_email` already grants a *direct* role,
   * not group membership). */
  async function addProjectMember(userId: string) {
    await api.post(`/api/v1/projects/${projectId}/roles`, { user_id: userId, role: addMemberRole });
    await reloadEffectiveMembers();
  }

  /** Changes a project group's granted role (`PATCH .../groups/{id}`,
   * Phase 5) — the fix for "project groups' role was fixed at creation,
   * making add-then-assign impossible." Only the Groups section's own
   * per-group `SidePanel` role `<select>` calls this any more (Phase D
   * removed groups as rows from the Members table entirely). Updates both
   * `memberTableGroups` (still the Groups section's own `?openGroup=`
   * lookup source) and `groups` (if this group happens to be on the
   * currently-loaded page) locally on success. */
  async function changeGroupRole(groupId: string, role: ProjectRole) {
    try {
      const updated = await api.patch<ProjectGroup>(`/api/v1/projects/${projectId}/groups/${groupId}`, { role });
      setMemberTableGroups((prev) => prev.map((g) => (g.id === groupId ? updated : g)));
      setGroups((prev) => prev.map((g) => (g.id === groupId ? updated : g)));
      showToast(strings.admin.groupUpdated);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Same client-side "last manager" hint `ProjectMembersTable` computes
  // internally from its own `members` prop (see that component's
  // docstring) — recomputed here too since the Groups section's per-group
  // `SidePanel` role `<select>` (below) needs an equivalent count for its
  // own disabled state, outside of `ProjectMembersTable` itself. Matches
  // exactly what the retired `MemberRoleTable`-era `memberRoleRows` used to
  // count (every project-manager-role group, plus every direct-role-kind
  // project-manager grant) — just recombined from the two state arrays
  // that used to feed that merged row list, now that Members no longer
  // merges them into one.
  const groupManagerSourceCount =
    memberTableGroups.filter((g) => g.role === "project_manager").length +
    (effectiveMembers ?? []).filter((m) => m.sources.some((s) => s.role === "project_manager" && s.kind === "direct_role")).length;

  // Consolidated from 8 tabs to 5 (2026-08 UX audit roadmap — "Revisit
  // Project Admin's 8-tab bar against the 5-tab ceiling"). Terminology's
  // content moved into Overview (a sub-block, not its own group); Stages +
  // Components/Categories merged into Structure; Custom Fields + Action
  // Types merged into Fields & Actions; Groups and Report Setup keep their
  // own groups unchanged. See `docs/decisions.md` for the full rationale —
  // including the later reversal from `Tabs` to `ResourceMenu` recorded
  // above `ProjectAdminGroupKey`, and Phase 5's later "groups" -> "members"
  // + "groups" split recorded there too.
  const activeGroup: ProjectAdminGroupKey = PROJECT_ADMIN_GROUP_KEYS.includes(groupParam as ProjectAdminGroupKey)
    ? (groupParam as ProjectAdminGroupKey)
    : "overview";

  // --- Groups section: per-group SidePanel + ?openGroup= deep link -------
  // (Phase 5, docs/decisions.md) — "click a group in Members, see its
  // members" is a real URL, not client-only state, matching `ResourceMenu`'s
  // own bookmarkability principle one level deeper (see that component's
  // own docstring/comment for the framing this reuses). `memberTableGroups`
  // (unpaginated) is searched first, not the Groups section's own paginated
  // `groups`, so a deep-linked group not on the currently-loaded page is
  // still found.
  useEffect(() => {
    if (activeGroup !== "groups") return;
    const openGroupParam = searchParams.get("openGroup");
    if (!openGroupParam) return;
    setOpenGroupId(openGroupParam);
    const next = new URLSearchParams(searchParams);
    next.delete("openGroup");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroup, searchParams]);

  async function deleteGroup(groupId: string) {
    try {
      await api.delete(`/api/v1/projects/${projectId}/groups/${groupId}`);
      setDeletingGroupId(null);
      if (openGroupId === groupId) setOpenGroupId(null);
      showToast(strings.admin.groupDeleted);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (!stages || !project) return <Spinner />;

  // Project Groups `DirectoryTable` retrofit (Phase B, follow-up UX batch,
  // 2026-08-31) — replaces the old `<button style={{width:"100%"}}>` per
  // row (no `SortableHeader`, not a real `<table>`) with the same shared
  // shell Org Groups now uses too. `groups` is already sorted server-side
  // (`applyGroupSort`/`loadGroups`'s `order` param), no client-side
  // re-sort needed.
  const projectGroupColumns: DirectoryColumn<ProjectGroup>[] = [
    {
      key: "name", label: strings.admin.name, sortable: true,
      render: (g) => g.name,
    },
    { key: "role", label: strings.admin.groupRole, render: (g) => <span className="badge">{PROJECT_ROLE_LABEL[g.role]}</span> },
    {
      key: "members", label: strings.admin.groupMembersColumn,
      render: (g) => strings.admin.memberCount(g.member_user_ids.length),
    },
  ];

  // Title is rendered by the header row below, not `ResourceMenu`'s own
  // `title` prop — this page already has other page chrome (the "Add
  // sub-project" button alongside the h1), unlike Org Admin's plain
  // title-only header, so passing `project.name` into `ResourceMenu` too
  // would duplicate it.
  const projectAdminGroups: ResourceMenuGroupDef<ProjectAdminGroupKey>[] = [
    { key: "overview", label: strings.admin.settings, href: `/projects/${projectId}/admin/overview` },
    { key: "structure", label: strings.admin.structure, href: `/projects/${projectId}/admin/structure` },
    { key: "fieldsActions", label: strings.admin.fieldsAndActions, href: `/projects/${projectId}/admin/fieldsActions` },
    { key: "members", label: strings.admin.membersNav, href: `/projects/${projectId}/admin/members` },
    { key: "groups", label: strings.admin.groups, href: `/projects/${projectId}/admin/groups` },
    { key: "reportSetup", label: strings.admin.reportSetup, href: `/projects/${projectId}/admin/reportSetup` },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: "0.15rem" }}>
          <h1 style={{ margin: 0 }}>{project.name}</h1>
          <p className="text-muted" style={{ margin: 0 }}>{strings.nav.admin}</p>
        </div>
        {/* "Add sub-project" (decision 8, docs/decisions.md) — the
            create-project flow itself lives on ProjectListPage, so this
            navigates there with the parent pre-filled/locked rather than
            duplicating that modal's logic here. Disabled until this
            project has opted in to being a parent (can_be_parent) — the
            saved server value, not the settings tab's own possibly-
            unsaved checkbox edit, since a click here leads straight to a
            create flow the backend would otherwise reject. */}
        <button
          className="btn"
          disabled={!project.can_be_parent}
          title={project.can_be_parent ? undefined : strings.admin.canBeParentHint}
          onClick={() => navigate(`/projects?parentProjectId=${project.id}&organizationId=${project.organization_id}`)}
        >
          <Plus size={14} /> {strings.projects.addSubProject}
        </button>
      </div>

      <ResourceMenu ariaLabel={strings.admin.sectionsNav} groups={projectAdminGroups} active={activeGroup}>

      {activeGroup === "overview" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.settings}</h2>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.name}
          <input
            className="input"
            value={settingsName}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setSettingsName(e.target.value);
            }}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.summary}
          <textarea
            className="input"
            rows={2}
            value={settingsSummary}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setSettingsSummary(e.target.value);
            }}
          />
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={allowMemberCr}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setAllowMemberCr(e.target.checked);
            }}
          />
          {strings.admin.allowMemberChangeRequests}
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={isTemplate}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setIsTemplate(e.target.checked);
            }}
          />
          {strings.admin.isTemplate}
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.visibility}
          <select
            className="input"
            value={visibility}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setVisibility(e.target.value as "only_specified" | "org_wide");
            }}
          >
            <option value="only_specified">{strings.admin.visibilityOnlySpecified}</option>
            <option value="org_wide">{strings.admin.visibilityOrgWide}</option>
          </select>
        </label>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>{strings.admin.visibilityHint(orgLabel)}</p>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.admin.projectStatus}
          <select
            className="input"
            value={statusId}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setStatusId(e.target.value);
            }}
          >
            {orgProjectStatuses.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>

        {/* Hierarchical projects (docs/decisions.md). Always visible
            regardless of whether this project currently has (or could
            have) a parent of its own — it's the opt-in mechanism other
            projects' managers need before this project appears in *their*
            "Parent project" picker at all. */}
        <label className="row">
          <input
            type="checkbox"
            checked={canBeParent}
            onChange={(e) => {
              settingsDirtyRef.current = true;
              setCanBeParent(e.target.checked);
            }}
          />
          {strings.admin.canBeParent}
        </label>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>{strings.admin.canBeParentHint}</p>
        {/* The current parent's name is always shown plainly here (unlike
            ProjectListPage's list/tile "Child of:" label, which redacts a
            parent the viewer can't see) — a project's own manager needs to
            see and manage this relationship to do their job, and already
            holds the highest level of authority over it. Rely on the
            server-side cycle check rather than excluding descendants
            client-side. Hidden entirely when there's nothing eligible to
            pick and no parent currently set — an empty "Parent project"
            picker with only "None" in it is confusing, not useful. */}
        {showParentField && (
          <>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.projects.parentProject}
              <select
                className="input"
                value={parentProjectId}
                onChange={(e) => {
                  settingsDirtyRef.current = true;
                  setParentProjectId(e.target.value);
                  // Changing the parent while an elevated inheritance mode is
                  // set must not silently carry that mode's confirmation over
                  // to a *different* parent's role-holders — reset to "none"
                  // (the safe default) so re-selecting MIRROR_ALL/MIRROR_ROLE
                  // for the new parent goes back through
                  // requestInheritModeChange's own confirmation dialog, which
                  // will then correctly name the new parent.
                  if (MODES_NEEDING_CONFIRMATION.includes(roleInheritanceMode)) {
                    setRoleInheritanceMode("none");
                  }
                }}
              >
                <option value="">{strings.projects.noParent}</option>
                {parentOptions.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
            {parentProjectId && (
              <>
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.projects.inheritFromParent}
                  <select
                    className="input"
                    value={roleInheritanceMode}
                    onChange={(e) => requestInheritModeChange(e.target.value as ProjectRoleInheritanceMode)}
                  >
                    {(Object.keys(PROJECT_ROLE_INHERITANCE_MODE_LABEL) as ProjectRoleInheritanceMode[]).map((m) => (
                      <option key={m} value={m}>{PROJECT_ROLE_INHERITANCE_MODE_LABEL[m]}</option>
                    ))}
                  </select>
                </label>
                {roleInheritanceMode === "mirror_role" && (
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.projects.inheritModeFilterRole}
                    <select
                      className="input"
                      value={roleInheritanceFilterRole}
                      onChange={(e) => {
                        settingsDirtyRef.current = true;
                        setRoleInheritanceFilterRole(e.target.value as ProjectRole);
                      }}
                    >
                      <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                      <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                      <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                    </select>
                  </label>
                )}
              </>
            )}
          </>
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

        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <button className="btn btn-primary" onClick={saveSettings}>
              {strings.admin.saveSettings}
            </button>
            <button className="btn" onClick={exportProject} disabled={exporting} title={strings.admin.exportProjectHint(orgLabel)}>
              <Download size={16} /> {exporting ? "Exporting…" : strings.admin.exportProject}
            </button>
          </div>
          <button className="btn btn-danger" onClick={toggleArchive}>
            {project.is_archived ? strings.admin.unarchiveProject : strings.admin.archiveProject}
          </button>
        </div>

        {/* Terminology (2026-08 UX audit roadmap: Project Admin's 8 tabs ->
            5) — pure relocation of the previously-standalone Terminology
            tab's own JSX/state/handlers into Overview, unchanged. The
            architecture that would make custom terms actually take effect
            across the app is a separate, deliberately-deferred roadmap
            item (see docs/decisions.md); this is only where its existing
            (still mostly-inert) UI lives now. */}
        <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)", margin: "0.25rem 0" }} />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.terminology}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.terminologyHint}</p>
        {TERMINOLOGY_KEYS.map((key) => (
          <div key={key} className="row">
            <span style={{ minWidth: 140 }}>{strings.admin.terminologyKeyLabel[key]}</span>
            <input
              className="input"
              placeholder={key}
              value={terminology[key] ?? ""}
              onChange={(e) => {
                terminologyDirtyRef.current = true;
                setTerminology((t2) => ({ ...t2, [key]: e.target.value }));
              }}
            />
          </div>
        ))}
        <button className="btn btn-primary" onClick={saveTerminology} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveTerminology}
        </button>

        {/* Member sources (docs/decisions.md) — the reverse (source ->
            receiving) RBAC mechanism, deliberately NOT a field on the
            source's own form: authorized entirely by managing *this*
            project (the receiving side), never the source. Generalized
            beyond direct children to any same-organisation project, and
            beyond baseline Member to mirror_mode/mirror_filter_role — same
            mode vocabulary and confirmation posture as the forward
            (Inherit from parent) controls above: no confirmation needed on
            "Member only" (same risk profile as visibility=org_wide), but
            "Mirror all roles"/"Mirror one role" can convey a real elevated
            role, same as the forward mechanism's own modes. */}
        <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)", margin: "0.25rem 0" }} />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.memberSources}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.admin.memberSourcesHint}</p>
        {memberSources.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
            {memberSources.map((ms) => (
              <li key={ms.source_project_id} className="row" style={{ justifyContent: "space-between", listStyle: "disc" }}>
                <span className="row" style={{ gap: "0.5rem" }}>
                  <Link to={`/projects/${ms.source_project_id}`}>{ms.source_project_name}</Link>
                  <span className="badge">
                    {ms.mirror_mode === "mirror_role" && ms.mirror_filter_role
                      ? strings.admin.memberSourceModeRole(PROJECT_ROLE_LABEL[ms.mirror_filter_role])
                      : PROJECT_ROLE_INHERITANCE_MODE_LABEL[ms.mirror_mode]}
                  </span>
                </span>
                <button className="btn" onClick={() => removeMemberSource(ms.source_project_id)}>
                  {strings.admin.removeMemberSource}
                </button>
              </li>
            ))}
          </ul>
        )}
        {sourceCandidates.length > 0 ? (
          <div className="row" style={{ flexWrap: "wrap" }}>
            <select
              className="input" style={{ maxWidth: 280 }} value={addSourceId}
              aria-label={strings.admin.memberSourceProjectSelect}
              onChange={(e) => setAddSourceId(e.target.value)}
            >
              <option value="">{strings.common.selectOption}</option>
              {sourceCandidates.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <select
              className="input" style={{ maxWidth: 200 }} value={addMirrorMode}
              aria-label={strings.admin.memberSourceModeSelect}
              onChange={(e) => setAddMirrorMode(e.target.value as ProjectRoleInheritanceMode)}
            >
              {(Object.keys(PROJECT_ROLE_INHERITANCE_MODE_LABEL) as ProjectRoleInheritanceMode[])
                .filter((m) => m !== "none")
                .map((m) => (
                  <option key={m} value={m}>{PROJECT_ROLE_INHERITANCE_MODE_LABEL[m]}</option>
                ))}
            </select>
            {addMirrorMode === "mirror_role" && (
              <select
                className="input" style={{ maxWidth: 200 }} value={addMirrorFilterRole}
                aria-label={strings.admin.memberSourceFilterRoleSelect}
                onChange={(e) => setAddMirrorFilterRole(e.target.value as ProjectRole)}
              >
                <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
              </select>
            )}
            <button className="btn" onClick={addMemberSource} disabled={!addSourceId}>
              {strings.admin.addMemberSource}
            </button>
          </div>
        ) : (
          memberSources.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.admin.noChildrenToAdd}</p>
        )}
      </div>
      )}

      {activeGroup === "structure" && (
      <div className="stack">
        {structureError && <div style={{ color: "var(--color-danger)" }}>{structureError}</div>}
        <CollapsibleSection sectionKey="projectAdmin.structure.stages" title={strings.admin.stages} defaultCollapsed={false}>
        {stages.map((s) => {
          const nameEdit = stageNameEdits[s.id] ?? s.name;
          const otherStages = stages.filter((other) => other.id !== s.id);
          return (
          <div key={s.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="row">
                <input
                  className="input" style={{ maxWidth: 220 }} value={nameEdit}
                  onChange={(e) => setStageNameEdits((m) => ({ ...m, [s.id]: e.target.value }))}
                />
                {nameEdit !== s.name && nameEdit && (
                  <button
                    className="btn"
                    onClick={() => renameStage(s.id, nameEdit)}
                    title={strings.admin.rename}
                    aria-label={strings.admin.rename}
                  >
                    <Pencil size={14} />
                  </button>
                )}
                <span className="badge">{STAGE_STATUS_LABEL[s.status]}</span>
                {s.review_deadline && <span className="badge">{strings.admin.reviewDeadline}: {new Date(s.review_deadline).toLocaleString()}</span>}
                {s.completed_at && <span className="badge">{strings.admin.stageCompletedAt}: {new Date(s.completed_at).toLocaleDateString()}</span>}
                <button
                  className="btn btn-danger"
                  disabled={otherStages.length === 0}
                  title={otherStages.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteStage}
                  aria-label={otherStages.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteStage}
                  onClick={() => setDeletingStageId(s.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
              {s.status === "scoping" && (
                <button className="btn" onClick={() => startStageReview(s.id)}>
                  {strings.admin.startReview}
                </button>
              )}
              {s.status === "review" && (
                <button className="btn" onClick={() => approveStage(s.id)}>
                  <Check size={14} /> {strings.admin.approveStage}
                </button>
              )}
              {s.status === "approved" && (
                <div className="row">
                  <label className="row" style={{ gap: "0.25rem" }}>
                    <input
                      type="checkbox" checked={cascadeInputs[s.id] ?? false}
                      onChange={(e) => setCascadeInputs((c) => ({ ...c, [s.id]: e.target.checked }))}
                    />
                    {strings.admin.cascadeToRequirements}
                  </label>
                  <button className="btn" onClick={() => completeStage(s.id, cascadeInputs[s.id] ?? false)}>
                    {strings.admin.completeStage}
                  </button>
                </div>
              )}
            </div>
            {s.status === "review" && (
              <div className="row">
                <input
                  className="input" type="datetime-local" style={{ maxWidth: 220 }}
                  value={deadlineInputs[s.id] ?? ""}
                  onChange={(e) => setDeadlineInputs((d) => ({ ...d, [s.id]: e.target.value }))}
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
            {deletingStageId === s.id && (
              <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                <span>{strings.admin.reassignExistingTo}</span>
                <select className="input" style={{ maxWidth: 220 }} value={reassignStageTo} onChange={(e) => setReassignStageTo(e.target.value)}>
                  <option value="">—</option>
                  {otherStages.map((other) => (
                    <option key={other.id} value={other.id}>{other.name}</option>
                  ))}
                </select>
                <button className="btn btn-danger" disabled={!reassignStageTo} onClick={() => deleteStage(s.id)}>
                  {strings.admin.confirmDelete}
                </button>
                <button className="btn" onClick={() => { setDeletingStageId(null); setReassignStageTo(""); }}>
                  {strings.common.cancel}
                </button>
              </div>
            )}
          </div>
          );
        })}
        <div className="row">
          <input
            className="input" placeholder={strings.admin.name} value={newStageName}
            onChange={(e) => setNewStageName(e.target.value)}
          />
          <button className="btn btn-primary" onClick={addStage} disabled={!newStageName.trim()}>
            <Plus size={14} /> {strings.admin.newStage}
          </button>
        </div>
        </CollapsibleSection>

        {/* Audit finding: the tab bar used to call this "Categories" while
            its content opened with an <h2> reading "Components" — actually
            a two-level component -> category tree. This section's own
            title now names both levels accurately instead of either alone. */}
        <CollapsibleSection sectionKey="projectAdmin.structure.componentsCategories" title={strings.admin.componentsAndCategories} defaultCollapsed={false}>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.admin.componentTreeHint}</p>
        {components.map((c, idx) => {
          const ownCategories = categories.filter((cat) => cat.component_id === c.id);
          const categoryInput = newCategoryInputs[c.id] ?? { name: "", prefix: "" };
          const componentEdit = componentEdits[c.id] ?? { name: c.name, prefix: c.prefix };
          const componentDirty = componentEdit.name !== c.name || componentEdit.prefix !== c.prefix;
          const otherComponents = components.filter((other) => other.id !== c.id);
          return (
            <div key={c.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.75rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <input
                    className="input" style={{ maxWidth: 180 }} value={componentEdit.name}
                    onChange={(e) => setComponentEdits((m) => ({ ...m, [c.id]: { ...componentEdit, name: e.target.value } }))}
                  />
                  <input
                    className="input" style={{ maxWidth: 80 }} value={componentEdit.prefix}
                    onChange={(e) => setComponentEdits((m) => ({ ...m, [c.id]: { ...componentEdit, prefix: e.target.value.toUpperCase() } }))}
                  />
                  {componentDirty && componentEdit.name && componentEdit.prefix && (
                    <button
                      className="btn"
                      title={strings.admin.rename}
                      aria-label={strings.admin.rename}
                      onClick={() => renameComponent(c.id, componentEdit.name, componentEdit.prefix)}
                    >
                      <Pencil size={14} />
                    </button>
                  )}
                </div>
                <div className="row">
                  <button
                    className="btn"
                    disabled={idx === 0}
                    title={strings.common.up}
                    aria-label={strings.common.up}
                    onClick={() => moveComponent(c.id, "up")}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    className="btn"
                    disabled={idx === components.length - 1}
                    title={strings.common.down}
                    aria-label={strings.common.down}
                    onClick={() => moveComponent(c.id, "down")}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    className="btn btn-danger"
                    disabled={ownCategories.length > 0 || otherComponents.length === 0}
                    title={
                      ownCategories.length > 0
                        ? strings.admin.deleteComponentHasCategoriesHint
                        : otherComponents.length === 0
                        ? strings.admin.deleteLastOneHint
                        : strings.admin.deleteComponent
                    }
                    aria-label={
                      ownCategories.length > 0
                        ? strings.admin.deleteComponentHasCategoriesHint
                        : otherComponents.length === 0
                        ? strings.admin.deleteLastOneHint
                        : strings.admin.deleteComponent
                    }
                    onClick={() => setDeletingComponentId(c.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {deletingComponentId === c.id && (
                <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                  <span>{strings.admin.confirmDelete}?</span>
                  <button className="btn btn-danger" onClick={() => deleteComponent(c.id)}>
                    {strings.admin.confirmDelete}
                  </button>
                  <button className="btn" onClick={() => setDeletingComponentId(null)}>
                    {strings.common.cancel}
                  </button>
                </div>
              )}
              <div className="stack" style={{ paddingLeft: "1.5rem", gap: "0.4rem" }}>
                {ownCategories.map((cat, catIdx) => {
                  const categoryEdit = categoryEdits[cat.id] ?? { name: cat.name, prefix: cat.prefix };
                  const categoryDirty = categoryEdit.name !== cat.name || categoryEdit.prefix !== cat.prefix;
                  const otherCategories = categories.filter((other) => other.id !== cat.id);
                  return (
                  <div key={cat.id} className="stack" style={{ gap: "0.3rem" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="row">
                        <input
                          className="input" style={{ maxWidth: 180 }} value={categoryEdit.name}
                          onChange={(e) => setCategoryEdits((m) => ({ ...m, [cat.id]: { ...categoryEdit, name: e.target.value } }))}
                        />
                        <input
                          className="input" style={{ maxWidth: 80 }} value={categoryEdit.prefix}
                          onChange={(e) => setCategoryEdits((m) => ({ ...m, [cat.id]: { ...categoryEdit, prefix: e.target.value.toUpperCase() } }))}
                        />
                        {categoryDirty && categoryEdit.name && categoryEdit.prefix && (
                          <button
                            className="btn"
                            title={strings.admin.rename}
                            aria-label={strings.admin.rename}
                            onClick={() => renameCategory(cat.id, categoryEdit.name, categoryEdit.prefix)}
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                      </div>
                      <div className="row">
                        <button
                          className="btn"
                          disabled={catIdx === 0}
                          title={strings.common.up}
                          aria-label={strings.common.up}
                          onClick={() => moveCategory(cat.id, "up")}
                        >
                          <ArrowUp size={14} />
                        </button>
                        <button
                          className="btn"
                          disabled={catIdx === ownCategories.length - 1}
                          title={strings.common.down}
                          aria-label={strings.common.down}
                          onClick={() => moveCategory(cat.id, "down")}
                        >
                          <ArrowDown size={14} />
                        </button>
                        <button
                          className="btn btn-danger"
                          disabled={otherCategories.length === 0}
                          title={otherCategories.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteCategory}
                          aria-label={otherCategories.length === 0 ? strings.admin.deleteLastOneHint : strings.admin.deleteCategory}
                          onClick={() => setDeletingCategoryId(cat.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                    {deletingCategoryId === cat.id && (
                      <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                        <span>{strings.admin.reassignExistingTo}</span>
                        <select className="input" style={{ maxWidth: 260 }} value={reassignCategoryTo} onChange={(e) => setReassignCategoryTo(e.target.value)}>
                          <option value="">—</option>
                          {otherCategories.map((other) => {
                            const otherComponent = components.find((comp) => comp.id === other.component_id);
                            return (
                              <option key={other.id} value={other.id}>
                                {otherComponent ? `${otherComponent.name} / ` : ""}{other.name}
                              </option>
                            );
                          })}
                        </select>
                        <button className="btn btn-danger" disabled={!reassignCategoryTo} onClick={() => deleteCategory(cat.id)}>
                          {strings.admin.confirmDelete}
                        </button>
                        <button className="btn" onClick={() => { setDeletingCategoryId(null); setReassignCategoryTo(""); }}>
                          {strings.common.cancel}
                        </button>
                      </div>
                    )}
                  </div>
                  );
                })}
                <div className="row">
                  <input
                    className="input"
                    placeholder={strings.admin.name}
                    value={categoryInput.name}
                    onChange={(e) => setNewCategoryInputs((m) => ({ ...m, [c.id]: { ...categoryInput, name: e.target.value } }))}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 100 }}
                    placeholder={strings.admin.prefix}
                    value={categoryInput.prefix}
                    onChange={(e) =>
                      setNewCategoryInputs((m) => ({ ...m, [c.id]: { ...categoryInput, prefix: e.target.value.toUpperCase() } }))
                    }
                  />
                  <button
                    className="btn"
                    onClick={() => addCategory(c.id)}
                    disabled={!categoryInput.name || !categoryInput.prefix}
                  >
                    <Plus size={14} /> {strings.admin.newCategory}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        <div className="row">
          <input className="input" placeholder={strings.admin.name} value={newComponentName} onChange={(e) => setNewComponentName(e.target.value)} />
          <input
            className="input"
            style={{ maxWidth: 100 }}
            placeholder={strings.admin.prefix}
            value={newComponentPrefix}
            onChange={(e) => setNewComponentPrefix(e.target.value.toUpperCase())}
          />
          <button className="btn btn-primary" onClick={addComponent} disabled={!newComponentName || !newComponentPrefix}>
            <Plus size={14} /> {strings.admin.newComponent}
          </button>
        </div>
        </CollapsibleSection>
      </div>
      )}

      {activeGroup === "fieldsActions" && (
      <div className="stack">
        <CollapsibleSection sectionKey="projectAdmin.fieldsActions.customFields" title={strings.admin.customFields} defaultCollapsed={false}>
        {customFields.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {f.name} <span className="badge">{f.entity_kind === "requirement" ? strings.admin.entityKindRequirement : strings.admin.entityKindChangeRequest}</span> <span className="badge">{CUSTOM_FIELD_TYPE_LABEL[f.field_type]}</span>
              {f.required && <span className="badge">{strings.admin.required}</span>}
            </span>
            <button
              className="btn btn-danger"
              title={strings.admin.deleteCustomField(f.name)}
              aria-label={strings.admin.deleteCustomField(f.name)}
              onClick={() => setDeletingFieldId(f.id)}
            >
              <Trash2 size={14} />
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
        <div className="row">
          <select className="input" value={newFieldKind} onChange={(e) => setNewFieldKind(e.target.value as CustomFieldEntityKind)}>
            <option value="requirement">{strings.admin.entityKindRequirement}</option>
            <option value="change_request">{strings.admin.entityKindChangeRequest}</option>
          </select>
          <input className="input" placeholder={strings.admin.fieldName} value={newFieldName} onChange={(e) => setNewFieldName(e.target.value)} />
          <select className="input" value={newFieldType} onChange={(e) => setNewFieldType(e.target.value as CustomFieldType)}>
            <option value="short_text">{strings.admin.fieldTypeShortText}</option>
            <option value="long_text">{strings.admin.fieldTypeLongText}</option>
            <option value="checkbox">{strings.admin.fieldTypeCheckbox}</option>
            <option value="list">{strings.admin.fieldTypeList}</option>
          </select>
          {newFieldType === "list" && (
            <input
              className="input"
              placeholder={strings.admin.optionsCommaSeparated}
              value={newFieldOptions}
              onChange={(e) => setNewFieldOptions(e.target.value)}
            />
          )}
          <label className="row">
            <input type="checkbox" checked={newFieldRequired} onChange={(e) => setNewFieldRequired(e.target.checked)} />
            {strings.admin.required}
          </label>
          <button className="btn btn-primary" onClick={addCustomField} disabled={!newFieldName}>
            <Plus size={14} /> {strings.admin.newCustomField}
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
            {/* Convert-inherited-to-direct (decision 9, docs/decisions.md)
                — a safety net before disabling inheritance elsewhere
                silently drops someone's access. Not part of
                `ProjectMembersTable` itself since it operates on the whole
                member set at once, not a per-row action. */}
            <button className="btn" onClick={materializeInheritedAccess} disabled={materializing}>
              {strings.admin.materializeAll}
            </button>
          </div>
          {effectiveMembers === null ? (
            <Spinner />
          ) : (
            <ProjectMembersTable
              members={effectiveMembers}
              invites={pendingInvites}
              onToggleRole={toggleProjectMemberRole}
              onResendInvite={resendProjectInvite}
              resendingInviteId={resendingInviteId}
              ariaLabel={strings.admin.membersNav}
              addControl={
                <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
                  <UserAutocomplete
                    users={orgUsers}
                    placeholder={strings.admin.addOrInviteMemberPlaceholder}
                    onSelect={(userId) => addProjectMember(userId)}
                    organizationId={project?.organization_id}
                    projectId={project?.id}
                    onSelectExternal={(email) => addExternalMember(email, addMemberRole)}
                  />
                  <select
                    className="input"
                    aria-label={strings.membersTable.addRoleSelectLabel}
                    value={addMemberRole}
                    onChange={(e) => setAddMemberRole(e.target.value as ProjectRole)}
                  >
                    <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                    <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                    <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                    <option value="member">{PROJECT_ROLE_LABEL.member}</option>
                  </select>
                </div>
              }
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
          <Plus size={14} /> {strings.admin.newGroup}
        </button>
        {newGroupModalOpen && (
          // Style guide "Pattern: modal dialog for entity create/rename" —
          // a brand-new entity (a group) opens in a Modal, not a Popover —
          // the Popover-vs-Modal decision tree reserves Popover for a
          // one/two-field quick action on something that already exists,
          // not creating a new entity. `ProjectGroupCreate` still requires
          // a role up front — see this modal's own state declaration
          // comment for why that stays true even now that the role is
          // correctable afterward (Phase 5).
          <Modal title={strings.admin.newGroup} onClose={() => setNewGroupModalOpen(false)}>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.admin.name}
              <input
                className="input"
                autoFocus
                placeholder={strings.admin.groupNamePlaceholder}
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newGroupName) createProjectGroup();
                }}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.admin.groupRole}
              <select className="input" value={newGroupRole} onChange={(e) => setNewGroupRole(e.target.value as ProjectRole)}>
                <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                <option value="member">{PROJECT_ROLE_LABEL.member}</option>
              </select>
            </label>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setNewGroupModalOpen(false)}>
                {strings.common.cancel}
              </button>
              <button className="btn btn-primary" onClick={createProjectGroup} disabled={!newGroupName}>
                {strings.common.create}
              </button>
            </div>
          </Modal>
        )}

        {/* Rebuilt on the shared `DirectoryTable` (Phase 0) inside the
            standard `.side-grid` + `FilterPanel` layout, replacing the old
            `<button style={{width:"100%"}}>` per-row list — it wasn't a
            real `<table>` at all, no `SortableHeader` (2026-08-31, Phase B,
            follow-up UX batch — see docs/decisions.md). `onRowClick`, not
            `rowHref`, deliberately — found during verification, not
            assumed: every standard project seeds a default group literally
            named "Members" (`DEFAULT_GROUPS`, `routers/projects.py`), the
            exact same accessible name as this page's own `ResourceMenu`
            "Members" nav link. `rowHref` would render both as `role="link"`
            elements with an identical accessible name on the same page — a
            real ambiguity (not just a Playwright artifact; the same
            confusion a screen-reader user would hit navigating by link
            text), whereas `onRowClick`'s `role="button"` trigger can't
            collide with a nav `<Link>`. The existing manual `openGroupId`/
            `useSearchParams` handling below (unchanged since before this
            phase) already covers the `?openGroup=` deep link — `onRowClick`
            just calls the same `setOpenGroupId` a URL-driven open already
            uses. */}
        <div className="side-grid">
          <div className="stack">
            <DirectoryTable
              ariaLabel={strings.admin.groups}
              columns={projectGroupColumns}
              rows={groups}
              rowKey={(row) => row.id}
              sort={groupSort}
              onSort={(key) => applyGroupSort(key as ProjectGroupSortKey)}
              total={groupsTotal}
              onLoadMore={() => loadGroups(groupSearch, groups.length, true)}
              onRowClick={(row) => setOpenGroupId(row.id)}
              emptyState={<p className="text-muted">{strings.admin.noGroupsFound}</p>}
            />
          </div>
          <FilterPanel
            sectionKey="projectAdminGroupsFilters"
            search={groupSearch}
            onSearchChange={handleGroupSearchChange}
            searchPlaceholder={strings.admin.searchGroups}
          >
            {/* No dedicated filter fields beyond search exist for Groups
                today — see Org Groups' identical composition for why
                `FilterPanel` is still the right shell regardless. */}
            {null}
          </FilterPanel>
        </div>
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
          const groupRoleDisabled = g.role === "project_manager" && groupManagerSourceCount <= 1;
          return (
            <SidePanel title={strings.admin.groupDetails(g.name)} onClose={() => setOpenGroupId(null)}>
              <div className="stack">
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.admin.groupRoleAtTop}
                  <select
                    className="input"
                    value={g.role}
                    disabled={groupRoleDisabled}
                    title={groupRoleDisabled ? strings.membersTable.cannotRemoveLastManager : undefined}
                    onChange={(e) => changeGroupRole(g.id, e.target.value as ProjectRole)}
                  >
                    <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                    <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                    <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                    <option value="member">{PROJECT_ROLE_LABEL.member}</option>
                  </select>
                </label>
                <button
                  className="btn btn-danger"
                  style={{ alignSelf: "flex-start" }}
                  title={strings.admin.deleteGroup}
                  onClick={() => setDeletingGroupId(g.id)}
                >
                  <Trash2 size={14} /> {strings.admin.deleteGroup}
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
                            onClick={() => removeGroupMember(g.id, userId)}
                          >
                            <Trash2 size={14} />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <UserAutocomplete
                  users={availableUsers}
                  placeholder={strings.admin.addOrInviteMemberPlaceholder}
                  onSelect={(userId) => addGroupMember(g.id, userId)}
                  organizationId={project?.organization_id}
                  projectId={project?.id}
                  onSelectExternal={(email) => addExternalMember(email, g.role)}
                />
                {/* `externalAddResult` is shared with the Members section's
                    own add control (same `addExternalMember` handler) — it
                    needs its own render here too, not just there, since this
                    panel's invite-by-email path sets the same state and
                    otherwise had nowhere on the Groups section to surface
                    the outcome (Principle 7, feedback on every mutation). */}
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
                          onClick={() => removeOrgGroupMember(g.id, og.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {nestableOrgGroups.length > 0 && (
                  <div className="row">
                    <select
                      className="input"
                      aria-label={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      value={orgGroupSelections[g.id] ?? ""}
                      onChange={(e) => setOrgGroupSelections((prev) => ({ ...prev, [g.id]: e.target.value }))}
                    >
                      <option value="">{strings.admin.addOrgGroupToProjectGroup(orgLabel)}</option>
                      {nestableOrgGroups.map((og) => (
                        <option key={og.id} value={og.id}>
                          {og.name}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn"
                      disabled={!orgGroupSelections[g.id]}
                      title={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      aria-label={strings.admin.addOrgGroupToProjectGroup(orgLabel)}
                      onClick={() => addOrgGroupMember(g.id, orgGroupSelections[g.id])}
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                )}
                {referencedProjects.length > 0 && (
                  <>
                    <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                      {referencedProjects.map((p) => (
                        <li key={p.id} className="row" style={{ justifyContent: "space-between", listStyle: "circle" }}>
                          <span className="row" style={{ gap: "0.35rem" }}>
                            {strings.admin.viaProjectMembers(p.name)}
                            <Link to={`/projects/${p.id}/admin/members`}>{strings.admin.viaProjectMembersLinkLabel}</Link>
                          </span>
                          <button
                            className="btn btn-danger"
                            title={strings.admin.removeNestedGroup(strings.admin.viaProjectMembers(p.name))}
                            aria-label={strings.admin.removeNestedGroup(strings.admin.viaProjectMembers(p.name))}
                            onClick={() => removeProjectRefMember(g.id, p.id)}
                          >
                            <Trash2 size={14} />
                          </button>
                        </li>
                      ))}
                    </ul>
                    <p className="text-muted" style={{ fontSize: "0.8rem", margin: 0 }}>{strings.admin.viaProjectMembersHint}</p>
                  </>
                )}
                {referenceableProjects.length > 0 && (
                  <div className="row">
                    <select
                      className="input"
                      value={sourceProjectSelections[g.id] ?? ""}
                      aria-label={strings.admin.projectReferenceSelect}
                      onChange={(e) => setSourceProjectSelections((prev) => ({ ...prev, [g.id]: e.target.value }))}
                    >
                      <option value="">{strings.admin.addProjectReferenceToProjectGroup}</option>
                      {referenceableProjects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn"
                      disabled={!sourceProjectSelections[g.id]}
                      title={strings.admin.addProjectReferenceToProjectGroup}
                      aria-label={strings.admin.addProjectReferenceToProjectGroup}
                      onClick={() => addProjectRefMember(g.id, sourceProjectSelections[g.id])}
                    >
                      <Plus size={14} />
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
      </div>
      )}

      {activeGroup === "reportSetup" && (
      <div className="stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.reportSetup}</h2>
        <p className="text-muted" style={{ margin: 0 }}>
          This intro, these chapters, and these appendices are used as the default content when a report is
          generated for this project, unless overridden at generation time.
        </p>
        {reportTemplates.length > 0 && (
          <CollapsibleSection sectionKey="projectAdmin.reportSetup.defaultTemplate" title={strings.admin.defaultTemplateSection} defaultCollapsed={false}>
            <label className="stack" style={{ gap: "0.25rem", maxWidth: 280 }}>
              {strings.admin.defaultReportTemplate}
              <select
                className="input" value={defaultReportTemplateId}
                onChange={(e) => {
                  reportConfigDirtyRef.current = true;
                  setDefaultReportTemplateId(e.target.value);
                }}
              >
                <option value="">{strings.reports.noTemplate}</option>
                {reportTemplates.map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>
                    {tpl.name}
                  </option>
                ))}
              </select>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.admin.defaultReportTemplateHint}</span>
            </label>
          </CollapsibleSection>
        )}
        <CollapsibleSection sectionKey="projectAdmin.reportSetup.content" title={strings.admin.reportContent} defaultCollapsed={false}>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span>
            Project intro
            {reportConfigDefaults.intro && <span className="text-muted"> (organisation default)</span>}
          </span>
          <RichTextEditor
            rows={3}
            value={reportIntro}
            onChange={(v) => {
              reportConfigDirtyRef.current = true;
              setReportIntro(v);
            }}
            organizationId={project?.organization_id}
          />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          {reportConfigDefaults.chapters && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>Using the organisation default body chapters.</span>
          )}
          <ReportChapterListEditor
            label="Body chapters" list={reportChapters}
            setList={(list) => {
              reportConfigDirtyRef.current = true;
              setReportChapters(list);
            }}
            organizationId={project?.organization_id}
          />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          {reportConfigDefaults.appendices && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>Using the organisation default appendices.</span>
          )}
          <ReportChapterListEditor
            label="Appendices" list={reportAppendices}
            setList={(list) => {
              reportConfigDirtyRef.current = true;
              setReportAppendices(list);
            }}
            organizationId={project?.organization_id}
          />
        </div>
        </CollapsibleSection>
        <button className="btn btn-primary" onClick={saveReportConfig} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveSettings}
        </button>
      </div>
      )}
      </ResourceMenu>
    </div>
  );
}
