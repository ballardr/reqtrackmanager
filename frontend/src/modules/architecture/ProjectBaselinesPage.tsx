/**
 * Module: modules/architecture/ProjectBaselinesPage
 *
 * The Baselines tab of the System Architecture page: the project's baselines that hold architecture records (taken manually or
 * written by a stage entering a locked phase), with their kind, stage, who took them, when and how many records. A row opens the
 * baseline (`BaselineDetailPage`); "Take baseline" records the architecture as it stands. A baseline is not a record type, so
 * the list has no export or import; it filters by search and kind, sorts on a header click (the sort in the address) and keeps its
 * place like every list. Taking one is refused by the server for a person without the Architect role, shown in the dialog.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useUrlChoice, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { labelOptions } from "../../utils/labelOptions";
import { sortRows } from "../../utils/sortRows";
import { projectBaselineApi } from "./api";
import { BASELINE_SORT_KEYS, BASELINE_SORT_VALUES, baselineRecordCount } from "./architectureSort";
import { ARCHITECTURE_PAGE_TITLE, type ArchitectureListChrome } from "./architectureTabs";
import { ARCHITECTURE_HELP } from "./help";
import { TakeBaselineModal } from "./TakeBaselineModal";
import { BASELINE_KIND_LABEL, BASELINE_TYPE_LABEL, type BaselineKind, type ProjectBaseline } from "./types";

const KINDS = Object.keys(BASELINE_KIND_LABEL) as BaselineKind[];

/** Whether a baseline holds any record of this module. */
function holdsArchitecture(baseline: ProjectBaseline): boolean {
  return baselineRecordCount(baseline) > 0;
}

/** @param chrome The page's tab strip and layout props. */
export function ProjectBaselinesPage({ chrome }: { chrome?: ArchitectureListChrome }) {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const [search, setSearch] = useUrlText("q");
  const [kindFilter, setKindFilter] = useUrlChoice("kind", KINDS);
  const [sort, setSort] = useUrlSort<string>(BASELINE_SORT_KEYS);
  const [baselines, setBaselines] = useState<ProjectBaseline[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [taking, setTaking] = useState(false);
  const [takeError, setTakeError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    let live = true;
    projectBaselineApi(projectId).list()
      .then((list) => { if (live) { setBaselines(list.filter(holdsArchitecture)); setLoadError(null); } })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "Baselines could not be loaded, or you do not have access to them.")); });
    return () => { live = false; };
  }, [projectId, refreshKey]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (baselines ?? []).filter((b) => (
      (!kindFilter || b.kind === kindFilter)
      && (!needle || `${b.label} ${b.stage_name ?? ""} ${b.created_by_name ?? ""}`.toLowerCase().includes(needle))
    ));
  }, [baselines, kindFilter, search]);
  const sorted = useMemo(() => sortRows(filtered, sort, BASELINE_SORT_VALUES), [filtered, sort]);

  const take = useCallback(async (label: string) => {
    setTakeError(null);
    try {
      await projectBaselineApi(projectId).take(label, Object.keys(BASELINE_TYPE_LABEL));
      showToast("Baseline taken.");
      setTaking(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setTakeError(toErrorMessage(err, "Could not take the baseline."));
    }
  }, [projectId, showToast]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (baselines === null) return <Spinner />;

  const columns: DirectoryColumn<ProjectBaseline>[] = [
    { key: "name", label: "Name", sortable: true, render: (b) => b.label },
    { key: "kind", label: "Kind", sortable: true, render: (b) => BASELINE_KIND_LABEL[b.kind] },
    { key: "stage", label: "Stage", sortable: true, render: (b) => b.stage_name ?? "—" },
    { key: "taken", label: "Taken", sortable: true, render: (b) => new Date(b.created_at).toLocaleString() },
    { key: "by", label: "Taken by", sortable: true, render: (b) => b.created_by_name ?? "—" },
    { key: "records", label: "Records", sortable: true, render: (b) => baselineRecordCount(b) },
  ];

  return (
    <div className="container stack">
      <ListPageLayout
        title={ARCHITECTURE_PAGE_TITLE} {...chrome}
        actions={<button type="button" className="btn btn-primary" onClick={() => { setTakeError(null); setTaking(true); }}>Take baseline</button>}
        filter={
          <FilterPanel
            sectionKey="architecture.baselines" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search baselines…" searchAriaLabel="Search baselines"
          >
            <FilterSelect
              label="Kind" value={kindFilter} onChange={setKindFilter} allLabel="All kinds" help={ARCHITECTURE_HELP.baselineKind}
              options={labelOptions(BASELINE_KIND_LABEL)}
            />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Baselines" columns={columns} rows={sorted} rowKey={(b) => b.id}
          sort={sort} onSort={(key) => setSort((current) => cycleSort(current, key))}
          rowHref={(b) => `/projects/${projectId}/modules/architecture/baselines/${b.id}`}
          emptyState={<p className="text-muted">{baselines.length === 0 ? "No baselines hold architecture records yet." : "No baselines match these filters."}</p>}
        />
      </ListPageLayout>
      {taking && <TakeBaselineModal error={takeError} onCancel={() => setTaking(false)} onSave={take} />}
    </div>
  );
}
