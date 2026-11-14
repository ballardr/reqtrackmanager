/**
 * Module: modules/architecture/ProjectStatesList
 *
 * The States view of the Diagrams tab (`?tab=diagrams&view=states`): one flat list of the states (and markers) of every state
 * machine diagram in the project, with its code, name, state machine diagram, kind and element. A state is a registered record
 * type, so the list filters (search, kind, tags, project scope), sorts on a header click (the sort in the URL), exports from the
 * shared list actions and keeps its place like every record list; its code opens the state machine diagram with the state
 * selected. A state is created and edited inside its diagram's editor, so the view has no New button and no import (a state is
 * meaningful only with its transitions).
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { cycleSort } from "../../components/sortState";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { RecordCode } from "../../components/RecordCode";
import { Spinner } from "../../components/Spinner";
import { TagFilterField } from "../../components/TagFilterField";
import { toErrorMessage } from "../../context/ToastContext";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useUrlChoice, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { sortRows } from "../../utils/sortRows";
import { STATE_SORT_KEYS, STATE_SORT_VALUES } from "./architectureSort";
import { ARCHITECTURE_PAGE_TITLE, type ArchitectureListChrome } from "./architectureTabs";
import { projectStateApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import { STATE_KIND_LABEL, type ArchitectureState, type StateKind } from "./types";

const KINDS = Object.keys(STATE_KIND_LABEL) as StateKind[];

/**
 * @param chrome The page's tab strip and layout props.
 * @param viewTabs The Diagrams / States switch, shown above the table.
 */
export function ProjectStatesList({ chrome, viewTabs }: { chrome?: ArchitectureListChrome; viewTabs: ReactNode }) {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const [search, setSearch] = useUrlText("q");
  const [kindFilter, setKindFilter] = useUrlChoice("kind", KINDS);
  const [sort, setSort] = useUrlSort<string>(STATE_SORT_KEYS);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [states, setStates] = useState<ArchitectureState[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectStateApi(projectId).list({ ...tagFilter.listFilters, project_scope: projectScope.scope })
      .then((list) => { if (active) { setStates(list); setLoadError(null); } })
      .catch((err) => { if (active) setLoadError(toErrorMessage(err, "State machine diagrams are not enabled for this project, or you do not have access to them.")); });
    return () => { active = false; };
  }, [projectId, tagFilter.listFilters, projectScope.scope]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (states ?? []).filter((s) => (
      (!kindFilter || s.kind === kindFilter)
      && (!needle || `${s.unique_code} ${s.name} ${s.description} ${s.state_machine_diagram_code} ${s.state_machine_diagram_name}`.toLowerCase().includes(needle))
    ));
  }, [states, kindFilter, search]);
  const sorted = useMemo(() => sortRows(filtered, sort, STATE_SORT_VALUES), [filtered, sort]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (states === null) return <Spinner />;

  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (kindFilter) params.set("kind", kindFilter);
    if (search.trim()) params.set("search", search.trim());
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  const columns: DirectoryColumn<ArchitectureState>[] = [
    { key: "code", label: "Code", sortable: true, render: (s) => <RecordCode code={s.unique_code} ownerProjectCode={s.from_project_code} /> },
    { key: "name", label: "Name", sortable: true, render: (s) => <>{s.name}<ProjectScopeLabel row={s} /></> },
    { key: "diagram", label: "State machine diagram", sortable: true, render: (s) => `${s.state_machine_diagram_code} ${s.state_machine_diagram_name}` },
    { key: "kind", label: "Kind", sortable: true, render: (s) => STATE_KIND_LABEL[s.kind] },
    { key: "element", label: "Element", sortable: true, render: (s) => `${s.element_code ?? ""} ${s.element_name ?? ""}`.trim() || "—" },
  ];

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        records={{ projectId, recordType: "architecture_state", filters: filterParams().toString(), kindLabel: "states" }}
        filter={
          <FilterPanel
            sectionKey="architecture.states" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search states…" searchAriaLabel="Search states"
          >
            <FilterSelect
              label="Kind" value={kindFilter} onChange={setKindFilter} allLabel="All kinds" help={ARCHITECTURE_HELP.stateKind}
              options={labelOptions(STATE_KIND_LABEL)}
            />
            <ProjectScopeFilter scope={projectScope} />
            <TagFilterField projectId={projectId} filter={tagFilter} components={false} />
          </FilterPanel>
        }
      >
        {viewTabs}
        <DirectoryTable
          ariaLabel="States" columns={columns} rows={sorted} rowKey={(s) => s.id}
          sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key))}
          rowHref={(s) => `/projects/${rowProjectId(s, projectId)}/modules/architecture/state-machine-diagrams/${s.state_machine_diagram_id}?state=${s.id}`}
          emptyState={<p className="text-muted">{states.length === 0 ? "No states drawn for this project yet." : "No states match these filters."}</p>}
        />
      </ListPageLayout>
    </div>
  );
}
