import { Plus, Settings, Star } from "lucide-react";
import { ImportWarnings } from "../components/ImportWarnings";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ImportPeopleChoices,
  OrgUser,
  Organization,
  Project,
  ProjectImportPreview,
  ProjectImportResult,
  ProjectListItem,
  ProjectRole,
  ProjectRoleInheritanceMode,
  ProjectTreeNode,
  StagePhaseKind,
  UnjoinedProjectListItem,
} from "../api/types";
import { collapseProjectRoles, MAX_PROJECT_REPORT_NAME_LENGTH, PROJECT_ROLE_LABEL, STAGE_PHASE_KIND_LABEL, STAGE_PHASE_KINDS } from "../api/types";
import { stageBadgeText } from "../utils/stageBadge";
import { BundleImportDialog } from "../components/BundleImportDialog";
import type { ImportMemberOption } from "../components/ImportPeopleStep";
import { UploadsDisabledPrompt } from "../components/UploadsDisabledPrompt";
import { uploadsDisabledInfo, type UploadsDisabledInfo } from "../utils/uploadsDisabled";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Badge } from "../components/Badge";
import { FilterBadge } from "../components/FilterBadge";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { ManageProjectUsersModal } from "../components/ManageProjectUsersModal";
import { Modal } from "../components/Modal";
import { ProjectHierarchyLabels } from "../components/ProjectHierarchyLabels";
import { ProjectIdentityFields } from "../components/ProjectIdentityFields";
import { ProjectNestingFields } from "../components/ProjectNestingFields";
import { MODES_NEEDING_CONFIRMATION } from "../utils/projectInheritance";
import { ProjectTree } from "../components/ProjectTree";
import { Spinner } from "../components/Spinner";
import { TileCard, TileGrid } from "../components/TileCard";
import { Tooltip } from "../components/Tooltip";
import { SplitButtonTrigger } from "../components/SplitButtonTrigger";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { useFavourites } from "../context/FavouritesContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { describeCodePolicy, normaliseProjectCode } from "../utils/codePolicy";
import { TextField } from "../components/FormFields";
import { InlineSelect, LabeledSelect } from "../components/LabeledSelect";
import { FormActions } from "../components/FormActions";
import { FormGrid, FormGridFull } from "../components/FormGrid";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { DEFAULT_NEW_PROJECT_ORG_PREFERENCE, resolveNewProjectOrgId } from "../hooks/defaultProjectOrganization";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useUiPreference } from "../hooks/useUiPreference";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useUrlChoice, useUrlFlag, useUrlText } from "../hooks/useUrlFilter";

const PAGE_SIZE = 30;

/** One row of the project list: a project the caller belongs to, or one they only administer the organisation of. */
type ProjectListRow = ProjectListItem | UnjoinedProjectListItem;

/**
 * The gear on a project the person is not a member of, opening the dialog that manages who has access to it.
 *
 * @param props.project The non-member row.
 * @param props.onOpen Called with the row when the gear is pressed.
 * @returns A square icon button with a tooltip naming the project.
 */
function ManageUsersGear({ project, onOpen }: { project: UnjoinedProjectListItem; onOpen: (project: UnjoinedProjectListItem) => void }) {
  const strings = useStrings();
  const label = strings.projects.manageUsersOf(project.name);
  return (
    <Tooltip label={label}>
      <button type="button" className="btn btn-sm btn-icon" aria-label={label} onClick={() => onOpen(project)} style={{ flexShrink: 0 }}>
        <Settings />
      </button>
    </Tooltip>
  );
}

/** Project list view (U-E-03): active projects across the user's organisations, with an archived filter (U-E-04), search, creation (C-G-02) and "load more" pagination (U-P-06). */
export function ProjectListPage() {
  const strings = useStrings();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const { showToast } = useToast();
  const { refreshFavourites } = useFavourites();
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();
  const [projects, setProjects] = useState<ProjectListRow[] | null>(null);
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count, shown by `ResultCount` beside the filtered/searched `total`.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  // Filters live in the URL so the list comes back as it was left after a visit to a project.
  const [showArchived, setShowArchived] = useUrlFlag("archived");
  const [search, setSearch] = useUrlText("q");
  const [roleFilter, setRoleFilter] = useUrlChoice("role", Object.keys(PROJECT_ROLE_LABEL) as ProjectRole[]);
  const [stagePhaseKindFilter, setStagePhaseKindFilter] = useUrlChoice("stage_phase_kind", STAGE_PHASE_KINDS);
  const [orgFilter, setOrgFilter] = useUrlText("org");
  const [favoriteOnly, setFavoriteOnly] = useUrlFlag("favourites");
  const [showTemplates, setShowTemplates] = useUrlFlag("templates");
  // Organisation administrators only: also list the projects of their organisations that they hold no role in.
  const [includeUnjoined, setIncludeUnjoined] = useUrlFlag("not_member");
  const [canIncludeUnjoined, setCanIncludeUnjoined] = useState(false);
  const [managedProject, setManagedProject] = useState<UnjoinedProjectListItem | null>(null);
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [showNewForm, setShowNewForm] = useState(false);
  const [showImportForm, setShowImportForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSummary, setNewSummary] = useState("");
  const [newReportName, setNewReportName] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newOrgId, setNewOrgId] = useState("");
  // The organisation the New project dialog starts on (Preferences); a deep link sets `newOrgId` first.
  const [defaultNewOrgId] = useUiPreference<string>(DEFAULT_NEW_PROJECT_ORG_PREFERENCE, "");
  const [templateProjectId, setTemplateProjectId] = useState("");
  const [newVisibility, setNewVisibility] = useState<"only_specified" | "org_wide">("only_specified");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createFilesPrompt, setCreateFilesPrompt] = useState<UploadsDisabledInfo | null>(null);
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null);
  const [allProjects, setAllProjects] = useState<ProjectListItem[]>([]);
  const [templateProjects, setTemplateProjects] = useState<ProjectListItem[]>([]);
  const [storedViewMode, setViewMode] = useViewMode("projects");
  // Hierarchical projects (docs/decisions.md).
  const [parentProjectId, setParentProjectId] = useState("");
  const [roleInheritanceMode, setRoleInheritanceMode] = useState<ProjectRoleInheritanceMode>("none");
  const [roleInheritanceFilterRole, setRoleInheritanceFilterRole] = useState<ProjectRole>("project_manager");
  const [pendingInheritMode, setPendingInheritMode] = useState<ProjectRoleInheritanceMode | null>(null);
  const [treeNodes, setTreeNodes] = useState<ProjectTreeNode[] | null>(null);
  const [chosenTreeOrgId, setTreeOrgId] = useState("");

  // The tree option appears only when the accessible set contains a parent/child relationship (`ViewToggle`'s `showTreeOption`).
  const hasHierarchy = allProjects.some((p) => p.parent_project_id || p.children.length > 0);
  const orgsWithHierarchy = orgs.filter((o) =>
    allProjects.some((p) => p.organization_id === o.id && (p.parent_project_id || p.children.length > 0))
  );

  // Derived rather than written back by effects: tree mode is meaningless without a hierarchy
  // (the stored choice comes back if one appears), and the tree shows the first organisation
  // with a hierarchy until another is picked.
  const viewMode = !hasHierarchy && storedViewMode === "tree" ? "tiles" : storedViewMode;
  const treeOrgId = chosenTreeOrgId || orgsWithHierarchy[0]?.id || "";

  useEffect(() => {
    if (viewMode !== "tree" || !treeOrgId) return;
    api.get<ProjectTreeNode[]>(`/api/v1/projects/tree?organization_id=${treeOrgId}`).then(setTreeNodes);
  }, [viewMode, treeOrgId]);

  function openAddSubProject(parentId: string, orgId: string) {
    setNewOrgId(orgId);
    setParentProjectId(parentId);
    setShowNewForm(true);
  }

  // "Add sub-project" from a project page or a ProjectTree node navigates here with these query parameters instead of duplicating
  // the create modal there; they are cleared once the modal opens so a reload or Back does not reopen it.
  const deepLinkParentId = searchParams.get("parentProjectId");
  const deepLinkOrgId = searchParams.get("organizationId");
  useResetOnChange([deepLinkParentId, deepLinkOrgId], () => {
    if (deepLinkParentId && deepLinkOrgId) openAddSubProject(deepLinkParentId, deepLinkOrgId);
  }, { runOnMount: true });

  useEffect(() => {
    if (!deepLinkParentId || !deepLinkOrgId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("parentProjectId");
      next.delete("organizationId");
      return next;
    }, { replace: true });
  }, [deepLinkParentId, deepLinkOrgId, setSearchParams]);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ archived: String(showArchived), limit: String(limitFor(offset)), offset: String(offset) });
    if (search) params.set("search", search);
    if (roleFilter) params.set("role", roleFilter);
    if (stagePhaseKindFilter) params.set("stage_phase_kind", stagePhaseKindFilter);
    if (orgFilter) params.set("organization_id", orgFilter);
    // The same `favorite_only` parameter as `FavouritesPage.tsx`, applied server-side like every other filter here.
    if (favoriteOnly) params.set("favorite_only", "true");
    if (showTemplates) params.set("include_templates", "true");
    if (includeUnjoined) params.set("include_unjoined", "true");
    return params;
  }

  // Read through a ref so a reload resuming after an `await` in an older render still lists with the current filters instead
  // of overwriting the filtered results. Declared before the reload effect.
  const listParamsRef = useLatest(listParams);

  // Discards a response when a newer request has started (e.g. rapid filter changes).
  const beginLoad = useRequestSequence();

  async function loadProjects(offset: number, append: boolean) {
    const isLatest = beginLoad();
    const page = await api.getPage<ProjectListRow>(`/api/v1/projects?${listParamsRef.current(offset).toString()}`);
    if (!isLatest()) return;
    setCanIncludeUnjoined(page.canIncludeUnjoined ?? false);
    setProjects((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
  }

  async function reload() {
    setProjects(null);
    const [orgList, everyProject, templates] = await Promise.all([
      // `mine=true`: otherwise a server administrator sees every organisation (the platform directory) instead of the ones they can
      // create a project in or filter by.
      api.get<Organization[]>("/api/v1/orgs?mine=true"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
      // The template picker reads its own list: the default list leaves templates out.
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false&templates_only=true"),
      loadProjects(0, false),
    ]);
    // A disabled organisation holds no visible projects (the list endpoint excludes them) and accepts no new ones
    // (`rbac._require_org_active`), so it is filtered out of the organisation filter and the new-project picker.
    const activeOrgs = orgList.filter((o) => o.is_active);
    setOrgs(activeOrgs);
    setAllProjects(everyProject);
    setTemplateProjects(templates);
    if (!newOrgId && activeOrgs[0]) setNewOrgId(resolveNewProjectOrgId(activeOrgs, defaultNewOrgId));
  }

  useLoadOnChange(reload, [showArchived, search, roleFilter, stagePhaseKindFilter, orgFilter, favoriteOnly, showTemplates, includeUnjoined]);

  // C-E-04: pre-select the organisation's default template project (if configured) when the target organisation changes; the user
  // can pick another or "None (blank project)".
  useResetOnChange([newOrgId], () => {
    const org = orgs.find((o) => o.id === newOrgId);
    setTemplateProjectId(org?.default_template_project_id ?? "");
  }, { runOnMount: true });

  async function toggleFavorite(project: ProjectListItem) {
    try {
      if (project.is_favorite) {
        await api.delete(`/api/v1/projects/${project.id}/favorite`);
      } else {
        await api.put(`/api/v1/projects/${project.id}/favorite`);
      }
      reload();
      refreshFavourites();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const newOrg = orgs.find((o) => o.id === newOrgId);
  // The organisation's default template is offered even when the caller cannot see it in the list (an
  // administrator chose it for every new project), under a generic name so nothing of it is revealed.
  const defaultTemplateId = newOrg?.default_template_project_id ?? null;
  const templateOptions: { id: string; name: string }[] = templateProjects
    .filter((p) => p.organization_id === newOrgId)
    .map((p) => ({ id: p.id, name: p.name }));
  if (defaultTemplateId && !templateOptions.some((p) => p.id === defaultTemplateId)) {
    templateOptions.push({ id: defaultTemplateId, name: strings.projects.organisationDefaultTemplate });
  }
  const showOrgColumn = orgs.length > 1 || !!user?.is_server_admin;

  function toggleStagePhaseKindFilter(status: StagePhaseKind | null) {
    if (!status) return;
    setStagePhaseKindFilter((current) => (current === status ? "" : status));
  }

  async function createProject(skipFiles = false) {
    setCreateError(null);
    try {
      const project = await api.post<Project>("/api/v1/projects", {
        organization_id: newOrgId,
        name: newName,
        summary: newSummary,
        report_name: newReportName.trim() || null,
        code: newOrg?.project_code_policy.assignment === "manual" ? normaliseProjectCode(newCode) : null,
        template_project_id: templateProjectId || null,
        // "None" is an explicit choice: without it the organisation's default template would apply.
        use_template: templateProjectId !== "",
        // Honoured by the server only while the template's files cannot be stored (uploads disabled).
        skip_files: skipFiles,
        visibility: newVisibility,
        parent_project_id: parentProjectId || null,
        role_inheritance_mode: roleInheritanceMode,
        role_inheritance_filter_role: roleInheritanceMode === "mirror_role" ? roleInheritanceFilterRole : null,
      });
      showToast(strings.projects.created);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      const filesInfo = skipFiles ? null : uploadsDisabledInfo(err);
      if (filesInfo) setCreateFilesPrompt(filesInfo);
      else setCreateError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  /**
   * Full-fidelity project bundle import (`services.project_export`): separate from template cloning because the bundle carries
   * its own structure and history and may come from another organisation. Errors are thrown to `BundleImportDialog`.
   */
  async function importProject(file: File, skipFiles: boolean, choices: ImportPeopleChoices) {
    const result = await api.postFile<ProjectImportResult>("/api/v1/projects/import", file, {
      organization_id: newOrgId, name: newName, summary: newSummary, people: JSON.stringify(choices),
      ...(skipFiles ? { skip_files: "true" } : {}),
    });
    if (result.warnings.length > 0) setImportWarnings(result.warnings);
    showToast(strings.projects.created);
    navigate(`/projects/${result.project.id}`);
  }

  /** The People step's preview: who the bundle names and how each would be recorded in the chosen organisation. */
  async function loadImportPeople(file: File, choices: ImportPeopleChoices) {
    const preview = await api.postFile<ProjectImportPreview>("/api/v1/projects/import/preview", file, {
      organization_id: newOrgId, people: JSON.stringify(choices),
    });
    return preview.people;
  }

  // The members a person can be reassigned to, read when the import dialog is open for an organisation.
  const [importMembers, setImportMembers] = useState<ImportMemberOption[]>([]);
  useLoadOnChange(async () => {
    if (!showImportForm || !newOrgId) return;
    try {
      const users = await api.get<OrgUser[]>(`/api/v1/orgs/${newOrgId}/users`);
      setImportMembers(users.filter((u) => u.is_active && !u.is_archived).map((u) => ({ user_id: u.user_id, display_name: u.display_name })));
    } catch {
      setImportMembers([]);
    }
  }, [showImportForm, newOrgId]);

  function closeImportForm() {
    setShowImportForm(false);
  }

  function closeNewForm() {
    setShowNewForm(false);
    setCreateFilesPrompt(null);
    setNewCode("");
    setParentProjectId("");
    setRoleInheritanceMode("none");
  }

  function requestInheritModeChange(mode: ProjectRoleInheritanceMode) {
    if (MODES_NEEDING_CONFIRMATION.includes(mode)) {
      setPendingInheritMode(mode);
    } else {
      setRoleInheritanceMode(mode);
    }
  }

  // No "exclude self" filter, unlike ProjectAdminPage's edit form: the project being created does not exist yet, and
  // `parentProjectId` is the selected parent, which must stay in the list to render as selected (e.g. from "Add sub-project").
  // Gated by can_be_parent (docs/decisions.md): a project is a parent candidate only once its manager opts in; `p.id ===
  // parentProjectId` keeps a pre-filled selection selectable even from a stale or crafted URL.
  const parentOptions = allProjects.filter(
    (p) => p.organization_id === newOrgId && !p.is_archived && (p.can_be_parent || p.id === parentProjectId),
  );
  const selectedParent = allProjects.find((p) => p.id === parentProjectId);
  // Nothing eligible to pick: hide the field (as ProjectAdminPage).
  const showParentField = parentOptions.length > 0 || parentProjectId !== "";

  return (
    <div className="stack">
      <ListPageLayout
        ready={projects !== null}
        loadedRows={projects?.length}
        title={strings.projects.title}
        actions={
          <SplitButtonTrigger
            icon={<Plus />}
            label={strings.projects.newProject}
            onDefaultAction={() => setShowNewForm(true)}
            menuTitle={strings.projects.newProject}
            moreOptionsLabel={strings.common.moreOptions}
            alternatives={[{ label: strings.projects.importProject, onSelect: () => setShowImportForm(true) }]}
          />
        }
        filter={
          <FilterPanel
            sectionKey="projectListFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.projects.search}
          >
            <FilterCheckbox label={strings.projects.favouritesOnly} checked={favoriteOnly} onChange={setFavoriteOnly} />
            <FilterCheckbox label={strings.projects.showTemplates} checked={showTemplates} onChange={setShowTemplates} />
            {canIncludeUnjoined && (
              <FilterCheckbox
                label={strings.projects.includeUnjoined}
                checked={includeUnjoined}
                onChange={setIncludeUnjoined}
                help={strings.help.includeUnjoinedProjects(orgLabel)}
              />
            )}
            <FilterSelect
              label={strings.filters.status}
              value={showArchived ? "archived" : "active"}
              onChange={(v) => setShowArchived(v === "archived")}
              options={[{ value: "active", label: strings.projects.active }, { value: "archived", label: strings.projects.archived }]}
            />
            {orgs.length > 1 && (
              <FilterSelect
                label={orgLabelCap}
                value={orgFilter}
                onChange={setOrgFilter}
                allLabel={strings.projects.allOrganisations(orgLabelPlural)}
                options={orgs.map((o) => ({ value: o.id, label: o.name }))}
              />
            )}
            <FilterSelect
              label={strings.filters.role}
              value={roleFilter}
              onChange={setRoleFilter}
              allLabel={strings.projects.allRoles}
              options={[{ value: "project_manager", label: PROJECT_ROLE_LABEL.project_manager }, { value: "project_administrator", label: PROJECT_ROLE_LABEL.project_administrator }, { value: "stakeholder", label: PROJECT_ROLE_LABEL.stakeholder }, { value: "member", label: PROJECT_ROLE_LABEL.member }]}
            />
            <FilterSelect
              label={strings.projects.stagePhaseKindLabel}
              help={strings.help.stagePhaseKindFilter}
              value={stagePhaseKindFilter}
              onChange={setStagePhaseKindFilter}
              allLabel={strings.projects.allStages}
              options={STAGE_PHASE_KINDS.map((kind) => ({ value: kind, label: STAGE_PHASE_KIND_LABEL[kind] }))}
            />
          </FilterPanel>
        }
      >
        {/* Style guide "Pattern: modal dialog for entity create/rename": a new entity opens in a Modal, not an inline block. */}
        {showNewForm && (
          <Modal title={strings.projects.newProject} onClose={closeNewForm} size="lg">
            {createFilesPrompt ? (
              <UploadsDisabledPrompt info={createFilesPrompt} onCancel={closeNewForm} onContinue={() => createProject(true)} />
            ) : (
            <div className="stack">
              <FormGrid minColumn="18rem">
                <ProjectIdentityFields
                  orgs={orgs} orgLabelCap={orgLabelCap} orgId={newOrgId} onOrgChange={setNewOrgId}
                  name={newName} onNameChange={setNewName}
                  nameHelp={newOrg?.project_code_policy.assignment === "auto" ? strings.help.newProjectNameAutoCode : undefined}
                  summary={newSummary} onSummaryChange={setNewSummary}
                  beforeName={templateOptions.length > 0 && (
                    <LabeledSelect help={strings.help.useTemplate}
                      label={strings.projects.useTemplate}
                      value={templateProjectId}
                      onChange={setTemplateProjectId}
                      options={templateOptions.map((p) => ({ value: p.id, label: p.name }))}
                      placeholder={strings.projects.noTemplate}
                      inputProps={{ autoFocus: orgs.length <= 1 }}
                    />
                  )}
                >
                  {newOrg?.project_code_policy.assignment === "manual" && (
                    <TextField helpNotNeeded required
                      label={strings.projects.code}
                      value={newCode}
                      onChange={(next) => setNewCode(next.toUpperCase())}
                      hint={strings.projects.codeHint(describeCodePolicy(newOrg.project_code_policy))}
                      inputProps={{ maxLength: newOrg.project_code_policy.max_length }}
                    />
                  )}
                  <TextField help={strings.help.projectReportName}
                    label={strings.projects.reportName}
                    value={newReportName}
                    onChange={setNewReportName}
                    inputProps={{ maxLength: MAX_PROJECT_REPORT_NAME_LENGTH }}
                  />
                </ProjectIdentityFields>
                <LabeledSelect help={strings.help.projectVisibility(orgLabel)}
                  label={strings.admin.visibility}
                  value={newVisibility}
                  onChange={(next) => setNewVisibility(next as "only_specified" | "org_wide")}
                  options={[{ value: "only_specified", label: strings.admin.visibilityOnlySpecified }, { value: "org_wide", label: strings.admin.visibilityOrgWide }]}
                  placeholder={null}
                />
                {/* can_be_parent-gated (docs/decisions.md) — hidden entirely when there's nothing eligible to pick,
                    rather than showing a picker with only "None" in it. Parent, inheritance and mirrored role are
                    one collapsed group: most projects are top-level, so the default dialog stays short. */}
                {showParentField && (
                  <FormGridFull>
                    <CollapsibleSection
                      sectionKey="newProjectNesting"
                      variant="plain"
                      defaultCollapsed
                      title={strings.projects.nesting}
                      summary={selectedParent?.name}
                      marked={!!selectedParent}
                    >
                      <ProjectNestingFields
                        parentProjectId={parentProjectId}
                        parentOptions={parentOptions}
                        onParentChange={setParentProjectId}
                        mode={roleInheritanceMode}
                        onModeChange={requestInheritModeChange}
                        filterRole={roleInheritanceFilterRole}
                        onFilterRoleChange={setRoleInheritanceFilterRole}
                      />
                    </CollapsibleSection>
                  </FormGridFull>
                )}
              </FormGrid>
              <FormActions
                error={createError}
                onCancel={closeNewForm}
                onSave={() => createProject()}
                saveLabel={strings.common.create}
                saveDisabled={!newName || !newOrgId || (newOrg?.project_code_policy.assignment === "manual" && !newCode)}
              />
            </div>
            )}
          </Modal>
        )}
        {showImportForm && (
          <BundleImportDialog
            title={strings.projects.importProject}
            fileLabel={strings.projects.bundleFile}
            fileHelp={strings.help.importProjectBundle}
            onClose={closeImportForm}
            onImport={importProject}
            canImport={!!newName && !!newOrgId}
            people={{ load: loadImportPeople, members: importMembers, dependsOn: newOrgId }}
          >
            <ProjectIdentityFields
              orgs={orgs} orgLabelCap={orgLabelCap} orgId={newOrgId} onOrgChange={setNewOrgId}
              name={newName} onNameChange={setNewName} nameHelp={strings.help.importProjectName}
              summary={newSummary} onSummaryChange={setNewSummary}
            />
          </BundleImportDialog>
        )}
        {managedProject && <ManageProjectUsersModal project={managedProject} onClose={() => setManagedProject(null)} />}
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
        <ImportWarnings warnings={importWarnings} title={strings.projects.importWarnings} />
          <div className="stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <ViewToggle mode={viewMode} onChange={setViewMode} showTreeOption={hasHierarchy} />
            </div>

            {viewMode === "tree" && hasHierarchy && (
              <div className="stack">
                {orgsWithHierarchy.length > 1 && (
                  <InlineSelect
                    maxWidth={280} ariaLabel={orgLabelCap} value={treeOrgId} placeholder={null} onChange={setTreeOrgId}
                    options={orgsWithHierarchy.map((o) => ({ value: o.id, label: o.name }))}
                  />
                )}
                {!treeNodes && <Spinner />}
                {treeNodes && (
                  <div className="card">
                    <ProjectTree nodes={treeNodes} onAddChild={(parentId) => openAddSubProject(parentId, treeOrgId)} />
                  </div>
                )}
              </div>
            )}

            {viewMode !== "tree" && !projects && <Spinner />}
            {viewMode !== "tree" && projects && projects.length === 0 && <p className="text-muted">{strings.projects.empty}</p>}
            {projects && projects.length > 0 && viewMode === "tiles" && (
              <TileGrid>
                {projects.map((p) => p.is_member === false ? (
                  <TileCard key={p.id} title={p.name} muted actions={<ManageUsersGear project={p} onOpen={setManagedProject} />}>
                    <div className="row" style={{ gap: "var(--space-2)" }}>
                      <Badge>{strings.projects.notMember}</Badge>
                      {p.is_template && <Badge>{strings.projects.template}</Badge>}
                    </div>
                    {showOrgColumn && <div style={{ fontSize: "0.8rem" }}>{p.organization_name}</div>}
                    <ProjectHierarchyLabels project={{ ...p, children: [] }} />
                  </TileCard>
                ) : (
                  <TileCard
                    key={p.id}
                    title={p.name}
                    to={`/projects/${p.id}`}
                    titleBadges={p.is_template ? <Badge>{strings.projects.template}</Badge> : undefined}
                    actions={
                      <button
                        className="btn"
                        onClick={() => toggleFavorite(p)}
                        title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                        aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                      >
                        <Star fill={p.is_favorite ? "currentColor" : "none"} />
                      </button>
                    }
                  >
                    {showOrgColumn && <div className="text-muted" style={{ fontSize: "0.8rem" }}>{p.organization_name}</div>}
                    <ProjectHierarchyLabels project={p} />
                    {p.current_stage_name && (
                      <FilterBadge
                        active={stagePhaseKindFilter === p.current_stage_phase_kind}
                        onClick={() => toggleStagePhaseKindFilter(p.current_stage_phase_kind)}
                        style={{ alignSelf: "flex-start" }}
                      >
                        {stageBadgeText(p.current_stage_name, p.current_stage_phase_name)}
                      </FilterBadge>
                    )}
                    <p
                      className="text-muted"
                      style={{
                        margin: 0, marginTop: "0.15rem", flex: 1,
                        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden",
                      }}
                    >
                      {p.summary || "—"}
                    </p>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {strings.projects.roles}: {collapseProjectRoles(p.my_roles).map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {strings.projects.requirementCount}: {p.requirement_count}
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                      {strings.projects.updated}: {new Date(p.updated_at).toLocaleString()}
                    </div>
                  </TileCard>
                ))}
              </TileGrid>
            )}
            {projects && projects.length > 0 && viewMode === "list" && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th />
                      <th>Name</th>
                      {showOrgColumn && <th>{strings.projects.organisation(orgLabelCap)}</th>}
                      <th>{strings.projects.stage}</th>
                      <th>{strings.projects.roles}</th>
                      <th>{strings.projects.requirementCount}</th>
                      <th>{strings.projects.updated}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map((p) => p.is_member === false ? (
                      <tr key={p.id} className="text-muted">
                        <td><ManageUsersGear project={p} onOpen={setManagedProject} /></td>
                        <td>
                          {p.name}
                          <Badge className="badge-after">{strings.projects.notMember}</Badge>
                          {p.is_template && <Badge className="badge-after">{strings.projects.template}</Badge>}
                          <ProjectHierarchyLabels project={{ ...p, children: [] }} />
                        </td>
                        {showOrgColumn && <td>{p.organization_name}</td>}
                        <td />
                        <td>—</td>
                        <td>—</td>
                        <td>—</td>
                      </tr>
                    ) : (
                      <tr key={p.id}>
                        <td>
                          <button
                            className="btn"
                            onClick={() => toggleFavorite(p)}
                            title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                            aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                          >
                            <Star fill={p.is_favorite ? "currentColor" : "none"} />
                          </button>
                        </td>
                        <td>
                          <Link to={`/projects/${p.id}`}>{p.name}</Link>
                          {p.is_template && <Badge className="badge-after">{strings.projects.template}</Badge>}
                          <div
                            className="text-muted"
                            style={{
                              fontSize: "0.85rem", marginTop: "0.15rem",
                              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                            }}
                          >
                            {p.summary || "—"}
                          </div>
                          <ProjectHierarchyLabels project={p} />
                        </td>
                        {showOrgColumn && <td className="text-muted">{p.organization_name}</td>}
                        <td>
                          {p.current_stage_name && (
                            <FilterBadge
                              active={stagePhaseKindFilter === p.current_stage_phase_kind}
                              onClick={() => toggleStagePhaseKindFilter(p.current_stage_phase_kind)}
                            >
                              {stageBadgeText(p.current_stage_name, p.current_stage_phase_name)}
                            </FilterBadge>
                          )}
                        </td>
                        <td className="text-muted">{collapseProjectRoles(p.my_roles).map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"}</td>
                        <td className="text-muted">{p.requirement_count}</td>
                        <td className="text-muted">{new Date(p.updated_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {viewMode !== "tree" && projects && (
              <LoadMoreButton loaded={projects.length} total={total} onClick={() => loadProjects(projects.length, true)} />
            )}
          </div>
      </ListPageLayout>
    </div>
  );
}
