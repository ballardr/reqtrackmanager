import { ArrowDown, ArrowUp, GitPullRequest, MessageSquare, Plus, TriangleAlert } from "lucide-react";
import { MarkdownSummary } from "../components/MarkdownSummary";
import { RequirementListCode } from "../components/RequirementListCode";
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
import { DirectoryTable, type DirectoryColumn } from "../components/DirectoryTable";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Popover } from "../components/Popover";
import { BulkTagDialog } from "../components/BulkTagDialog";
import { projectTagAdminApi } from "../api/tags";
import { TagFilterField } from "../components/TagFilterField";
import { ReferencesCell } from "../components/ReferencesCell";
import { Spinner } from "../components/Spinner";
import { TileCard, TileGrid } from "../components/TileCard";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { useOptionalColumns } from "../hooks/useOptionalColumns";
import { usePageReferences } from "../hooks/usePageReferences";
import { useTagFilter } from "../hooks/useTagFilter";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useProjectScope } from "../hooks/useProjectScope";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { SortField } from "../components/SortField";
import { addSortParams, TIME_SORT_KEYS, useListSort } from "../hooks/useListSort";
import { useUrlChoice, useUrlFlag, useUrlText } from "../hooks/useUrlFilter";
import { addSharedListFilters } from "../utils/listFilterParams";
import { InlineSelect } from "../components/LabeledSelect";

const PAGE_SIZE = 30;

// C-G-11: "completed" is no longer a `RequirementStatus` value — it's an
// independent overlay marker (`Requirement.is_completed`), filtered via its
// own `FilterCheckbox` below rather than a status option.
const STATUS_OPTIONS: RequirementStatus[] = ["draft", "reviewed", "approved", "archived"];
/**
 * The sort keys of the list. `component` is the default order (C-G-04: component, then category, then the project's own
 * order); it has no direction and the server is sent no `sort` for it.
 */
const COMPONENT_ORDER = "component";
const SORT_KEYS = [COMPONENT_ORDER, "unique_code", "name", "status", "target", "placement", "references", ...TIME_SORT_KEYS] as const;

/**
 * Requirement browser (C-G-04: sorted by component/category): search by name/ID
 * (U-E-01), filter panel, scoping-stage-only reordering (C-E-03) and
 * incremental "load more" pagination (U-P-06).
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
  // The External references column, read for the page's rows at once; shown only when a row has a reference.
  const referenced = usePageReferences(projectId, "requirement", (requirements ?? []).filter((r) => !r.from_project_id).map((r) => r.id));
  const showReferences = Object.keys(referenced).length > 0;
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
  // Older links and bookmarks carry the single `component` and `category` filters; they move onto the shared
  // component filter (`in_component`, `in_category`) so the page shows and keeps one choice.
  const legacyComponent = searchParams.get("component");
  const legacyCategory = searchParams.get("category");
  useEffect(() => {
    if (!legacyComponent && !legacyCategory) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("component");
      next.delete("category");
      if (legacyComponent && !next.getAll("in_component").includes(legacyComponent)) next.append("in_component", legacyComponent);
      if (legacyCategory && !next.getAll("in_category").includes(legacyCategory)) next.append("in_category", legacyCategory);
      return next;
    }, { replace: true });
  }, [legacyComponent, legacyCategory, setSearchParams]);
  // The phase that governs a requirement: its component's own track when component phases are on, else its stage's.
  const [phaseFilter, setPhaseFilter] = useUrlText("phase");
  const [hasCommentsOnly, setHasCommentsOnly] = useUrlFlag("comments");
  const [onlyWatched, setOnlyWatched] = useUrlFlag("watched");
  // An archived requirement's detail page has the Restore button; this filter is how the list reaches one.
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  // The list is backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so sorting is a `sort`/`order` query
  // parameter the backend honours; sorting only the loaded rows would misrepresent the full-list order.
  const listSort = useListSort("requirements", SORT_KEYS, COMPONENT_ORDER);
  // The component and category order has no column header: the headers show no arrow while it is in force.
  const headerSort = listSort.sort.key === COMPONENT_ORDER ? null : listSort.sort;
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const [showNewForm, setShowNewForm] = useState(false);
  const [viewMode, setViewMode] = useViewMode("requirements");

  // --- Bulk operations (list view only) ---------------------------------
  // Style guide "Pattern: bulk operations on a list". Selection is a Set of ids
  // so it survives "load more" appends; "select all" means all loaded rows
  // (U-P-06 pagination makes "all matching the filter" unsafe to promise).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkArchiveDialogOpen, setBulkArchiveDialogOpen] = useState(false);
  const [bulkMovePopoverOpen, setBulkMovePopoverOpen] = useState(false);
  const [bulkTagDialogOpen, setBulkTagDialogOpen] = useState(false);
  const [bulkMoveStageId, setBulkMoveStageId] = useState("");
  const [bulkMoveDialogOpen, setBulkMoveDialogOpen] = useState(false);
  const bulkMoveTriggerRef = useRef<HTMLButtonElement>(null);

  /** The list's filters, by the names its list request and the shared export both take (no paging or sort). */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (completedFilter) params.set("is_completed", "true");
    if (stageFrom) params.set("target_stage_from_id", stageFrom);
    if (stageTo) params.set("target_stage_to_id", stageTo);
    if (phaseFilter) params.set("phase", phaseFilter);
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
    if (headerSort) addSortParams(params, headerSort);
    return params;
  }

  // Read through a ref so a reload resuming after an `await` lists with the
  // filters set since, instead of overwriting the filtered results. Declared
  // before the reload effect so it is current there.
  const listParamsRef = useLatest(listParams);

  // Guards any two overlapping fetches (rapid filter changes, mount-time race)
  // so a slower, stale response cannot overwrite a newer one: each call claims
  // the next id and a response applies only if no newer call has started.
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
    // A fresh load (filter/search change, post-bulk-op reload) invalidates the
    // selection; "load more" calls `loadRequirements` directly and keeps it.
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

  /** The choices of the Sort by field: the default order, then each sortable column. */
  const sortColumns = [
    { key: COMPONENT_ORDER, label: strings.requirements.sortComponentOrder, sortable: true },
    { key: "unique_code", label: "ID", sortable: true },
    { key: "name", label: "Name", sortable: true },
    { key: "status", label: strings.changeRequests.status, sortable: true },
    { key: "target", label: "Target · level", sortable: true },
    { key: "placement", label: "Component · category", sortable: true },
    { key: "references", label: strings.references.column, sortable: true },
  ];

  useLoadOnChange(reload, [
    projectId, search, statusFilter, completedFilter, stageFrom, stageTo, phaseFilter,
    hasCommentsOnly, onlyWatched, includeArchived, listSort.sort, tagFilter.query, projectScope.scope,
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

  /** Runs `action` once per selected requirement, sequentially, tolerating
   * individual failures so one locked or archived row does not block the rest.
   * Reports "N updated"/"N updated, M failed" via `Toast`, then clears the
   * selection and refreshes the list. */
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
    // Mirrors `RequirementDetailPage.tsx`'s `save()` payload: the direct-edit
    // `PUT` needs the full `RequirementUpdate`, so every field except
    // `target_stage_id` carries the row's current value.
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

  /** Every column the list can draw; the person chooses the optional ones (`useOptionalColumns`). */
  const columns: DirectoryColumn<Requirement>[] = [
    {
      key: "unique_code", label: "ID", sortable: true,
      render: (r) => <span className="text-muted"><RequirementListCode requirement={r} componentIds={tagFilter.components} categoryIds={tagFilter.categories} /></span>,
    },
    {
      key: "name", label: "Name", sortable: true,
      render: (r) => (
        <>
          <Link to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`}>{r.name}</Link>
          <ProjectScopeLabel row={r} />
        </>
      ),
    },
    {
      key: "status", label: strings.changeRequests.status, sortable: true,
      render: (r) => (
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <FilterBadge active={statusFilter === r.status} tone={REQUIREMENT_STATUS_TONE[r.status]} onClick={() => toggleStatusFilter(r.status)}>
            {REQUIREMENT_STATUS_LABEL[r.status]}
          </FilterBadge>
          {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
          {r.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
          {badges(r)}
        </div>
      ),
    },
    {
      key: "target", label: "Target · level", sortable: true, optional: true, chooserLabel: "Target and level",
      render: (r) => <span className="text-muted">{targetText(r)} · {REQUIREMENT_LEVEL_LABEL[r.level]}</span>,
    },
    {
      key: "placement", label: "Component · category", sortable: true, optional: true, chooserLabel: "Component and category",
      render: (r) => <span className="text-muted">{r.from_project_id ? "—" : `${componentName(r.component_id)} · ${categoryName(r.category_id)}`}</span>,
    },
    ...(showReferences
      ? [{
          key: "references", label: strings.references.column, sortable: true, optional: true,
          render: (r: Requirement) => <ReferencesCell references={referenced[r.id]} />,
        } as DirectoryColumn<Requirement>]
      : []),
    {
      key: "order", label: <span className="sr-only">{strings.requirements.sortComponentOrder}</span>,
      render: (r) => !r.from_project_id && (
        <div className="row" style={{ gap: "var(--space-1)" }}>
          <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
            <ArrowUp />
          </button>
          <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
            <ArrowDown />
          </button>
        </div>
      ),
    },
  ];
  const shown = useOptionalColumns("requirements", columns);

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
        columnChooser={shown.chooser}
        records={{ projectId: projectId ?? "", recordType: "requirement", filters: (headerSort ? addSortParams(filterParams(), headerSort) : filterParams()).toString(), onImported: reload }}
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
            {/* C-G-11: completion is now an independent overlay marker, not a
                status value — a separate checkbox alongside the Status
                select above rather than one of its options. */}
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <SortField
              list={listSort} columns={sortColumns} codeKey="unique_code" titleKey="name" fixedOrder={[COMPONENT_ORDER]}
              describe={{ [COMPONENT_ORDER]: strings.requirements.sortComponentOrderHelp }}
            />
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

            {/* Bulk toolbar (style guide "Pattern: bulk operations on a list"):
                list view only (tile view has no checkbox column), directly above
                the table, gated on `canManageProject` like the checkbox column
                (both actions need the role the single-row Archive requires). */}
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
              <TileGrid>
                {requirements.map((r) => (
                  <TileCard
                    key={r.id}
                    title={r.name}
                    to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`}
                    accentColor={ENTITY_ACCENT_COLOR.requirement}
                    eyebrow={
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                        <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                          <RequirementListCode requirement={r} componentIds={tagFilter.components} categoryIds={tagFilter.categories} />
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
                    }
                  >
                    <ProjectScopeLabel row={r} />
                    {r.description && <MarkdownSummary text={r.description} math className="text-muted" style={{ fontSize: "0.85rem" }} />}
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="row" style={{ gap: "var(--space-2)" }}>
                        <FilterBadge
                          active={statusFilter === r.status}
                          tone={REQUIREMENT_STATUS_TONE[r.status]}
                          onClick={() => toggleStatusFilter(r.status)}
                        >
                          {REQUIREMENT_STATUS_LABEL[r.status]}
                        </FilterBadge>
                        {/* C-G-11: own badge; completion is independent of the
                            status badge, which stays "Approved". */}
                        {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
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
                  </TileCard>
                ))}
              </TileGrid>
            )}
            {requirements && requirements.length > 0 && viewMode === "list" && (
              <DirectoryTable
                ariaLabel={strings.requirements.title} columns={shown.columns} rows={requirements} rowKey={(r) => r.id}
                rowAccent={ENTITY_ACCENT_COLOR.requirement}
                selection={canManageProject ? {
                  selected: selectedIds, onChange: setSelectedIds, selectable: (r) => !r.from_project_id,
                  label: (r) => strings.requirements.bulkSelectRow(`${r.unique_code} ${r.name}`),
                  allLabel: strings.requirements.bulkSelectAll,
                } : undefined}
                sort={headerSort} onSort={listSort.onHeaderSort}
                emptyState={null}
              />
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
