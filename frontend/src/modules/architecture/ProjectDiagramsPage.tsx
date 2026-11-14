/**
 * Module: modules/architecture/ProjectDiagramsPage
 *
 * The project's diagrams, the Diagrams tab of `SystemArchitecturePage` (`/projects/:projectId/modules/architecture?tab=diagrams`; `chrome` is the page's tab strip): a
 * `DirectoryTable` (code opens the editor) listing block diagrams and state machine diagrams together, with a Type column, the
 * element, the contents (elements or states), status and a `FilterPanel` (search, Type, status, "Open only", folder, scope, tags,
 * archived). The list opens on open diagrams (`useOpenOnly`) and keeps its filters in the URL. A second view, **States**
 * (`?view=states`, `ProjectStatesList`), lists the states of every state machine diagram. Create uses `DiagramFormModal`, whose
 * first field is the Type, and opens the new diagram in its own editor.
 *
 * Design decisions:
 * - Each type keeps its own endpoints, so the list loads each and merges and sorts in the browser (the lists are not paged).
 * - A person sees a type only when they can read it: a type whose list answers 403 or 404 contributes no rows, its Type filter
 *   value, its Export group and the Type choice are left out, so someone with no state machine diagram access sees the tab
 *   as before. The tab shows an error only when no type can be read.
 * - Export and Import are one `ListActions` per type shown (the page's `records` array), each acting on its own filtered rows;
 *   the Type filter hides the other group.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import type { RecordListActions } from "../../components/ListActions";
import { cycleSort } from "../../components/sortState";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FieldHelp } from "../../components/FieldHelp";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { RecordCode } from "../../components/RecordCode";
import { Badge } from "../../components/Badge";
import { Spinner } from "../../components/Spinner";
import { TagFilterField } from "../../components/TagFilterField";
import { Tabs } from "../../components/Tabs";
import { toErrorMessage } from "../../context/ToastContext";
import { useStrings } from "../../context/TerminologyContext";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { sortRows } from "../../utils/sortRows";
import { DIAGRAM_KIND_ARTEFACT_TYPE, DIAGRAM_ROW_SORT_VALUES, DIAGRAM_SORT_KEYS, rowContents, rowElementText, type DiagramListRow } from "./architectureSort";
import { ARCHITECTURE_PAGE_TITLE, diagramEditorPath, type ArchitectureListChrome } from "./architectureTabs";
import { projectDiagramApi, projectElementApi, projectStateMachineApi } from "./api";
import { DiagramFormModal } from "./DiagramFormModal";
import { ARCHITECTURE_HELP } from "./help";
import { ProjectStatesList } from "./ProjectStatesList";
import { useCreateDiagram } from "./useCreateDiagram";
import { useFolderListControls } from "./useFolderListControls";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, DIAGRAM_KIND_LABEL, isOutOfUse, type ArchitectureDiagram, type ArchitectureElement,
  type ArchitectureRecordStatus, type DiagramKind, type StateMachineDiagram,
} from "./types";

const STATUSES = Object.keys(ARCHITECTURE_STATUS_LABEL) as ArchitectureRecordStatus[];
const KINDS = Object.keys(DIAGRAM_KIND_LABEL) as DiagramKind[];
const VIEWS = [{ key: "diagrams", label: "Diagram list" }, { key: "states", label: "State list" }] as const;

/** Where a list answered "you may not read this type" rather than failing (the type is then left out, not reported). */
const isRefused = (err: unknown) => typeof err === "object" && err !== null && "status" in err && [403, 404].includes((err as { status: number }).status);

export function ProjectDiagramsPage({ chrome }: { chrome?: ArchitectureListChrome }) {
  const [view, setView] = useUrlChoice("view", ["states"] as const);
  const viewTabs = (
    <Tabs idPrefix="diagram-views" tabs={[...VIEWS]} active={view || "diagrams"} onChange={(next) => setView(next === "states" ? "states" : "")} />
  );
  if (view === "states") return <ProjectStatesList chrome={chrome} viewTabs={viewTabs} />;
  return <DiagramsList chrome={chrome} viewTabs={viewTabs} />;
}

function DiagramsList({ chrome, viewTabs }: { chrome?: ArchitectureListChrome; viewTabs: React.ReactNode }) {
  const strings = useStrings();
  const navigate = useNavigate();
  const { projectId = "" } = useParams<{ projectId: string }>();
  const initial = useInitialSearchParams();

  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", STATUSES);
  const [kindFilter, setKindFilter] = useUrlChoice("type", KINDS);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const [sort, setSort] = useUrlSort<string>(DIAGRAM_SORT_KEYS);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [refreshKey, setRefreshKey] = useState(0);
  const folders = useFolderListControls({ projectId }, "diagram", "diagrams", () => setRefreshKey((k) => k + 1));
  const [blocks, setBlocks] = useState<ArchitectureDiagram[] | null>(null);
  const [machines, setMachines] = useState<StateMachineDiagram[] | null>(null);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const createForm = useCreateDiagram(projectId, (id, kind) => navigate(diagramEditorPath(projectId, kind, id)));

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    const filters = { include_archived: includeArchived, ...tagFilter.listFilters, project_scope: projectScope.scope };
    const mine = <T,>(call: Promise<T[]>): Promise<T[] | null> => call.catch((err) => {
      if (isRefused(err)) return null;
      throw err;
    });
    Promise.all([mine(projectDiagramApi(projectId).list(filters)), mine(projectStateMachineApi(projectId).list(filters))])
      .then(([block, machine]) => {
        if (!active) return;
        if (block === null && machine === null) throw new Error("System Architecture is not enabled for this project, or you do not have access to it.");
        setBlocks(block);
        setMachines(machine);
        setLoadError(null);
      })
      .catch((err) => { if (active) setLoadError(toErrorMessage(err, "System Architecture is not enabled for this project, or you do not have access to it.")); });
    return () => { active = false; };
  }, [projectId, includeArchived, refreshKey, tagFilter.listFilters, projectScope.scope]);

  useEffect(() => {
    if (!projectId || !creating) return;
    let active = true;
    const elementApi = projectElementApi(projectId);
    Promise.all([elementApi.list({ open_only: true }), elementApi.listShared({ open_only: true })])
      .then(([own, shared]) => { if (active) setElements([...own, ...shared]); })
      .catch(() => { if (active) setElements([]); });
    return () => { active = false; };
  }, [projectId, creating]);

  const rows = useMemo<DiagramListRow[]>(() => [
    ...(blocks ?? []).map((d): DiagramListRow => ({ kind: "block", id: d.id, source: d })),
    ...(machines ?? []).map((d): DiagramListRow => ({ kind: "state_machine", id: d.id, source: d })),
  ], [blocks, machines]);
  const offered = useMemo(() => KINDS.filter((k) => (k === "block" ? blocks !== null : machines !== null)), [blocks, machines]);

  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (r: DiagramListRow, applyOpenOnly: boolean) => {
      const d = r.source;
      if (applyOpenOnly && isOutOfUse(d.status)) return false;
      if (statusFilter && d.status !== statusFilter) return false;
      if (kindFilter && r.kind !== kindFilter) return false;
      if (folders.folderPath && !(r.kind === "block" && folders.matches(r.source.folder_path))) return false;
      const text = r.kind === "block" ? r.source.purpose : r.source.description;
      return !needle || `${d.unique_code} ${d.name} ${text} ${rowElementText(r)}`.toLowerCase().includes(needle);
    };
  }, [search, statusFilter, kindFilter, folders]);
  const filtered = useMemo(() => rows.filter((r) => matches(r, openOnly)), [rows, matches, openOnly]);
  const sorted = useMemo(() => sortRows(filtered, sort, DIAGRAM_ROW_SORT_VALUES), [filtered, sort]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (blocks === null && machines === null) return <Spinner />;

  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (search.trim()) params.set("search", search.trim());
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    folders.addParams(params);
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  const records: RecordListActions[] = offered
    .filter((k) => !kindFilter || k === kindFilter)
    .map((k) => {
      const params = filterParams();
      // A state machine diagram has no folder, so the folder filter does not apply to its export.
      if (k === "state_machine") { params.delete("folder"); params.delete("subfolders"); }
      return {
        projectId, recordType: DIAGRAM_KIND_ARTEFACT_TYPE[k], filters: params.toString(), kindLabel: `${DIAGRAM_KIND_LABEL[k].toLowerCase()}s`,
        onImported: () => setRefreshKey((n) => n + 1),
      };
    });

  const columns: DirectoryColumn<DiagramListRow>[] = [
    { key: "code", label: "Code", sortable: true, render: (r) => <RecordCode code={r.source.unique_code} ownerProjectCode={r.source.from_project_code} /> },
    { key: "name", label: "Name", sortable: true, render: (r) => <>{r.source.name}<ProjectScopeLabel row={r.source} /></> },
    ...(offered.length > 1 ? [{ key: "type", label: "Type", sortable: true, render: (r: DiagramListRow) => DIAGRAM_KIND_LABEL[r.kind] }] : []),
    { key: "folder", label: "Folder", sortable: true, render: (r) => (r.kind === "block" ? r.source.folder_path ?? "—" : "—") },
    {
      key: "scope", label: "Element", sortable: true,
      render: (r) => (r.kind === "block" && !r.source.scope_element_id
        ? <>System context <FieldHelp label="System context" help={ARCHITECTURE_HELP.systemContext} /></>
        : rowElementText(r) || "—"),
    },
    {
      key: "boxes", label: "Contents", sortable: true,
      render: (r) => (
        <>
          {rowContents(r)} {r.kind === "block" ? (rowContents(r) === 1 ? "element" : "elements") : (rowContents(r) === 1 ? "state" : "states")}
          {r.kind === "state_machine" && r.source.error_count > 0 && <> <Badge tone="danger">{r.source.error_count} {r.source.error_count === 1 ? "error" : "errors"}</Badge></>}
          {r.kind === "state_machine" && r.source.warning_count > 0 && <> <Badge tone="warning">{r.source.warning_count} {r.source.warning_count === 1 ? "warning" : "warnings"}</Badge></>}
        </>
      ),
    },
    { key: "toggles", label: "Switches", sortable: true, render: (r) => (r.kind === "block" ? r.source.toggle_count : "—") },
    {
      key: "status", label: "Status", sortable: true,
      render: (r) => (
        <FilterBadge
          tone={ARCHITECTURE_STATUS_TONE[r.source.status]} active={statusFilter === r.source.status}
          onClick={() => setStatusFilter(statusFilter === r.source.status ? "" : r.source.status)}
        >
          {ARCHITECTURE_STATUS_LABEL[r.source.status]}
        </FilterBadge>
      ),
    },
  ];

  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && rows.some((r) => matches(r, false));

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        records={records}
        actions={<button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>New diagram</button>}
        filter={
          <FilterPanel
            sectionKey="architecture.diagrams" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search diagrams…" searchAriaLabel="Search diagrams"
          >
            {offered.length > 1 && (
              <FilterSelect
                label="Type" value={kindFilter} onChange={setKindFilter} allLabel="All types" help={ARCHITECTURE_HELP.diagramType}
                options={offered.map((k) => ({ value: k, label: DIAGRAM_KIND_LABEL[k] }))}
              />
            )}
            <FilterSelect
              label={strings.filters.status} value={statusFilter} onChange={setStatusFilter} allLabel="All statuses"
              options={labelOptions(ARCHITECTURE_STATUS_LABEL)}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            {folders.panel}
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        {viewTabs}
        {folders.bar}
        <DirectoryTable
          ariaLabel="Diagrams" columns={columns} rows={sorted} rowKey={(r) => r.id}
          selection={{
            selected: folders.selected, onChange: folders.setSelected, label: (r) => `Select ${r.source.unique_code}`,
            selectable: (r) => r.kind === "block" && r.source.project_id === projectId, allLabel: "Select all diagrams",
          }}
          sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key))}
          placements={{ projectId, artefactType: (r) => DIAGRAM_KIND_ARTEFACT_TYPE[r.kind], rowId: (r) => r.id }}
          rowHref={(r) => diagramEditorPath(rowProjectId(r.source, projectId), r.kind, r.id)}
          emptyState={
            <p className="text-muted">
              {emptyBecauseOfOpenOnly
                ? "No open diagrams. Untick Open only to include retired ones."
                : rows.length === 0 ? "No diagrams drawn for this project yet." : "No diagrams match these filters."}
            </p>
          }
        />
      </ListPageLayout>

      {folders.dialog}
      {creating && (
        <DiagramFormModal
          elements={elements} projectId={projectId} error={createForm.error}
          kinds={offered.length > 0 ? offered : ["block"]}
          onCancel={() => { setCreating(false); createForm.clearError(); }} onSave={createForm.create}
        />
      )}
    </div>
  );
}
