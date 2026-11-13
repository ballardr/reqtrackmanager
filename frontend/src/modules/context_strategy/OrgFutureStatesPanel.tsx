const NONE: FutureState[] = [];

/**
 * Module: modules/context_strategy/OrgFutureStatesPanel
 *
 * The org-scoped equivalent of `ProjectFutureStatesPage.tsx` — an
 * organisation's own org-scoped Future State records (the
 * org/project scope discriminator), rendered as an `OrgOverviewPage.tsx`
 * `ResourceMenu` group (`module.ts`'s `orgOverviewSections`).
 *
 * **Placement, Decided by: Agent — follows `OrgStrategiesPanel.tsx`'s own
 * placement directly, for consistency.** No reason for Future State to differ
 * was found: an org-scoped Future State is the same kind of org-level
 * content a Future State Owner/Approver works with day to day that
 * `OrgStrategiesPanel.tsx`'s own docstring already reasons through for
 * Strategy, so it lands on `orgOverviewSections` (Org Dashboard) too, not
 * `orgAdminSections` (Org Management).
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ListActions } from "../../components/ListActions";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { FUTURE_STATE_SORT_VALUES } from "./contextStrategySort";
import { orgFutureStateApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { FUTURE_STATE_STATUS_LABEL, FUTURE_STATE_STATUS_TONE } from "./types";
import type { FutureState, FutureStateFieldValues, FutureStateStatus } from "./types";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useTableSort } from "../../hooks/useTableSort";
import { filterString } from "../../utils/listFilterParams";
import { useStrings } from "../../context/TerminologyContext";
import { labelOptions } from "../../utils/labelOptions";

export function OrgFutureStatesPanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [futureStates, setFutureStates] = useState<FutureState[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<FutureStateStatus | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadFutureStates() {
    try {
      setFutureStates(await orgFutureStateApi.list(orgId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module is not enabled for this organisation, or you do not have access to it."));
    }
  }

  useLoadOnChange(reloadFutureStates, [orgId, includeArchived]);

  const table = useTableSort(futureStates ?? NONE, FUTURE_STATE_SORT_VALUES);
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (futureStates === null) return <Spinner />;

  const filtered = table.rows.filter((fs) => {
    if (statusFilter && fs.status !== statusFilter) return false;
    if (search && !`${fs.unique_code} ${fs.title}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<FutureState>[] = [
    { key: "title", label: "Title", sortable: true, render: (fs) => fs.title },
    { key: "code", label: "Code", sortable: true, render: (fs) => <span className="text-muted"><ScopedRecordCode record={fs} /></span> },
    {
      key: "status", label: "Status", sortable: true,
      render: (fs) => <Badge tone={FUTURE_STATE_STATUS_TONE[fs.status]}>{FUTURE_STATE_STATUS_LABEL[fs.status]}</Badge>,
    },
    { key: "target_date", label: "Target date", sortable: true, render: (fs) => fs.target_date ?? "—" },
    { key: "version", label: "Version", sortable: true, render: (fs) => `v${fs.version_number}` },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New Future State
        </button>
        <ListActions
          organizationId={orgId} recordType="future_state" filters={filterString({ status: statusFilter, search, include_archived: includeArchived })} onImported={reloadFutureStates}
        />
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Organisation Future State"
          columns={columns}
          rows={filtered}
          sort={table.sort}
          onSort={table.onSort}
          rowKey={(fs) => fs.id}
          onRowClick={(fs) => navigate(`/orgs/${orgId}/modules/context_strategy/future-states/${fs.id}`)}
          emptyState={<p className="text-muted">No organisation-scoped Future State recorded yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.orgFutureStates.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Future State…" searchAriaLabel="Search organisation Future State"
        >
          <FilterSelect
            label={strings.filters.status}
            value={statusFilter}
            onChange={setStatusFilter}
            allLabel="All statuses"
            options={labelOptions(FUTURE_STATE_STATUS_LABEL)}
          />
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <FutureStateFormModal
          scopeLabel="organisation"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: FutureStateFieldValues) => {
            setCreateError(null);
            try {
              await orgFutureStateApi.create(orgId, values);
              showToast("Future State created.");
              setCreating(false);
              await reloadFutureStates();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Future State."));
            }
          }}
        />
      )}
    </div>
  );
}
