import { Plus } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { ChangeRequest, ChangeRequestStatus, ProjectStage, Requirement } from "../api/types";
import {
  CHANGE_REQUEST_STATUS_LABEL,
  CHANGE_REQUEST_STATUS_TONE,
  ENTITY_ACCENT_COLOR,
  REQUIREMENT_LEVEL_LABEL,
} from "../api/types";
import { ChangeRequestCreateModal } from "../components/ChangeRequestCreateModal";
import { FilterBadge } from "../components/FilterBadge";
import { FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { ListPageLayout } from "../components/ListPageLayout";
import { TagFilterField } from "../components/TagFilterField";
import { placementsText } from "../api/placements";
import { usePagePlacements } from "../hooks/usePagePlacements";
import { usePageReferences } from "../hooks/usePageReferences";
import { useTagFilter } from "../hooks/useTagFilter";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { SortableHeader } from "../components/SortableHeader";
import { ReferencesCell } from "../components/ReferencesCell";
import { LoadFailed } from "../components/LoadFailed";
import { Spinner } from "../components/Spinner";
import { TileCard, TileGrid } from "../components/TileCard";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useStrings, useTerm } from "../context/TerminologyContext";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useProjectScope } from "../hooks/useProjectScope";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { SortField } from "../components/SortField";
import { addSortParams, TIME_SORT_KEYS, useListSort } from "../hooks/useListSort";
import { useUrlChoice, useUrlText } from "../hooks/useUrlFilter";
import { addSharedListFilters } from "../utils/listFilterParams";

const PAGE_SIZE = 30;
const SORT_KEYS = ["unique_code", "proposed_name", "status", ...TIME_SORT_KEYS] as const;

const CR_STATUS_OPTIONS: ChangeRequestStatus[] = [
  "draft", "submitted", "in_review", "approved", "rejected", "withdrawn",
];
const STATUS_PARAMS: readonly (ChangeRequestStatus | "all")[] = [...CR_STATUS_OPTIONS, "all"];

// Tri-state status filter. "active" (default) sends `active_only=true` and no `cr_status`, narrowing
// to the non-terminal statuses like the backend's `active_only`; "" ("All statuses") sends neither;
// a `ChangeRequestStatus` sends `cr_status`. The "active" sentinel keeps the three states distinct.
type CrStatusFilterValue = ChangeRequestStatus | "" | "active";

/** Change request list and creation form (C-G-03), with "load more" pagination (U-P-06).
 *
 * For MODIFY_REQUIREMENT the form is field-toggle driven: a field is editable and submitted in
 * `changed_fields` only once ticked, pre-filled from the selected requirement's current version.
 * NEW_REQUIREMENT has nothing to diff against, so every field is always changed.
 */
export function ChangeRequestsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
  const placed = usePagePlacements(projectId, "change_request", (crs ?? []).map((cr) => cr.id));
  const showPlaces = Object.keys(placed).length > 0;
  const referenced = usePageReferences(projectId, "change_request", (crs ?? []).map((cr) => cr.id));
  const showReferences = Object.keys(referenced).length > 0;
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count, shown by `ResultCount` beside the filtered `total`.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const changeRequestTerm = useTerm("change_request");
  const [viewMode, setViewMode] = useViewMode("change-requests");
  // The list's filters, search and sort live in the URL (`useUrlFilter`), so it comes back as it was left
  // after a visit to a record; the dashboard's CR tiles link here with `status`. "Active" (the default)
  // is no parameter, "all statuses" is `status=all`.
  const [statusParam, setStatusParam] = useUrlChoice("status", STATUS_PARAMS);
  const statusFilter: CrStatusFilterValue = statusParam === "" ? "active" : statusParam === "all" ? "" : statusParam;
  const setStatusFilter = (next: CrStatusFilterValue) => setStatusParam(next === "active" ? "" : next === "" ? "all" : next);
  const [targetStageFilter, setTargetStageFilter] = useUrlText("stage");
  // Free-text search, server-side like the requirements list's, so it finds a change request on any page.
  const [search, setSearch] = useUrlText("q");
  // Sorting is server-side (`sort`/`order`): the list is paginated, so a client sort would reorder only the loaded page.
  const listSort = useListSort("change_requests", SORT_KEYS, "unique_code");
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  /** The list's filters, by the names its list request and the shared export both take (no paging or sort). */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter === "active") params.set("active_only", "true");
    else if (statusFilter) params.set("cr_status", statusFilter);
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(limitFor(offset)), offset: String(offset) });
    filterParams().forEach((value, key) => params.append(key, value));
    return addSortParams(params, listSort.sort);
  }

  // Read through a ref so a reload resuming after an `await` in an older render still lists with the
  // current filters instead of overwriting the filtered results. Declared before the reload effect.
  const listParamsRef = useLatest(listParams);

  // Discards a response when a newer request has started (e.g. rapid filter changes).
  const beginLoad = useRequestSequence();

  async function loadChangeRequests(offset: number, append: boolean) {
    if (!projectId) return;
    const isLatest = beginLoad();
    const page = await api.getPage<ChangeRequest>(
      `/api/v1/projects/${projectId}/change-requests?${listParamsRef.current(offset).toString()}`
    );
    if (!isLatest()) return;
    setCrs((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
  }

  async function reload() {
    if (!projectId) return;
    const [reqs, stgs] = await Promise.all([
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      loadChangeRequests(0, false),
    ]);
    setRequirements(reqs);
    setStages(stgs);
  }

  // A refused read shows the failure with Retry instead of leaving the spinner up; a later success clears it.
  const [failed, setFailed] = useState(false);
  function reloadShowingFailure() {
    setFailed(false);
    return reload().catch(() => setFailed(true));
  }
  useLoadOnChange(reloadShowingFailure, [projectId, statusFilter, targetStageFilter, listSort.sort, search, tagFilter.query, projectScope.scope]);

  // Deep-linked from a requirement's "Make change request" button
  // (?requirement=<id>) — pre-selects that requirement for a
  // MODIFY_REQUIREMENT change request and opens the form.
  const deepLinkedRequirementId = searchParams.get("requirement");
  // Kept in state because the parameter is stripped from the URL as soon as the form opens.
  const [formRequirementId, setFormRequirementId] = useState<string | undefined>(undefined);
  useResetOnChange([deepLinkedRequirementId], () => {
    if (deepLinkedRequirementId) {
      setFormRequirementId(deepLinkedRequirementId);
      setShowForm(true);
    }
  }, { runOnMount: true });

  useEffect(() => {
    if (!deepLinkedRequirementId) return;
    setSearchParams((params) => {
      params.delete("requirement");
      return params;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkedRequirementId]);

  /** The columns the table can be ordered by, for the Sort by choices. */
  const sortColumns = [
    { key: "unique_code", label: "Code", sortable: true },
    { key: "proposed_name", label: "Name", sortable: true },
    { key: "status", label: strings.changeRequests.status, sortable: true },
    { key: "created", label: "Created", sortable: true },
  ];

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function requirementById(id: string | null) {
    return id ? requirements.find((r) => r.id === id) ?? null : null;
  }

  // A MODIFY_REQUIREMENT change request's proposed_* value is null for any
  // field not in `changed_fields` — fall back to the target requirement's
  // current value so the list/tile views never show a blank title.
  function crTitle(cr: ChangeRequest): string {
    if (cr.proposed_name) return cr.proposed_name;
    return requirementById(cr.requirement_id)?.name ?? changeRequestTerm;
  }

  function crTargetLabel(cr: ChangeRequest): string {
    if (cr.proposed_target_stage_id) return stageName(cr.proposed_target_stage_id);
    const requirement = requirementById(cr.requirement_id);
    return requirement ? stageName(requirement.target_stage_id) : "—";
  }

  function crLevelLabel(cr: ChangeRequest): string {
    if (cr.proposed_level) return REQUIREMENT_LEVEL_LABEL[cr.proposed_level];
    const requirement = requirementById(cr.requirement_id);
    return REQUIREMENT_LEVEL_LABEL[requirement?.level ?? "requirement"];
  }

  function toggleStatusFilter(status: ChangeRequestStatus) {
    setStatusFilter(statusFilter === status ? "" : status);
  }

  function toggleTargetStageFilter(stageId: string | null) {
    if (!stageId) return;
    setTargetStageFilter((current) => (current === stageId ? "" : stageId));
  }

  return (
    <div className="stack">
      <ListPageLayout
        ready={crs !== null}
        loadedRows={crs?.length}
        title={strings.changeRequests.title}
        actions={
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <Plus /> {strings.changeRequests.newChangeRequest}
          </button>
        }
        records={{ projectId: projectId ?? "", recordType: "change_request", filters: addSortParams(filterParams(), listSort.sort).toString(), onImported: reload }}
        filter={
          <FilterPanel
            sectionKey="changeRequestsFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.changeRequests.search}
          >
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              options={[{ value: "active", label: "Active" }, { value: "", label: "All statuses" }, ...CR_STATUS_OPTIONS.map((s) => ({ value: s, label: CHANGE_REQUEST_STATUS_LABEL[s] }))]}
            />
            <FilterSelect
              label={strings.filters.targetVersion}
              value={targetStageFilter}
              onChange={setTargetStageFilter}
              allLabel="All versions"
              options={stages.map((s) => ({ value: s.id, label: s.name }))}
            />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <SortField list={listSort} columns={sortColumns} codeKey="unique_code" titleKey="proposed_name" />
          </FilterPanel>
        }
      >
        {showForm && projectId && (
          // Style guide "Pattern: modal dialog for entity create/rename" — a brand-new entity opens in a Modal, not a
          // permanently-visible inline block that reflows the list underneath it.
          <ChangeRequestCreateModal
            projectId={projectId} defaultRequirementId={formRequirementId}
            onCreated={() => reload()} onClose={() => { setShowForm(false); setFormRequirementId(undefined); }}
          />
        )}
          <div className="stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <ViewToggle mode={viewMode} onChange={setViewMode} />
            </div>

            {failed && <LoadFailed message={strings.requestFailure.loadFailed(strings.requestFailure.changeRequests)} onRetry={() => void reloadShowingFailure()} />}
            {!crs && !failed && <Spinner />}
            {crs && crs.length === 0 && <p className="text-muted">{strings.changeRequests.empty}</p>}
            {crs && crs.length > 0 && viewMode === "list" && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <SortableHeader
                        label="Code" sortKey="unique_code" sort={listSort.sort}
                        onSort={listSort.onHeaderSort}
                      />
                      <SortableHeader
                        label="Name" sortKey="proposed_name" sort={listSort.sort}
                        onSort={listSort.onHeaderSort}
                      />
                      <SortableHeader
                        label={strings.changeRequests.status} sortKey="status" sort={listSort.sort}
                        onSort={listSort.onHeaderSort}
                      />
                      <th>Target</th>
                      <th>Level</th>
                      <SortableHeader
                        label="Created" sortKey="created" sort={listSort.sort}
                        onSort={listSort.onHeaderSort}
                      />
                      {showPlaces && <th>{strings.placements.label}</th>}
                      {showReferences && <th>{strings.references.column}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {crs.map((cr) => (
                      <tr
                        key={cr.id}
                        className="entity-accent-row"
                        style={{ ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.change_request }}
                      >
                        <td className="text-muted"><RecordCode code={cr.unique_code} ownerProjectCode={cr.from_project_code} /></td>
                        <td>
                          <Link to={`/projects/${rowProjectId(cr, projectId ?? "")}/change-requests/${cr.id}`}>{crTitle(cr)}</Link>
                          <ProjectScopeLabel row={cr} />
                        </td>
                        <td>
                          <FilterBadge
                            active={statusFilter === cr.status}
                            tone={CHANGE_REQUEST_STATUS_TONE[cr.status]}
                            onClick={() => toggleStatusFilter(cr.status)}
                          >
                            {CHANGE_REQUEST_STATUS_LABEL[cr.status]}
                          </FilterBadge>
                        </td>
                        <td className="text-muted">{crTargetLabel(cr)}</td>
                        <td className="text-muted">{crLevelLabel(cr)}</td>
                        <td>{new Date(cr.created_at).toLocaleString()}</td>
                        {showPlaces && <td className="text-muted">{placementsText(placed[cr.id])}</td>}
                        {showReferences && <td><ReferencesCell references={referenced[cr.id]} /></td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {crs && crs.length > 0 && viewMode === "tiles" && (
              <TileGrid>
                {crs.map((cr) => (
                  <TileCard
                    key={cr.id}
                    title={crTitle(cr)}
                    to={`/projects/${rowProjectId(cr, projectId ?? "")}/change-requests/${cr.id}`}
                    accentColor={ENTITY_ACCENT_COLOR.change_request}
                  >
                    <small className="text-muted"><RecordCode code={cr.unique_code} ownerProjectCode={cr.from_project_code} /></small>
                    <ProjectScopeLabel row={cr} />
                    <div className="row" style={{ gap: "var(--space-2)" }}>
                      <FilterBadge
                        active={statusFilter === cr.status}
                        tone={CHANGE_REQUEST_STATUS_TONE[cr.status]}
                        onClick={() => toggleStatusFilter(cr.status)}
                      >
                        {CHANGE_REQUEST_STATUS_LABEL[cr.status]}
                      </FilterBadge>
                      {cr.proposed_target_stage_id && (
                        <FilterBadge
                          active={targetStageFilter === cr.proposed_target_stage_id}
                          onClick={() => toggleTargetStageFilter(cr.proposed_target_stage_id)}
                        >
                          {crTargetLabel(cr)}
                        </FilterBadge>
                      )}
                      <Badge>{crLevelLabel(cr)}</Badge>
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {new Date(cr.created_at).toLocaleString()}
                    </div>
                  </TileCard>
                ))}
              </TileGrid>
            )}
            {crs && <LoadMoreButton loaded={crs.length} total={total} onClick={() => loadChangeRequests(crs.length, true)} />}
          </div>
      </ListPageLayout>
    </div>
  );
}
