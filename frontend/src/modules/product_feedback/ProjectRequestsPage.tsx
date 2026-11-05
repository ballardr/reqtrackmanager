/**
 * Module: modules/product_feedback/ProjectRequestsPage
 *
 * The project's enhancement request list, mounted at `/projects/:projectId/modules/product_feedback/requests`.
 * It opens on the Open statuses choice (New, Under review, Accepted); a link that names a status or the unscored slice starts
 * with that filter instead.
 *
 * Columns, filters and the unscored count are `requestList.tsx`'s, shared with the organisation inbox. Demand sits
 * beside the score, never inside it. A request with no Pain Point shows a warning (a solution with no stated
 * problem), never a block.
 *
 * A triager also gets a Grid view of the same rows and filters (`RecordGrid`) with the scoring levels as cells, so
 * a run of requests can be scored in bulk, typically after filtering to the unscored ones. The grid is offered only
 * to someone the server would let save; submitting is offered only where the project's policy allows it.
 *
 * Filters live in the URL (`status`, `open=1|0`, `scored=unscored|scored`, `missing`, `model`, `q`, `archived`) so
 * the list comes back as it was left after a visit to a record.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import { rowProjectId } from "../../api/projectScope";
import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import type { OrgUser, Project } from "../../api/types";
import { DirectoryTable } from "../../components/DirectoryTable";
import { FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { RecordCode } from "../../components/RecordCode";
import { RecordGrid } from "../../components/RecordGrid";
import { Spinner } from "../../components/Spinner";
import { TagFilterField } from "../../components/TagFilterField";
import { ViewToggle, useViewMode } from "../../components/ViewToggle";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { projectRequestApi } from "./api";
import { RequestFormModal, type RequestFormValues } from "./RequestFormModal";
import { RequestColumnChooser } from "./RequestColumnChooser";
import { requestColumns } from "./requestColumns";
import { RequestFilterFields } from "./RequestFilterFields";
import { sortRequests, useRequestListFilters } from "./requestListState";
import type { EnhancementRequest, FeedbackAccess } from "./types";

const SCHEME_KEY = "enhancement_request";

export function ProjectRequestsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "enhancement_request");
  const commitTags = useCommitTags(projectId ?? "", "enhancement_request");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [access, setAccess] = useState<FeedbackAccess | null>(null);
  const [requests, setRequests] = useState<EnhancementRequest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  // Where the grid puts its Columns / Discard / Save controls: the row of the view toggle.
  const [toolbarHost, setToolbarHost] = useState<HTMLElement | null>(null);
  const [viewMode, setViewMode] = useViewMode("product_feedback.requests", "list");

  const filters = useRequestListFilters(scheme, "project", true);

  useEffect(() => {
    if (!projectId) return;
    void api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => {
      setProject(p);
      void api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    });
    // Scoring and access are secondary to the list: a failure leaves the score columns and the extra controls out.
    void projectScoringApi.get(projectId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
    void projectRequestApi.getAccess(projectId).then(setAccess).catch(() => setAccess(null));
  }, [projectId]);

  async function reload() {
    if (!projectId) return;
    try {
      setRequests(await projectRequestApi.list(projectId, {
        include_archived: filters.includeArchived, scoring_model: filters.requestedModels,
        tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope,
      }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Product Feedback module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useLoadOnChange(reload, [projectId, filters.includeArchived, filters.requestedModels.join(","), tagFilter.query, projectScope.scope]);

  async function create(values: RequestFormValues, quickLinks: Parameters<typeof commitQuickLinks>[1], tags: string[]) {
    if (!projectId) return;
    setCreateError(null);
    try {
      const created = await projectRequestApi.create(projectId, values);
      showToast("Request submitted.");
      setCreating(false);
      await commitQuickLinks(created.id, quickLinks);
      await commitTags(created.id, tags);
      await reload();
    } catch (err) {
      setCreateError(toErrorMessage(err, "Could not submit the request."));
    }
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (requests === null || project === null) return <Spinner />;

  const filtered = requests.filter((r) => filters.matches(r));
  const rows = sortRequests(filtered, filters);
  const emptyBecauseOfOpenOnly = filters.openOnly && filtered.length === 0 && requests.some((r) => filters.matches(r, "open"));
  const params = addSharedListFilters(filters.filterParams(), tagFilter, projectScope);
  const columns = requestColumns({
    scheme, models: filters.models, shown: filters.columns.visible, showLinkWarnings: true,
    titleExtra: (r) => <ProjectScopeLabel row={r} />,
    codeCell: (r) => <RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} />,
  });

  return (
    <div className="container stack">
      <ListPageLayout
        title="Enhancement requests"
        records={{ projectId, recordType: "enhancement_request", filters: params.toString(), onImported: reload }}
        actions={access?.can_submit !== false && (
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New request
          </button>
        )}
        filter={
          <FilterPanel
            sectionKey="product_feedback.requests.list" total={filtered.length}
            search={filters.search} onSearchChange={filters.setSearch}
            searchPlaceholder="Search requests…" searchAriaLabel="Search requests"
          >
            <RequestFilterFields filters={filters} scheme={scheme} requests={requests} />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
          </FilterPanel>
        }
      >
        <div className="row" style={{ justifyContent: "flex-end", alignItems: "center" }}>
          <div ref={setToolbarHost} className="row" style={{ alignItems: "center" }} />
          {!(access?.can_triage && viewMode === "grid") && <RequestColumnChooser filters={filters} scheme={scheme} />}
          {access?.can_triage && <ViewToggle mode={viewMode} onChange={setViewMode} showTilesOption={false} showGridOption />}
        </div>
        {access?.can_triage && viewMode === "grid" ? (
          <RecordGrid
            projectId={projectId} toolbarHost={toolbarHost} recordType="enhancement_request" filters={params.toString()}
            contextKeys={["title"]}
            recordHref={(row) => `/projects/${row.project_id ?? projectId}/modules/product_feedback/requests/${row.id}`}
            onSaved={() => void reload()}
          />
        ) : (
          <DirectoryTable
            ariaLabel="Enhancement requests"
            columns={columns}
            rows={rows}
            sort={filters.sort}
            onSort={(key) => filters.setSort((current) => cycleSort(current, key))}
            rowKey={(r) => r.id}
            rowHref={(r) => `/projects/${rowProjectId(r, projectId)}/modules/product_feedback/requests/${r.id}`}
            emptyState={
              <p className="text-muted">
                {emptyBecauseOfOpenOnly
                  ? "No open requests. Set Status to All statuses to include delivered, declined and duplicate ones."
                  : requests.length > 0 ? "No requests match these filters." : "No enhancement requests in this project yet."}
              </p>
            }
          />
        )}
      </ListPageLayout>

      {creating && (
        <RequestFormModal
          scopeLabel="project" scheme={scheme} orgUsers={orgUsers} organizationId={project.organization_id}
          projectId={projectId} error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={create}
        />
      )}
    </div>
  );
}
