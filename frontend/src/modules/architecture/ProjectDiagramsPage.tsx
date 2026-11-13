/**
 * Module: modules/architecture/ProjectDiagramsPage
 *
 * The project's diagrams, the Diagrams tab of `SystemArchitecturePage` (`/projects/:projectId/modules/architecture?tab=diagrams`; `chrome` is the page's tab strip): a `DirectoryTable` (code opens the
 * editor) with the scope element, status and counts, and a `FilterPanel` (search, status, "Open only", scope, tags,
 * archived). The list opens on open diagrams (`useOpenOnly`) and keeps its filters in the URL. Create uses
 * `DiagramFormModal`, the form the editor edits with, and opens the new diagram in the editor.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FieldHelp } from "../../components/FieldHelp";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { RecordCode } from "../../components/RecordCode";
import { Spinner } from "../../components/Spinner";
import { TagFilterField } from "../../components/TagFilterField";
import { toErrorMessage } from "../../context/ToastContext";
import { useStrings } from "../../context/TerminologyContext";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { ARCHITECTURE_PAGE_TITLE, type ArchitectureListChrome } from "./architectureTabs";
import { projectDiagramApi, projectElementApi } from "./api";
import { DiagramFormModal } from "./DiagramFormModal";
import { ARCHITECTURE_HELP } from "./help";
import { useCreateDiagram } from "./useCreateDiagram";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureDiagram, type ArchitectureElement,
  type ArchitectureRecordStatus,
} from "./types";

const STATUSES = Object.keys(ARCHITECTURE_STATUS_LABEL) as ArchitectureRecordStatus[];

export function ProjectDiagramsPage({ chrome }: { chrome?: ArchitectureListChrome }) {
  const strings = useStrings();
  const navigate = useNavigate();
  const { projectId = "" } = useParams<{ projectId: string }>();
  const initial = useInitialSearchParams();

  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", STATUSES);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [diagrams, setDiagrams] = useState<ArchitectureDiagram[] | null>(null);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const createForm = useCreateDiagram(projectId, (id) => navigate(`/projects/${projectId}/modules/architecture/diagrams/${id}`));

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectDiagramApi(projectId).list({ include_archived: includeArchived, ...tagFilter.listFilters, project_scope: projectScope.scope })
      .then((list) => { if (active) { setDiagrams(list); setLoadError(null); } })
      .catch((err) => { if (active) setLoadError(toErrorMessage(err, "System Architecture is not enabled for this project, or you do not have access to it.")); });
    return () => { active = false; };
  }, [projectId, includeArchived, refreshKey, tagFilter.listFilters, projectScope.scope]);

  useEffect(() => {
    if (!projectId || !creating) return;
    let active = true;
    projectElementApi(projectId).list({ open_only: true })
      .then((list) => { if (active) setElements(list); })
      .catch(() => { if (active) setElements([]); });
    return () => { active = false; };
  }, [projectId, creating]);

  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (d: ArchitectureDiagram, applyOpenOnly: boolean) => {
      if (applyOpenOnly && d.status === "retired") return false;
      if (statusFilter && d.status !== statusFilter) return false;
      return !needle || `${d.unique_code} ${d.name} ${d.purpose} ${d.scope_element_name ?? ""}`.toLowerCase().includes(needle);
    };
  }, [search, statusFilter]);
  const filtered = useMemo(() => (diagrams ?? []).filter((d) => matches(d, openOnly)), [diagrams, matches, openOnly]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (diagrams === null) return <Spinner />;

  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (search.trim()) params.set("search", search.trim());
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  const columns: DirectoryColumn<ArchitectureDiagram>[] = [
    { key: "code", label: "Code", render: (d) => <RecordCode code={d.unique_code} ownerProjectCode={d.from_project_code} /> },
    { key: "name", label: "Name", render: (d) => <>{d.name}<ProjectScopeLabel row={d} /></> },
    { key: "scope", label: "Scope", render: (d) => (d.scope_element_id ? `${d.scope_element_code ?? ""} ${d.scope_element_name ?? ""}`.trim() || "—" : <>System context <FieldHelp label="System context" help={ARCHITECTURE_HELP.systemContext} /></>) },
    { key: "boxes", label: "Elements", render: (d) => d.placement_count },
    { key: "toggles", label: "Switches", render: (d) => d.toggle_count },
    {
      key: "status", label: "Status",
      render: (d) => (
        <FilterBadge
          tone={ARCHITECTURE_STATUS_TONE[d.status]} active={statusFilter === d.status}
          onClick={() => setStatusFilter(statusFilter === d.status ? "" : d.status)}
        >
          {ARCHITECTURE_STATUS_LABEL[d.status]}
        </FilterBadge>
      ),
    },
  ];

  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && diagrams.some((d) => matches(d, false));

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        records={{ projectId, recordType: "architecture_diagram", filters: filterParams().toString(), onImported: () => setRefreshKey((k) => k + 1) }}
        actions={<button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>New diagram</button>}
        filter={
          <FilterPanel
            sectionKey="architecture.diagrams" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search diagrams…" searchAriaLabel="Search diagrams"
          >
            <FilterSelect
              label={strings.filters.status} value={statusFilter} onChange={setStatusFilter} allLabel="All statuses"
              options={labelOptions(ARCHITECTURE_STATUS_LABEL)}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Diagrams" columns={columns} rows={filtered} rowKey={(d) => d.id}
          placements={{ projectId, artefactType: "architecture_diagram", rowId: (d) => d.id }}
          rowHref={(d) => `/projects/${rowProjectId(d, projectId)}/modules/architecture/diagrams/${d.id}`}
          emptyState={
            <p className="text-muted">
              {emptyBecauseOfOpenOnly
                ? "No open diagrams. Untick Open only to include retired ones."
                : diagrams.length === 0 ? "No diagrams drawn for this project yet." : "No diagrams match these filters."}
            </p>
          }
        />
      </ListPageLayout>

      {creating && (
        <DiagramFormModal
          elements={elements} projectId={projectId} error={createForm.error}
          onCancel={() => { setCreating(false); createForm.clearError(); }} onSave={createForm.create}
        />
      )}
    </div>
  );
}
