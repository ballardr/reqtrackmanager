/**
 * Module: modules/architecture/ProjectElementsPage
 *
 * The project's elements, the Elements tab of `SystemArchitecturePage` (`/projects/:projectId/modules/architecture?tab=elements`;
 * `chrome` is the page's tab strip). Two views over the same filtered set, switched with `Tabs`:
 * - *List*: a `DirectoryTable` (code opens the detail page) with type, owner, parent, connection count and status, plus a
 *   `FilterPanel` (search, status, type, "Open only", scope, tags, archived).
 * - *Tree*: the elements arranged by parent, each a link to its page. An element whose parent is filtered out is shown at
 *   the top level, so every match is visible.
 *
 * Elements other owners share with this project appear in the same lists, marked "Shared" and read-only. The list opens on
 * open elements only (`useOpenOnly`); the view and filters live in the URL, so the page comes back as it was left. Status
 * and type render through their label maps. Create uses `ElementFormModal`, the same fields as the edit form.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { Badge } from "../../components/Badge";
import { cycleSort } from "../../components/sortState";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { TagFilterField } from "../../components/TagFilterField";
import { TreeView } from "../../components/TreeView";
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
import { projectElementApi, projectSymbolUrl } from "./api";
import { ELEMENT_SORT_KEYS, elementSortValues } from "./architectureSort";
import { ARCHITECTURE_PAGE_TITLE, type ArchitectureListChrome } from "./architectureTabs";
import { buildElementTree, elementCodeRecord } from "./architectureFields";
import { ElementFormModal } from "./ElementFormModal";
import { useCreateElement } from "./useCreateElement";
import { useArchitectureReference } from "./useArchitectureReference";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureElement, type ArchitectureRecordStatus, isOutOfUse,
} from "./types";

type View = "list" | "tree";
const VIEW_PARAMS: readonly View[] = ["tree"];
const STATUSES = Object.keys(ARCHITECTURE_STATUS_LABEL) as ArchitectureRecordStatus[];

export function ProjectElementsPage({ chrome }: { chrome?: ArchitectureListChrome }) {
  const strings = useStrings();
  const { projectId = "" } = useParams<{ projectId: string }>();
  const initial = useInitialSearchParams();
  const reference = useArchitectureReference(projectId);

  const [viewParam, setViewParam] = useUrlChoice("view", VIEW_PARAMS);
  const view: View = viewParam || "list";
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", STATUSES);
  const [typeFilter, setTypeFilter] = useUrlText("type");
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [sort, setSort] = useUrlSort<string>(ELEMENT_SORT_KEYS);

  const [elements, setElements] = useState<ArchitectureElement[] | null>(null);
  const [shared, setShared] = useState<ArchitectureElement[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const createForm = useCreateElement(projectId, () => { setCreating(false); setRefreshKey((k) => k + 1); });

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    const api = projectElementApi(projectId);
    api.list({ include_archived: includeArchived, ...tagFilter.listFilters, project_scope: projectScope.scope })
      .then((list) => { if (active) { setElements(list); setLoadError(null); } })
      .catch((err) => { if (active) setLoadError(toErrorMessage(err, "System Architecture is not enabled for this project, or you do not have access to it.")); });
    api.listShared().then((list) => { if (active) setShared(list); }).catch(() => { if (active) setShared([]); });
    return () => { active = false; };
  }, [projectId, includeArchived, refreshKey, tagFilter.listFilters, projectScope.scope]);

  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (e: ArchitectureElement, applyOpenOnly: boolean) => {
      if (applyOpenOnly && isOutOfUse(e.status)) return false;
      if (statusFilter && e.status !== statusFilter) return false;
      if (typeFilter && e.element_type_id !== typeFilter) return false;
      return !needle || `${e.unique_code} ${e.name} ${e.description}`.toLowerCase().includes(needle);
    };
  }, [search, statusFilter, typeFilter]);

  const rows = useMemo(() => [...(elements ?? []), ...shared], [elements, shared]);
  const filtered = useMemo(() => rows.filter((e) => matches(e, openOnly)), [rows, matches, openOnly]);
  const parentName = (e: ArchitectureElement) => rows.find((p) => p.id === e.parent_id)?.name ?? (e.parent_id ? "—" : "");
  const sorted = sortRows(filtered, sort, elementSortValues(parentName));
  const tree = useMemo(() => buildElementTree(filtered), [filtered]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (elements === null || !reference.loaded || reference.project === null) return <Spinner />;
  const project = reference.project;

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    const typeName = reference.elementTypes.find((t) => t.id === typeFilter)?.name;
    if (typeName) params.set("type", typeName);
    if (search.trim()) params.set("search", search.trim());
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  const rowHref = (e: ArchitectureElement) => `/projects/${rowProjectId(e, projectId)}/modules/architecture/elements/${e.id}`;

  const columns: DirectoryColumn<ArchitectureElement>[] = [
    { key: "code", label: "Code", sortable: true, render: (e) => <ScopedRecordCode record={elementCodeRecord(e)} /> },
    {
      key: "name", label: "Name", sortable: true,
      render: (e) => <>{e.name}{e.shared && <> <Badge tone="info">Shared</Badge></>}<ProjectScopeLabel row={e} /></>,
    },
    { key: "type", label: "Type", sortable: true, render: (e) => e.element_type_name },
    { key: "parent", label: "Parent", sortable: true, render: (e) => parentName(e) || "—" },
    { key: "owner", label: "Owner", sortable: true, render: (e) => <PrincipalBadge principal={e.owner} placeholder="—" /> },
    { key: "connections", label: "Connections", sortable: true, render: (e) => e.connection_count },
    {
      key: "status", label: "Status", sortable: true,
      render: (e) => (
        <FilterBadge
          tone={ARCHITECTURE_STATUS_TONE[e.status]} active={statusFilter === e.status}
          onClick={() => setStatusFilter(statusFilter === e.status ? "" : e.status)}
        >
          {ARCHITECTURE_STATUS_LABEL[e.status]}
        </FilterBadge>
      ),
    },
  ];

  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && rows.some((e) => matches(e, false));
  const emptyState = (
    <p className="text-muted">
      {emptyBecauseOfOpenOnly
        ? "No open elements. Untick Open only to include retired ones."
        : rows.length === 0 ? "No elements recorded for this project yet." : "No elements match these filters."}
    </p>
  );

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        records={{ projectId, recordType: "architecture_element", filters: filterParams().toString(), onImported: () => setRefreshKey((k) => k + 1) }}
        actions={
          <>
            <Link className="btn" to={`/projects/${projectId}/modules/architecture/sharing`}>Sharing</Link>
            <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>New element</button>
          </>
        }
        filter={
          <FilterPanel
            sectionKey="architecture.elements" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search elements…" searchAriaLabel="Search elements"
          >
            <FilterSelect
              label={strings.filters.status} value={statusFilter} onChange={setStatusFilter} allLabel="All statuses"
              options={labelOptions(ARCHITECTURE_STATUS_LABEL)}
            />
            <FilterSelect
              label="Element type" value={typeFilter} onChange={setTypeFilter} allLabel="All types"
              options={reference.elementTypes.map((t) => ({ value: t.id, label: t.name }))}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <Tabs
          idPrefix="elements-view"
          tabs={[{ key: "list", label: "List" }, { key: "tree", label: "Tree" }]}
          active={view}
          onChange={(next) => setViewParam(next === "tree" ? "tree" : "")}
        />
        <div className="stack" {...tabPanelProps("elements-view", view)}>
          {view === "list" ? (
            <DirectoryTable
              ariaLabel="Elements" columns={columns} rows={sorted} rowKey={(e) => e.id}
              sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key))}
              placements={{ projectId, artefactType: "architecture_element", rowId: (e) => e.id }}
              rowHref={rowHref} emptyState={emptyState}
            />
          ) : (
            <TreeView
              nodes={tree}
              nodeLabel={(node) => node.element.name}
              emptyText={emptyBecauseOfOpenOnly ? "No open elements. Untick Open only to include retired ones." : "No elements match these filters."}
              renderNode={(node) => (
                <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
                  <Link to={rowHref(node.element)}>
                    <ScopedRecordCode record={elementCodeRecord(node.element)} /> {node.element.name}
                  </Link>
                  <span className="text-muted">{node.element.element_type_name}</span>
                  {node.element.shared && <Badge tone="info">Shared</Badge>}
                  <Badge tone={ARCHITECTURE_STATUS_TONE[node.element.status]}>{ARCHITECTURE_STATUS_LABEL[node.element.status]}</Badge>
                </span>
              )}
            />
          )}
        </div>
      </ListPageLayout>

      {creating && (
        <ElementFormModal
          elementTypes={reference.elementTypes} connectionTypes={reference.connectionTypes} candidates={elements}
          symbols={reference.symbols} symbolUrl={(id) => projectSymbolUrl(projectId, id)} orgUsers={reference.orgUsers}
          organizationId={project.organization_id} projectId={projectId} error={createForm.error}
          onCancel={() => { setCreating(false); createForm.clearError(); }} onSave={createForm.create}
        />
      )}
    </div>
  );
}
