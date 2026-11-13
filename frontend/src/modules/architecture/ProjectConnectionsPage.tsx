/**
 * Module: modules/architecture/ProjectConnectionsPage
 *
 * The project's connections, the Connections tab of `SystemArchitecturePage` (`/projects/:projectId/modules/architecture?tab=connections`; `chrome` is the page's tab strip): a `DirectoryTable` (code
 * opens the detail page) with the type, both ends, protocol and status, and a `FilterPanel` (search, status, connection
 * type, element at either end, "Open only", scope, tags, archived). An end the viewer cannot read shows only its code. The list
 * opens on open connections (`useOpenOnly`) and keeps its filters in the URL. Create uses `ConnectionFormModal`, the form the
 * detail page edits with.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { cycleSort } from "../../components/sortState";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
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
import { useRecordCode } from "../../hooks/useRecordCode";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { sortRows } from "../../utils/sortRows";
import { CONNECTION_SORT_KEYS, CONNECTION_SORT_VALUES } from "./architectureSort";
import { ARCHITECTURE_PAGE_TITLE, type ArchitectureListChrome } from "./architectureTabs";
import { projectConnectionApi, projectElementApi } from "./api";
import { ConnectionFormModal } from "./ConnectionFormModal";
import { ConnectionEnd } from "./connectionEnds";
import { pathOptions, typeClosure } from "./connectionTypeTree";
import { ARCHITECTURE_HELP } from "./help";
import { useArchitectureReference } from "./useArchitectureReference";
import { useCreateConnection } from "./useCreateConnection";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureConnection, type ArchitectureElement,
  type ArchitectureRecordStatus, isOutOfUse,
} from "./types";

const STATUSES = Object.keys(ARCHITECTURE_STATUS_LABEL) as ArchitectureRecordStatus[];

export function ProjectConnectionsPage({ chrome }: { chrome?: ArchitectureListChrome }) {
  const strings = useStrings();
  const formatCode = useRecordCode();
  const { projectId = "" } = useParams<{ projectId: string }>();
  const initial = useInitialSearchParams();
  const reference = useArchitectureReference(projectId);

  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", STATUSES);
  const [typeFilter, setTypeFilter] = useUrlText("type");
  const [elementFilter, setElementFilter] = useUrlText("element");
  const [sort, setSort] = useUrlSort<string>(CONNECTION_SORT_KEYS);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [connections, setConnections] = useState<ArchitectureConnection[] | null>(null);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const createForm = useCreateConnection(projectId, () => { setCreating(false); setRefreshKey((k) => k + 1); });

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectConnectionApi(projectId).list({ include_archived: includeArchived, ...tagFilter.listFilters, project_scope: projectScope.scope })
      .then((list) => { if (active) { setConnections(list); setLoadError(null); } })
      .catch((err) => { if (active) setLoadError(toErrorMessage(err, "System Architecture is not enabled for this project, or you do not have access to it.")); });
    return () => { active = false; };
  }, [projectId, includeArchived, refreshKey, tagFilter.listFilters, projectScope.scope]);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    const api = projectElementApi(projectId);
    Promise.all([api.list({ open_only: true }), api.listShared({ open_only: true })])
      .then(([own, shared]) => { if (active) setElements([...own, ...shared]); })
      .catch(() => { if (active) setElements([]); });
    return () => { active = false; };
  }, [projectId, refreshKey]);

  // Choosing a group keeps the connections typed with any type beneath it.
  const typeIds = useMemo(
    () => (typeFilter ? typeClosure(reference.connectionTypes, [typeFilter]) : null),
    [typeFilter, reference.connectionTypes],
  );
  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (c: ArchitectureConnection, applyOpenOnly: boolean) => {
      if (applyOpenOnly && isOutOfUse(c.status)) return false;
      if (statusFilter && c.status !== statusFilter) return false;
      if (typeIds && !typeIds.has(c.connection_type_id)) return false;
      if (elementFilter && c.source_element_id !== elementFilter && c.target_element_id !== elementFilter) return false;
      return !needle || `${c.unique_code} ${c.name} ${c.protocol} ${c.description} ${c.source_element_name} ${c.target_element_name}`.toLowerCase().includes(needle);
    };
  }, [search, statusFilter, typeIds, elementFilter]);
  const filtered = useMemo(() => (connections ?? []).filter((c) => matches(c, openOnly)), [connections, matches, openOnly]);
  const sorted = useMemo(() => sortRows(filtered, sort, CONNECTION_SORT_VALUES), [filtered, sort]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (connections === null || !reference.loaded || reference.project === null) return <Spinner />;

  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    const typeName = reference.connectionTypes.find((t) => t.id === typeFilter)?.name;
    if (typeName) params.set("type", typeName);
    if (search.trim()) params.set("search", search.trim());
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  const columns: DirectoryColumn<ArchitectureConnection>[] = [
    { key: "code", label: "Code", sortable: true, render: (c) => <RecordCode code={c.unique_code} ownerProjectCode={c.from_project_code} /> },
    { key: "name", label: "Name", sortable: true, render: (c) => <>{c.name || "—"}<ProjectScopeLabel row={c} /></> },
    { key: "type", label: "Type", sortable: true, render: (c) => c.connection_type_name },
    { key: "source", label: "Source", sortable: true, render: (c) => <ConnectionEnd connection={c} end="source" /> },
    { key: "target", label: "Target", sortable: true, render: (c) => <ConnectionEnd connection={c} end="target" /> },
    { key: "protocol", label: "Protocol", sortable: true, render: (c) => c.protocol || "—" },
    {
      key: "status", label: "Status", sortable: true,
      render: (c) => (
        <FilterBadge
          tone={ARCHITECTURE_STATUS_TONE[c.status]} active={statusFilter === c.status}
          onClick={() => setStatusFilter(statusFilter === c.status ? "" : c.status)}
        >
          {ARCHITECTURE_STATUS_LABEL[c.status]}
        </FilterBadge>
      ),
    },
  ];

  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && connections.some((c) => matches(c, false));

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        records={{ projectId, recordType: "architecture_connection", filters: filterParams().toString(), onImported: () => setRefreshKey((k) => k + 1) }}
        actions={<button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>New connection</button>}
        filter={
          <FilterPanel
            sectionKey="architecture.connections" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search connections…" searchAriaLabel="Search connections"
          >
            <FilterSelect
              label={strings.filters.status} value={statusFilter} onChange={setStatusFilter} allLabel="All statuses"
              options={labelOptions(ARCHITECTURE_STATUS_LABEL)}
            />
            <FilterSelect
              label="Connection type" value={typeFilter} onChange={setTypeFilter} allLabel="All types"
              help={ARCHITECTURE_HELP.connectionTypeFilter} options={pathOptions(reference.connectionTypes)}
            />
            <FilterSelect
              label="Element" value={elementFilter} onChange={setElementFilter} allLabel="All elements"
              options={elements.map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}` }))}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Connections" columns={columns} rows={sorted} rowKey={(c) => c.id}
          sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key))}
          placements={{ projectId, artefactType: "architecture_connection", rowId: (c) => c.id }}
          rowHref={(c) => `/projects/${rowProjectId(c, projectId)}/modules/architecture/connections/${c.id}`}
          emptyState={
            <p className="text-muted">
              {emptyBecauseOfOpenOnly
                ? "No open connections. Untick Open only to include retired ones."
                : connections.length === 0 ? "No connections recorded for this project yet." : "No connections match these filters."}
            </p>
          }
        />
      </ListPageLayout>

      {creating && (
        <ConnectionFormModal
          connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} elements={elements} projectId={projectId}
          error={createForm.error}
          onCancel={() => { setCreating(false); createForm.clearError(); }} onSave={createForm.create}
        />
      )}
    </div>
  );
}
