import { ArrowDown, ArrowUp, GitPullRequest, MessageSquare, Plus, TriangleAlert } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { Tooltip } from "../components/Tooltip";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Category,
  Component,
  OrgUser,
  Project,
  ProjectStage,
  StageWorkflow,
  Requirement,
  RequirementStatus,
} from "../api/types";
import {
  ENTITY_ACCENT_COLOR,
  REQUIREMENT_LEVEL_LABEL,
  REQUIREMENT_STATUS_LABEL,
  REQUIREMENT_STATUS_TONE,
  principalRef,
} from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { RequirementCreateModal } from "../components/RequirementCreateModal";
import { FilterBadge } from "../components/FilterBadge";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Popover } from "../components/Popover";
import { BulkTagDialog } from "../components/BulkTagDialog";
import { projectTagAdminApi } from "../api/tags";
import { TagFilterField } from "../components/TagFilterField";
import { SortableHeader } from "../components/SortableHeader";
import { cycleSort } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { useTagFilter } from "../hooks/useTagFilter";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useProjectScope } from "../hooks/useProjectScope";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { addSharedListFilters } from "../utils/listFilterParams";
import { InlineSelect } from "../components/LabeledSelect";

const PAGE_SIZE = 30;

// C-G-11: "completed" is no longer a `RequirementStatus` value — it's an
// independent overlay marker (`Requirement.is_completed`), filtered via its
// own `FilterCheckbox` below rather than a status option.
const STATUS_OPTIONS: RequirementStatus[] = ["draft", "reviewed", "approved", "archived"];
const SORT_KEYS = ["unique_code", "name", "status"] as const;

/**
 * Requirement browser (C-G-04: sorted by component/category), with search
 * by name/ID (U-E-01), a filter panel (status/target version/category/
 * comments/watched), scoping-stage-only reordering (C-E-03), and
 * incremental "load more" pagination (U-P-06) for large requirement sets.
 */
export function RequirementsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const { showToast } = useToast();
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const myRoles = useMyProjectRoles(projectId);
  const [isOrgAdminOfProject, setIsOrgAdminOfProject] = useState(false);
  const canManageProject =
    myRoles.includes("project_manager") || myRoles.includes("project_administrator") || isOrgAdminOfProject;
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count — powers
  // `ResultCount` in `FilterPanel`'s header alongside `total` above, which
  // is the filtered/searched count.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [workflows, setWorkflows] = useState<StageWorkflow[]>([]);
  // The list's filters, search and sort live in the URL (`useUrlFilter`), so it comes back as it was left
  // after a visit to a record, and a dashboard glance links here with the same `status`, `stage` and
  // `completed` parameters. Completion is a separate overlay marker, not a status value.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice<RequirementStatus>("status", STATUS_OPTIONS);
  const [completedFilter, setCompletedFilter] = useUrlFlag("completed");
  // The target version is a range by the versions' order. `stage` is the single-version form older links and
  // bookmarks use: it is read as a range of one and dropped as soon as either end is changed.
  const [legacyStage, setLegacyStage] = useUrlText("stage");
  const [stageFromParam, setStageFromParam] = useUrlText("stage_from");
  const [stageToParam, setStageToParam] = useUrlText("stage_to");
  const stageFrom = stageFromParam || legacyStage;
  const stageTo = stageToParam || legacyStage;
  // The phase that governs a requirement: its component's own track when component phases are on, else its stage's.
  const [phaseFilter, setPhaseFilter] = useUrlText("phase");
  const [componentFilter, setComponentFilter] = useUrlText("component");
  const [categoryFilter, setCategoryFilter] = useUrlText("category");
  const [hasCommentsOnly, setHasCommentsOnly] = useUrlFlag("comments");
  const [onlyWatched, setOnlyWatched] = useUrlFlag("watched");
  // An archived requirement's detail page has the Restore button; this filter is how the list reaches one.
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  // The list is backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so sorting is a `sort`/`order` query
  // parameter the backend honours; sorting only the loaded rows would misrepresent the full-list order.
  const [sort, setSort] = useUrlSort(SORT_KEYS);
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const [showNewForm, setShowNewForm] = useState(false);
  const [viewMode, setViewMode] = useViewMode("requirements");

  // --- Bulk operations (list view only) ---------------------------------
  // Style guide "Pattern: bulk operations on a list" — the first pilot of
  // this shape in the app. Selection is a plain `id` Set rather than tied to array
  // indices, so it survives `loadRequirements`'s append-on-"load more"
  // without extra bookkeeping, and "select all" only ever means "all
  // currently loaded rows" (U-P-06's incremental pagination makes a true
  // "all 500 matching the filter" unsafe to promise from the client).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkArchiveDialogOpen, setBulkArchiveDialogOpen] = useState(false);
  const [bulkMovePopoverOpen, setBulkMovePopoverOpen] = useState(false);
  const [bulkTagDialogOpen, setBulkTagDialogOpen] = useState(false);
  const [bulkMoveStageId, setBulkMoveStageId] = useState("");
  const [bulkMoveDialogOpen, setBulkMoveDialogOpen] = useState(false);
  const bulkMoveTriggerRef = useRef<HTMLButtonElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  /** The list's filters, by the names its list request and the shared export both take (no paging or sort). */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (completedFilter) params.set("is_completed", "true");
    if (stageFrom) params.set("target_stage_from_id", stageFrom);
    if (stageTo) params.set("target_stage_to_id", stageTo);
    if (phaseFilter) params.set("phase", phaseFilter);
    if (componentFilter) params.set("component_id", componentFilter);
    if (categoryFilter) params.set("category_id", categoryFilter);
    if (hasCommentsOnly) params.set("has_comments", "true");
    if (onlyWatched) params.set("only_watched", "true");
    if (includeArchived) params.set("include_archived", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  /** Sets one end of the target version range, keeping the other end a legacy `stage` link implied. */
  function setStageRange(from: string, to: string) {
    setLegacyStage("");
    setStageFromParam(from);
    setStageToParam(to);
  }

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(limitFor(offset)), offset: String(offset) });
    filterParams().forEach((value, key) => params.append(key, value));
    if (sort) {
      params.set("sort", sort.key);
      params.set("order", sort.direction);
    }
    return params;
  }

  // Read through a ref so a reload started from an older render (a
  // post-mutation `reload()` resuming after an `await`) still lists with the
  // filters the user has set since — otherwise, as the newest request, it
  // would overwrite their filtered results (found 2026-10-04 via the e2e
  // suite). Declared before the reload effect so it's current there.
  const listParamsRef = useLatest(listParams);

  // Belt-and-suspenders guard (bug fix, 2026-08: dashboard glance
  // navigation race) alongside the filters living in the URL — neither
  // `loadRequirements` nor `reload()` previously sequenced requests at all,
  // so *any* path that can fire two overlapping fetches (e.g. rapid filter
  // changes, not just the mount-time race the seeding fix eliminates) could
  // still let a slower, stale response overwrite a faster, newer one. Each
  // call claims the next id; a response is applied only if no newer call
  // has started since.
  const beginLoad = useRequestSequence();

  async function loadRequirements(offset: number, append: boolean) {
    if (!projectId) return;
    const isLatest = beginLoad();
    const page = await api.getPage<Requirement>(
      `/api/v1/projects/${projectId}/requirements?${listParamsRef.current(offset).toString()}`
    );
    if (!isLatest()) return;
    setRequirements((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
  }

  async function reload() {
    if (!projectId) return;
    setRequirements(null);
    // A fresh load invalidates any prior selection (a filter/search change,
    // or the post-bulk-op reload below, may drop previously-selected rows
    // from the result set entirely) — "load more" append, by contrast,
    // calls `loadRequirements` directly and never touches this.
    setSelectedIds(new Set());
    const [comps, cats, stgs, flows] = await Promise.all([
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<StageWorkflow[]>(`/api/v1/projects/${projectId}/stage-workflows`),
      loadRequirements(0, false),
    ]);
    setComponents(comps);
    setCategories(cats);
    setStages(stgs);
    setWorkflows(flows);
  }

  useLoadOnChange(reload, [
    projectId, search, statusFilter, completedFilter, stageFrom, stageTo, phaseFilter, componentFilter, categoryFilter,
    hasCommentsOnly, onlyWatched, includeArchived, sort, tagFilter.query, projectScope.scope,
  ]);

  // Deep-linked from the Project Overview page's "New requirement" button
  // (?new=1) — opened once, then the param is stripped so a later reload
  // of this page doesn't keep reopening the form.
  const newFormRequested = searchParams.get("new") === "1";
  useResetOnChange([newFormRequested], () => {
    if (newFormRequested) setShowNewForm(true);
  }, { runOnMount: true });

  useEffect(() => {
    if (!newFormRequested) return;
    setSearchParams((params) => {
      params.delete("new");
      return params;
    }, { replace: true });
  }, [newFormRequested, setSearchParams]);

  useEffect(() => {
    if (!projectId || !user) return;
    (async () => {
      try {
        const proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`);
        setIsOrgAdminOfProject(users.some((u) => u.user_id === user.id && u.roles.includes("org_admin")));
      } catch {
        // No org role at all (rare) — canManageProject still resolves correctly
        // from myRoles alone in that case.
      }
    })();
  }, [projectId, user]);

  async function move(id: string, direction: "up" | "down") {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${id}/move`, { direction });
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // `indeterminate` isn't a settable HTML attribute/React prop — it's a
  // DOM-only property, so the "some but not all loaded rows selected"
  // visual state has to be applied imperatively via the ref, same as any
  // other indeterminate-checkbox implementation.
  useEffect(() => {
    if (!selectAllRef.current || !requirements) return;
    const own = requirements.filter((r) => !r.from_project_id);
    const selectedLoaded = own.filter((r) => selectedIds.has(r.id)).length;
    selectAllRef.current.indeterminate = selectedLoaded > 0 && selectedLoaded < own.length;
  }, [requirements, selectedIds]);

  function toggleRowSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllLoaded() {
    if (!requirements) return;
    // Rows from a related project are read-only here: bulk actions only ever touch this project's own.
    const own = requirements.filter((r) => !r.from_project_id);
    setSelectedIds((current) => {
      const allSelected = own.every((r) => current.has(r.id));
      return allSelected ? new Set() : new Set(own.map((r) => r.id));
    });
  }

  /** Runs `action` once per selected requirement, sequentially (simpler
   * than bounded concurrency and fine for the list sizes this pilot
   * targets), tolerating individual failures rather than aborting the
   * whole batch — one locked/already-archived row shouldn't block the
   * rest. Reports a CSV-import-wizard-style "N updated"/"N updated, M
   * failed" summary via the shared `Toast`, then clears the selection and
   * refreshes the list regardless of outcome. */
  async function runBulkAction(action: (r: Requirement) => Promise<void>) {
    if (!requirements) return;
    const targets = requirements.filter((r) => selectedIds.has(r.id));
    setBulkRunning(true);
    let succeeded = 0;
    let failed = 0;
    for (const r of targets) {
      try {
        await action(r);
        succeeded++;
      } catch {
        failed++;
      }
    }
    setBulkRunning(false);
    setBulkMoveStageId("");
    reload();
    if (failed > 0) {
      showToast(strings.requirements.bulkResultPartial(succeeded, failed), "error");
    } else {
      showToast(strings.requirements.bulkResultSuccess(succeeded));
    }
  }

  async function bulkArchive() {
    setBulkArchiveDialogOpen(false);
    await runBulkAction((r) => api.delete(`/api/v1/projects/${projectId}/requirements/${r.id}`));
  }

  async function bulkMoveToStage() {
    setBulkMoveDialogOpen(false);
    const targetStageId = bulkMoveStageId;
    // Mirrors `RequirementDetailPage.tsx`'s own `save()` payload exactly
    // (the direct-edit `PUT` endpoint requires the full `RequirementUpdate`
    // shape, not a partial patch) — every field except `target_stage_id`
    // carries the row's own current value forward unchanged, so the only
    // effective change is the stage.
    await runBulkAction((r) =>
      api.put(`/api/v1/projects/${projectId}/requirements/${r.id}`, {
        name: r.name,
        reasoning: r.reasoning,
        clarification: r.clarification,
        description: r.description,
        component_id: r.component_id,
        category_id: r.category_id,
        owner: principalRef(r.owner),
        target_stage_id: targetStageId,
        level: r.level,
        custom_fields: r.custom_fields,
        change_note: "Bulk move to stage.",
        review_date: r.review_date,
        review_lead_days: r.review_lead_days,
        reviewer: principalRef(r.reviewer),
      })
    );
  }

  function componentName(id: string) {
    return components.find((c) => c.id === id)?.name ?? "";
  }
  function categoryName(id: string) {
    return categories.find((c) => c.id === id)?.name ?? "";
  }
  /** The phase names the project's workflows use, each once, for the phase filter. */
  const phaseNames = [...new Set(workflows.flatMap((w) => w.phases.map((p) => p.name)))];

  /** A requirement's target: its stage, with the phase that governs it, e.g. "Release 1 (Review)". */
  function targetText(r: Requirement) {
    if (r.from_project_id) return "—";
    return r.phase_name ? `${stageName(r.target_stage_id)} (${r.phase_name})` : stageName(r.target_stage_id);
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function toggleStatusFilter(status: RequirementStatus) {
    setStatusFilter((current) => (current === status ? "" : status));
  }

  function badges(r: Requirement) {
    return (
      <>
        {r.comment_count > 0 && (
          <Tooltip label={strings.requirements.commentCountLabel(r.comment_count)}>
            <span className="row" role="img" aria-label={strings.requirements.commentCountLabel(r.comment_count)} style={{ gap: "0.2rem" }}>
              <MessageSquare size={14} /> {r.comment_count}
            </span>
          </Tooltip>
        )}
        {r.has_open_change_request && (
          <Tooltip label={strings.requirements.hasPendingChangeRequest}>
            <span role="img" aria-label={strings.requirements.hasPendingChangeRequest}>
              <GitPullRequest size={14} />
            </span>
          </Tooltip>
        )}
        {r.requires_approval && (
          <Tooltip label={strings.requirements.requiresApprovalBadge}>
            <span role="img" aria-label={strings.requirements.requiresApprovalBadge}>
              <TriangleAlert size={14} />
            </span>
          </Tooltip>
        )}
      </>
    );
  }

  return (
    <div className="stack">
      <ListPageLayout
        title={strings.requirements.title}
        ready={requirements !== null}
        loadedRows={requirements?.length}
        actions={
          <button className="btn btn-primary" onClick={() => setShowNewForm(true)}>
            <Plus size={16} /> {strings.requirements.newRequirement}
          </button>
        }
        records={{ projectId: projectId ?? "", recordType: "requirement", filters: filterParams().toString(), onImported: reload }}
        filter={
          <FilterPanel
            sectionKey="requirementsFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.requirements.search}
          >
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              allLabel="All statuses"
              options={STATUS_OPTIONS.map((s) => ({ value: s, label: REQUIREMENT_STATUS_LABEL[s] }))}
            />
            <FilterSelect
              label={strings.requirements.targetVersionFrom}
              value={stageFrom}
              onChange={(v) => setStageRange(v, stageTo)}
              allLabel={strings.requirements.firstVersion}
              options={stages.map((s) => ({ value: s.id, label: s.name }))}
            />
            <FilterSelect
              label={strings.requirements.targetVersionTo}
              value={stageTo}
              onChange={(v) => setStageRange(stageFrom, v)}
              allLabel={strings.requirements.lastVersion}
              options={stages.map((s) => ({ value: s.id, label: s.name }))}
            />
            <FilterSelect
              label={strings.requirements.phaseFilter}
              help={strings.requirements.phaseFilterHelp}
              value={phaseFilter}
              onChange={setPhaseFilter}
              allLabel={strings.requirements.allPhases}
              options={phaseNames.map((name) => ({ value: name, label: name }))}
            />
            <FilterSelect
              label={strings.requirements.component}
              value={componentFilter}
              onChange={setComponentFilter}
              allLabel={strings.requirements.allComponents}
              options={components.map((c) => ({ value: c.id, label: c.name }))}
            />
            <FilterSelect
              label={strings.requirements.category}
              value={categoryFilter}
              onChange={setCategoryFilter}
              allLabel={strings.requirements.allCategories}
              options={categories.map((c) => ({ value: c.id, label: c.name }))}
            />
            {/* C-G-11: completion is now an independent overlay marker, not a
                status value — a separate checkbox alongside the Status
                select above rather than one of its options. */}
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} components={false} />}
            <FilterCheckbox label={strings.requirements.completedFilter} checked={completedFilter} onChange={setCompletedFilter} />
            <FilterCheckbox label="Has comments" checked={hasCommentsOnly} onChange={setHasCommentsOnly} />
            <FilterCheckbox label="Only watched" checked={onlyWatched} onChange={setOnlyWatched} />
            <FilterCheckbox label={strings.requirements.includeArchived} checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >

        {showNewForm && projectId && (
          // Style guide "Pattern: modal dialog for entity create/rename" — a brand-new entity opens in a Modal, not a
          // layer that still occupies the side panel's "detail about the current view" slot.
          <RequirementCreateModal
            projectId={projectId} canManageProject={canManageProject} offerAttach
            onCreated={() => reload()} onClose={() => setShowNewForm(false)}
          />
        )}
          <div className="stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <ViewToggle mode={viewMode} onChange={setViewMode} />
            </div>

            {/* Bulk operations toolbar (style guide "Pattern: bulk operations
                on a list") — table/list view only, per this pilot's scope;
                tile view has no checkbox column to select from. Sits directly
                above the table rather than replacing the search/view-toggle
                row above, so it's visible without scrolling away from the
                list it acts on. Gated on `canManageProject` the same way the
                checkbox column itself is (see below) — both bulk actions
                require the same manager/administrator role the single-row
                Archive button already requires on `RequirementDetailPage.tsx`. */}
            {viewMode === "list" && canManageProject && selectedIds.size > 0 && (
              <div className="card row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "var(--space-3)" }}>
                <div className="row" style={{ gap: "var(--space-4)", alignItems: "center" }}>
                  <strong>{strings.requirements.bulkSelectedCount(selectedIds.size)}</strong>
                  <button className="btn" onClick={() => setSelectedIds(new Set())} disabled={bulkRunning}>
                    {strings.requirements.bulkClearSelection}
                  </button>
                </div>
                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <button className="btn" onClick={() => setBulkTagDialogOpen(true)} disabled={bulkRunning}>
                    {strings.requirements.bulkTagSelected}
                  </button>
                  <button className="btn btn-danger" onClick={() => setBulkArchiveDialogOpen(true)} disabled={bulkRunning}>
                    {strings.requirements.bulkArchiveSelected}
                  </button>
                  <button
                    ref={bulkMoveTriggerRef}
                    className="btn"
                    onClick={() => {
                      setBulkMoveStageId((current) => current || stages[0]?.id || "");
                      setBulkMovePopoverOpen((v) => !v);
                    }}
                    disabled={bulkRunning || stages.length === 0}
                  >
                    {strings.requirements.bulkMoveToStage}
                  </button>
                  {bulkMovePopoverOpen && (
                    <Popover anchorRef={bulkMoveTriggerRef} title={strings.requirements.bulkMoveToStage} onClose={() => setBulkMovePopoverOpen(false)}>
                      <div className="stack" style={{ gap: "var(--space-3)", minWidth: 200 }}>
                        <InlineSelect
                          ariaLabel={strings.requirements.targetVersion}
                          value={bulkMoveStageId}
                          placeholder={null}
                          onChange={setBulkMoveStageId}
                          options={stages.map((s) => ({ value: s.id, label: s.name }))}
                        />
                        <button
                          className="btn btn-primary"
                          disabled={!bulkMoveStageId}
                          onClick={() => {
                            setBulkMovePopoverOpen(false);
                            setBulkMoveDialogOpen(true);
                          }}
                        >
                          {strings.requirements.bulkMoveApply}
                        </button>
                      </div>
                    </Popover>
                  )}
                </div>
              </div>
            )}

            {bulkArchiveDialogOpen && (
              <ConfirmDialog
                title={strings.requirements.bulkArchiveTitle(selectedIds.size)}
                message={strings.requirements.bulkArchiveConfirm}
                confirmLabel={strings.requirements.bulkArchiveSelected}
                onConfirm={bulkArchive}
                onCancel={() => setBulkArchiveDialogOpen(false)}
              />
            )}

            {bulkTagDialogOpen && projectId && (
              <BulkTagDialog
                api={projectTagAdminApi(projectId)}
                artefactType="requirement"
                ids={[...selectedIds]}
                title={strings.requirements.bulkTagTitle(selectedIds.size)}
                onClose={() => setBulkTagDialogOpen(false)}
                onApplied={async (result) => {
                  setBulkTagDialogOpen(false);
                  showToast(strings.tags.admin.reclassifyDone(result.matched));
                  await reload();
                }}
              />
            )}

            {bulkMoveDialogOpen && (
              <ConfirmDialog
                title={strings.requirements.bulkMoveTitle(selectedIds.size, stageName(bulkMoveStageId))}
                message={strings.requirements.bulkMoveConfirm}
                confirmLabel={strings.requirements.bulkMoveApply}
                onConfirm={bulkMoveToStage}
                onCancel={() => setBulkMoveDialogOpen(false)}
              />
            )}

            {!requirements && <Spinner />}
            {requirements && requirements.length === 0 && <p className="text-muted">{strings.requirements.empty}</p>}
            {requirements && requirements.length > 0 && viewMode === "tiles" && (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
                {requirements.map((r) => (
                  <div
                    key={r.id}
                    className="card stack entity-accent-card"
                    style={{ gap: "var(--space-3)", ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.requirement }}
                  >
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                      <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                        <RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} />
                      </span>
                      {!r.from_project_id && (
                        <div className="row" style={{ gap: "var(--space-1)" }}>
                          <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                            <ArrowUp />
                          </button>
                          <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                            <ArrowDown />
                          </button>
                        </div>
                      )}
                    </div>
                    <Link to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`} style={{ fontWeight: 600 }}>
                      {r.name}
                    </Link>
                    <ProjectScopeLabel row={r} />
                    {r.reasoning && (
                      <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                        {r.reasoning.length > 140 ? `${r.reasoning.slice(0, 140)}…` : r.reasoning}
                      </p>
                    )}
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="row" style={{ gap: "var(--space-2)" }}>
                        <FilterBadge
                          active={statusFilter === r.status}
                          tone={REQUIREMENT_STATUS_TONE[r.status]}
                          onClick={() => toggleStatusFilter(r.status)}
                        >
                          {REQUIREMENT_STATUS_LABEL[r.status]}
                        </FilterBadge>
                        {/* C-G-11: rendered as its own badge, distinct from
                            the status badge above (which stays "Approved"
                            for a completed requirement) — completion is now
                            an independent overlay, not a merged status. */}
                        {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
                        {r.is_locked && <Badge>{strings.requirements.locked}</Badge>}
                        {r.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
                      </div>
                      <div className="row" style={{ gap: "var(--space-3)" }}>{badges(r)}</div>
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {r.from_project_id ? "—" : `${componentName(r.component_id)} · ${categoryName(r.category_id)}`}
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                      Target: {targetText(r)} · Level: {REQUIREMENT_LEVEL_LABEL[r.level]}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {requirements && requirements.length > 0 && viewMode === "list" && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      {canManageProject && (
                        <th style={{ width: "3%" }}>
                          <input
                            ref={selectAllRef}
                            type="checkbox"
                            checked={requirements.some((r) => !r.from_project_id) && requirements.every((r) => r.from_project_id || selectedIds.has(r.id))}
                            onChange={toggleSelectAllLoaded}
                            aria-label={strings.requirements.bulkSelectAll}
                          />
                        </th>
                      )}
                      <SortableHeader
                        style={{ width: "9%" }} label="ID" sortKey="unique_code" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        style={{ width: "38%" }} label="Name" sortKey="name" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        label={strings.changeRequests.status} sortKey="status" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <th>Target · level</th>
                      <th>Component · category</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {requirements.map((r) => (
                      <tr
                        key={r.id}
                        className="entity-accent-row"
                        style={{ ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.requirement }}
                      >
                        {canManageProject && (
                          <td>
                            {!r.from_project_id && (
                              <input
                                type="checkbox"
                                checked={selectedIds.has(r.id)}
                                onChange={() => toggleRowSelected(r.id)}
                                aria-label={strings.requirements.bulkSelectRow(`${r.unique_code} ${r.name}`)}
                              />
                            )}
                          </td>
                        )}
                        <td className="text-muted"><RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} /></td>
                        <td>
                          <Link to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`}>{r.name}</Link>
                          <ProjectScopeLabel row={r} />
                        </td>
                        <td>
                          <div className="row" style={{ gap: "var(--space-2)" }}>
                            <FilterBadge
                              active={statusFilter === r.status}
                              tone={REQUIREMENT_STATUS_TONE[r.status]}
                              onClick={() => toggleStatusFilter(r.status)}
                            >
                              {REQUIREMENT_STATUS_LABEL[r.status]}
                            </FilterBadge>
                            {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
                            {r.is_locked && <Badge>{strings.requirements.locked}</Badge>}
                            {r.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
                            {badges(r)}
                          </div>
                        </td>
                        <td className="text-muted">
                          {targetText(r)} · {REQUIREMENT_LEVEL_LABEL[r.level]}
                        </td>
                        <td className="text-muted">
                          {r.from_project_id ? "—" : `${componentName(r.component_id)} · ${categoryName(r.category_id)}`}
                        </td>
                        <td>
                          {!r.from_project_id && (
                            <div className="row" style={{ gap: "var(--space-1)" }}>
                              <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                                <ArrowUp />
                              </button>
                              <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                                <ArrowDown />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {requirements && (
              <LoadMoreButton
                loaded={requirements.length}
                total={total}
                onClick={() => loadRequirements(requirements.length, true)}
              />
            )}
          </div>
      </ListPageLayout>
    </div>
  );
}
