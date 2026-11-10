import { Plus, Star } from "lucide-react";
import { ImportWarnings } from "../components/ImportWarnings";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Organization,
  Project,
  ProjectImportResult,
  ProjectListItem,
  ProjectRole,
  ProjectRoleInheritanceMode,
  ProjectTreeNode,
  StagePhaseKind,
} from "../api/types";
import { collapseProjectRoles, MAX_PROJECT_REPORT_NAME_LENGTH, PROJECT_ROLE_LABEL, STAGE_PHASE_KIND_LABEL, STAGE_PHASE_KINDS } from "../api/types";
import { stageBadgeText } from "../utils/stageBadge";
import { BundleImportDialog } from "../components/BundleImportDialog";
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
import { Modal } from "../components/Modal";
import { ProjectHierarchyLabels } from "../components/ProjectHierarchyLabels";
import { ProjectIdentityFields } from "../components/ProjectIdentityFields";
import { ProjectNestingFields } from "../components/ProjectNestingFields";
import { MODES_NEEDING_CONFIRMATION } from "../utils/projectInheritance";
import { ProjectTree } from "../components/ProjectTree";
import { Spinner } from "../components/Spinner";
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

/**
 * Project list view (U-E-03): active projects across all organisations the
 * user can access, with an archived filter (U-E-04), search, project
 * creation (C-G-02), and incremental "load more" pagination (U-P-06).
 */
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
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count — powers
  // `ResultCount` in `FilterPanel`'s header alongside `total` above, which
  // is the filtered/searched count.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  // Filters live in the URL so the list comes back as it was left after a visit to a project.
  const [showArchived, setShowArchived] = useUrlFlag("archived");
  const [search, setSearch] = useUrlText("q");
  const [roleFilter, setRoleFilter] = useUrlChoice("role", Object.keys(PROJECT_ROLE_LABEL) as ProjectRole[]);
  const [stagePhaseKindFilter, setStagePhaseKindFilter] = useUrlChoice("stage_phase_kind", STAGE_PHASE_KINDS);
  const [orgFilter, setOrgFilter] = useUrlText("org");
  const [favoriteOnly, setFavoriteOnly] = useUrlFlag("favourites");
  const [showTemplates, setShowTemplates] = useUrlFlag("templates");
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

  // The tree option only appears when the caller's accessible project set
  // actually contains a parent/child relationship — a tree mode with
  // nothing to show a hierarchy for doesn't mean anything (see
  // `ViewToggle`'s own `showTreeOption` docstring).
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

  // "Add sub-project" from a project's own page (ProjectAdminPage) or a
  // ProjectTree node navigates here with these query params rather than
  // duplicating the create-project modal's logic on that page. Cleared
  // immediately after opening so a later reload/back-navigation doesn't
  // silently re-open the modal.
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
    // Same `favorite_only` param `FavouritesPage.tsx` already uses server-side
    // — filtering here rather than
    // client-side keeps this consistent with every other filter on this
    // page, all of which narrow the paginated result set itself rather
    // than hiding already-loaded rows.
    if (favoriteOnly) params.set("favorite_only", "true");
    if (showTemplates) params.set("include_templates", "true");
    return params;
  }

  // Read through a ref so a reload started from an older render (a
  // post-mutation `reload()` resuming after an `await`) still lists with the
  // filters the user has set since — otherwise, as the newest request, it
  // would overwrite their filtered results (found 2026-10-04 via the e2e
  // suite). Declared before the reload effect so it's current there.
  const listParamsRef = useLatest(listParams);

  // Belt-and-suspenders request-sequencing guard, same reasoning/shape as
  // `RequirementsPage.tsx`/`ChangeRequestsPage.tsx`'s identical guards
  // — discards a response if a newer request
  // has since been kicked off (e.g. rapid filter changes).
  const beginLoad = useRequestSequence();

  async function loadProjects(offset: number, append: boolean) {
    const isLatest = beginLoad();
    const page = await api.getPage<ProjectListItem>(`/api/v1/projects?${listParamsRef.current(offset).toString()}`);
    if (!isLatest()) return;
    setProjects((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
  }

  async function reload() {
    setProjects(null);
    const [orgList, everyProject, templates] = await Promise.all([
      // `mine=true`: a server admin otherwise sees every organisation in the
      // deployment here (the plain `GET /orgs` directory-listing bypass,
      // meant for the platform-level org directory) rather than just the
      // ones they can actually create a project in or usefully filter by.
      api.get<Organization[]>("/api/v1/orgs?mine=true"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
      // The template picker reads its own list: the default list leaves templates out.
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false&templates_only=true"),
      loadProjects(0, false),
    ]);
    // A disabled org can't hold any (newly) visible projects (the list
    // endpoint itself now excludes them) and can't accept new ones either
    // (`rbac._require_org_active`) — filtered out here so it doesn't appear
    // as a dead option in either the org filter or the "new project" org
    // picker below.
    const activeOrgs = orgList.filter((o) => o.is_active);
    setOrgs(activeOrgs);
    setAllProjects(everyProject);
    setTemplateProjects(templates);
    if (!newOrgId && activeOrgs[0]) setNewOrgId(resolveNewProjectOrgId(activeOrgs, defaultNewOrgId));
  }

  useLoadOnChange(reload, [showArchived, search, roleFilter, stagePhaseKindFilter, orgFilter, favoriteOnly, showTemplates]);

  // C-E-04: pre-select the organisation's default template project (if
  // one is configured) whenever the target org changes, rather than
  // always starting from "None". The user can still pick a different
  // template or explicitly choose "None (blank project)" before creating.
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
   * Full-fidelity project bundle import (`services.project_export`): a distinct path from template cloning, since
   * the bundle carries its own structure and history and may come from a different organisation entirely.
   * An error is thrown to `BundleImportDialog`, which shows it.
   */
  async function importProject(file: File, skipFiles: boolean) {
    const result = await api.postFile<ProjectImportResult>("/api/v1/projects/import", file, {
      organization_id: newOrgId, name: newName, summary: newSummary, ...(skipFiles ? { skip_files: "true" } : {}),
    });
    if (result.warnings.length > 0) setImportWarnings(result.warnings);
    showToast(strings.projects.created);
    navigate(`/projects/${result.project.id}`);
  }

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

  // No "exclude self" filter needed here, unlike ProjectAdminPage's own
  // equivalent (which excludes the project currently being edited from its
  // own parent-picker) — this is the *create* form, so the project being
  // created doesn't exist yet and there's nothing to exclude. `parentProjectId`
  // here is simply the currently-selected parent's id, not a "self" to avoid;
  // filtering it out was a bug (copied from the edit-form pattern without
  // adjusting for this different context) that made a pre-selected parent
  // (e.g. via "Add sub-project") permanently unable to render as selected,
  // since its own <option> never existed in the list at all.
  // can_be_parent-gated (docs/decisions.md) — a project isn't eligible to
  // be a parent until its own manager opts in; `p.id === parentProjectId`
  // keeps a pre-filled selection (via "Add sub-project") selectable even
  // in the edge case of a stale/manually-crafted URL.
  const parentOptions = allProjects.filter(
    (p) => p.organization_id === newOrgId && !p.is_archived && (p.can_be_parent || p.id === parentProjectId),
  );
  const selectedParent = allProjects.find((p) => p.id === parentProjectId);
  // Nothing eligible to pick — hide the field entirely rather than show a
  // picker with only "None" in it (see ProjectAdminPage's identical rule).
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
        {/* Style guide "Pattern: modal dialog for entity create/rename" —
            a brand-new entity opens in a Modal, not a permanently-visible
            inline block that reflows the list underneath it. */}
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
          >
            <ProjectIdentityFields
              orgs={orgs} orgLabelCap={orgLabelCap} orgId={newOrgId} onOrgChange={setNewOrgId}
              name={newName} onNameChange={setNewName} nameHelp={strings.help.importProjectName}
              summary={newSummary} onSummaryChange={setNewSummary}
            />
          </BundleImportDialog>
        )}
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
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
                {projects.map((p) => (
                  <div key={p.id} className="card stack" style={{ gap: "var(--space-3)" }}>
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
                      <Link
                        to={`/projects/${p.id}`}
                        style={{
                          fontWeight: 600, fontSize: "1.05rem", minWidth: 0, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}
                        title={p.name}
                      >
                        {p.name}
                      </Link>
                      {p.is_template && <Badge className="badge-after">{strings.projects.template}</Badge>}
                      <button
                        className="btn"
                        onClick={() => toggleFavorite(p)}
                        title={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                        aria-label={p.is_favorite ? strings.projects.unfavorite : strings.projects.favorite}
                        style={{ flexShrink: 0 }}
                      >
                        <Star fill={p.is_favorite ? "currentColor" : "none"} />
                      </button>
                    </div>
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
                  </div>
                ))}
              </div>
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
                    {projects.map((p) => (
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
