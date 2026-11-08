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
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { TagFilterField } from "../components/TagFilterField";
import { placementsText } from "../api/placements";
import { usePagePlacements } from "../hooks/usePagePlacements";
import { useTagFilter } from "../hooks/useTagFilter";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { SortableHeader } from "../components/SortableHeader";
import { cycleSort } from "../components/sortState";
import { Spinner } from "../components/Spinner";
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
import { useUrlChoice, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { addSharedListFilters } from "../utils/listFilterParams";

const PAGE_SIZE = 30;
const SORT_KEYS = ["proposed_name", "status", "created_at"] as const;

const CR_STATUS_OPTIONS: ChangeRequestStatus[] = [
  "draft", "submitted", "in_review", "approved", "rejected", "withdrawn",
];
const STATUS_PARAMS: readonly (ChangeRequestStatus | "all")[] = [...CR_STATUS_OPTIONS, "all"];

// Tri-state status filter — a change request list is
// usually consulted for what still needs a decision, not a permanent
// archive of every decision ever made, so the default view narrows to the
// three non-terminal statuses (draft/submitted/in_review, matching the
// backend's own `active_only` filter in
// `backend/app/routers/change_requests.py::list_change_requests`).
// "active" (default) sends `active_only=true` and no `cr_status`; "" ("All
// statuses") sends neither param; a specific `ChangeRequestStatus` sends
// `cr_status` as before. A sentinel string distinct from both "" and any
// real status value is needed so the three states are distinguishable in
// the `<select>` and in `listParams()` below.
type CrStatusFilterValue = ChangeRequestStatus | "" | "active";

/** Change request list and creation form (introduction, C-G-03), with
 * incremental "load more" pagination (U-P-06) for large CR sets.
 *
 * For a MODIFY_REQUIREMENT change request, the form is field-toggle driven:
 * a field's proposed value is only editable (and only submitted as part of
 * `changed_fields`) once its checkbox is ticked, and it's pre-filled from
 * the selected requirement's current version the moment it's toggled on or
 * the selected requirement changes — the user never has to copy values
 * across by hand. NEW_REQUIREMENT change requests have no existing
 * requirement to diff against, so every field is always "changed" and the
 * form looks like a normal create form.
 */
export function ChangeRequestsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
  const placed = usePagePlacements(projectId, "change_request", (crs ?? []).map((cr) => cr.id));
  const showPlaces = Object.keys(placed).length > 0;
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count — powers
  // `ResultCount` in `FilterPanel`'s header alongside `total` above, which
  // is the filtered count.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const changeRequestTerm = useTerm("change_request");
  const [viewMode, setViewMode] = useViewMode("change-requests");
  // Seeded directly from the URL on initial render, not set in a separate
  // effect after mount (bug fix, 2026-08: dashboard glance navigation race
  // — same fix and reasoning as `RequirementsPage.tsx`'s identical
  // two-effect shape) — only one filter state, and therefore only one
  // fetch, ever exists per mount.
  // The list's filters, search and sort live in the URL (`useUrlFilter`), so it comes back as it was left
  // after a visit to a record; the dashboard's CR tiles link here with `status`. "Active" (the default)
  // is no parameter, "all statuses" is `status=all`.
  const [statusParam, setStatusParam] = useUrlChoice("status", STATUS_PARAMS);
  const statusFilter: CrStatusFilterValue = statusParam === "" ? "active" : statusParam === "all" ? "" : statusParam;
  const setStatusFilter = (next: CrStatusFilterValue) => setStatusParam(next === "active" ? "" : next === "" ? "all" : next);
  const [targetStageFilter, setTargetStageFilter] = useUrlText("stage");
  // Free-text search, server-side like the requirements list's, so it finds a change request on any page.
  const [search, setSearch] = useUrlText("q");
  // Column-header sorting — backend `sort`/`order` param, same reasoning as `RequirementsPage.tsx`: this
  // list is backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so a client-side sort would only reorder the
  // currently-loaded page.
  const [sort, setSort] = useUrlSort(SORT_KEYS);
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
  // navigation race), same reasoning as `RequirementsPage.tsx`'s identical
  // guard — discards a response if a newer request has since been kicked
  // off, covering any overlapping-fetch path beyond the mount-time race the
  // searchParams-seeding fix above eliminates (e.g. rapid filter changes).
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

  useLoadOnChange(reload, [projectId, statusFilter, targetStageFilter, sort, search, tagFilter.query, projectScope.scope]);

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
        records={{ projectId: projectId ?? "", recordType: "change_request", filters: filterParams().toString(), onImported: reload }}
        filter={
          <FilterPanel
            sectionKey="changeRequestsFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.changeRequests.search}
          >
            <FilterField label={strings.filters.status}>
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as CrStatusFilterValue)}>
                <option value="active">Active</option>
                <option value="">All statuses</option>
                {CR_STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {CHANGE_REQUEST_STATUS_LABEL[s]}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label={strings.filters.targetVersion}>
              <select className="input" value={targetStageFilter} onChange={(e) => setTargetStageFilter(e.target.value)}>
                <option value="">All versions</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </FilterField>
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
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

            {!crs && <Spinner />}
            {crs && crs.length === 0 && <p className="text-muted">{strings.changeRequests.empty}</p>}
            {crs && crs.length > 0 && viewMode === "list" && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <SortableHeader
                        label="Name" sortKey="proposed_name" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        label={strings.changeRequests.status} sortKey="status" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <th>Target</th>
                      <th>Level</th>
                      <SortableHeader
                        label="Created" sortKey="created_at" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      {showPlaces && <th>{strings.placements.label}</th>}
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
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {crs && crs.length > 0 && viewMode === "tiles" && (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
                {crs.map((cr) => (
                  <div
                    key={cr.id}
                    className="card stack entity-accent-card"
                    style={{ gap: "var(--space-3)", ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.change_request }}
                  >
                    <Link to={`/projects/${rowProjectId(cr, projectId ?? "")}/change-requests/${cr.id}`} style={{ fontWeight: 600 }}>
                      {crTitle(cr)}
                    </Link>
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
                  </div>
                ))}
              </div>
            )}
            {crs && <LoadMoreButton loaded={crs.length} total={total} onClick={() => loadChangeRequests(crs.length, true)} />}
          </div>
      </ListPageLayout>
    </div>
  );
}
