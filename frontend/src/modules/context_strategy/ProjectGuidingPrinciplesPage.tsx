/**
 * Module: modules/context_strategy/ProjectGuidingPrinciplesPage
 *
 * The Context & Strategy module's project-scoped Guiding Principle list
 * route,
 * mounted at `/projects/:projectId/modules/context_strategy/guiding-principles`
 * (`module.ts`, reached via the "Guiding Principle" nav-rail
 * entry — one of the five top-level entries).
 * Mirrors `ProjectStrategiesPage.tsx`'s exact `DirectoryTable` + `FilterPanel`
 * + "New X" `Modal` shape, minus the quick-view `SidePanel` tier, for the
 * same reasons that page's own docstring gives.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE } from "./types";
import type { GuidingPrinciple, GuidingPrincipleFieldValues, GuidingPrinciplePriority, GuidingPrincipleStatus } from "./types";
import { Badge } from "../../components/Badge";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { addSharedListFilters } from "../../utils/listFilterParams";

export function ProjectGuidingPrinciplesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "guiding_principle");
  const commitTags = useCommitTags(projectId ?? "", "guiding_principle");
  const [project, setProject] = useState<Project | null>(null);
  const [guidingPrinciples, setGuidingPrinciples] = useState<GuidingPrinciple[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Filters live in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(GUIDING_PRINCIPLE_STATUS_LABEL) as GuidingPrincipleStatus[]);
  const [priorityFilter, setPriorityFilter] = useUrlChoice("priority", Object.keys(GUIDING_PRINCIPLE_PRIORITY_LABEL) as GuidingPrinciplePriority[]);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadGuidingPrinciples() {
    if (!projectId) return;
    try {
      setGuidingPrinciples(await projectGuidingPrincipleApi.list(projectId, { include_archived: includeArchived, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
  }, [projectId]);

  useLoadOnChange(reloadGuidingPrinciples, [projectId, includeArchived, tagFilter.query, projectScope.scope]);

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (priorityFilter) params.set("priority", priorityFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciples === null || project === null) return <Spinner />;

  const filtered = guidingPrinciples.filter((g) => {
    if (statusFilter && g.status !== statusFilter) return false;
    if (priorityFilter && g.priority !== priorityFilter) return false;
    if (search && !`${g.unique_code} ${g.name}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<GuidingPrinciple>[] = [
    { key: "name", label: "Name", render: (g) => <>{g.name}<ProjectScopeLabel row={g} /></> },
    { key: "code", label: "Code", render: (g) => <span className="text-muted"><ScopedRecordCode record={g} /></span> },
    { key: "priority", label: "Priority", render: (g) => GUIDING_PRINCIPLE_PRIORITY_LABEL[g.priority] },
    {
      key: "status", label: "Status",
      render: (g) => <Badge tone={GUIDING_PRINCIPLE_STATUS_TONE[g.status]}>{GUIDING_PRINCIPLE_STATUS_LABEL[g.status]}</Badge>,
    },
    { key: "version", label: "Version", render: (g) => `v${g.version_number}` },
  ];

  return (
    <div className="container stack">
      <ListPageLayout
        title="Guiding Principle"
        records={{ projectId, recordType: "guiding_principle", filters: filterParams().toString(), onImported: reloadGuidingPrinciples }}
        actions={
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New Guiding Principle
          </button>
        }
        filter={
          <FilterPanel
            sectionKey="context_strategy.guidingPrinciples.list" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search Guiding Principles…" searchAriaLabel="Search Guiding Principles"
          >
            <FilterField label="Status">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as GuidingPrincipleStatus | "")}>
                <option value="">All statuses</option>
                {Object.entries(GUIDING_PRINCIPLE_STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Priority">
              <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as GuidingPrinciplePriority | "")}>
                <option value="">All priorities</option>
                {Object.entries(GUIDING_PRINCIPLE_PRIORITY_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Guiding Principles"
          columns={columns}
          rows={filtered}
          rowKey={(g) => g.id}
          onRowClick={(g) => navigate(`/projects/${rowProjectId(g, projectId)}/modules/context_strategy/guiding-principles/${g.id}`)}
          emptyState={<p className="text-muted">No Guiding Principle recorded for this project yet.</p>}
        />
      </ListPageLayout>

      {creating && (
        <GuidingPrincipleFormModal
          scopeLabel="project"
          projectId={projectId}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: GuidingPrincipleFieldValues, quickLinks, tags) => {
            setCreateError(null);
            try {
              const created = await projectGuidingPrincipleApi.create(projectId, values);
              showToast("Guiding Principle created.");
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
              await reloadGuidingPrinciples();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Guiding Principle."));
            }
          }}
        />
      )}
    </div>
  );
}
