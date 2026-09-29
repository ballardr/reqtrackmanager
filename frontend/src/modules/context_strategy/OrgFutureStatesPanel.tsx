/**
 * Module: modules/context_strategy/OrgFutureStatesPanel
 *
 * The org-scoped equivalent of `ProjectFutureStatesPage.tsx` — an
 * organisation's own org-scoped Future State records (Phase 0 Q1's
 * follow-on scope discriminator), rendered as an `OrgOverviewPage.tsx`
 * `ResourceMenu` group (`module.ts`'s `orgOverviewSections`).
 *
 * **Placement, Decided by: Agent — follows `OrgStrategiesPanel.tsx`'s own
 * placement directly, per this phase's own brief ("use whatever surface
 * Phase 7.1 decided for Strategy's org-scoped list... for consistency,
 * unless you find a concrete reason Future State should differ").** No such
 * reason was found: an org-scoped Future State is the same kind of org-level
 * content a Future State Owner/Approver works with day to day that
 * `OrgStrategiesPanel.tsx`'s own docstring already reasons through for
 * Strategy, so it lands on `orgOverviewSections` (Org Dashboard) too, not
 * `orgAdminSections` (Org Management).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgFutureStateApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { FUTURE_STATE_STATUS_LABEL, FUTURE_STATE_STATUS_TONE } from "./types";
import type { FutureState, FutureStateFieldValues, FutureStateStatus } from "./types";

export function OrgFutureStatesPanel({ orgId }: { orgId: string }) {
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
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    void reloadFutureStates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, includeArchived]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (futureStates === null) return <Spinner />;

  const filtered = futureStates.filter((fs) => {
    if (statusFilter && fs.status !== statusFilter) return false;
    if (search && !fs.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<FutureState>[] = [
    { key: "title", label: "Title", render: (fs) => fs.title },
    {
      key: "status", label: "Status",
      render: (fs) => <span className={`badge badge--${FUTURE_STATE_STATUS_TONE[fs.status]}`}>{FUTURE_STATE_STATUS_LABEL[fs.status]}</span>,
    },
    { key: "target_date", label: "Target date", render: (fs) => fs.target_date ?? "—" },
    { key: "version", label: "Version", render: (fs) => `v${fs.version_number}` },
  ];

  return (
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Future State
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Organisation Future State"
          columns={columns}
          rows={filtered}
          rowKey={(fs) => fs.id}
          onRowClick={(fs) => navigate(`/orgs/${orgId}/modules/context_strategy/future-states/${fs.id}`)}
          emptyState={<p className="text-muted">No organisation-scoped Future State recorded yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.orgFutureStates.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Future State…" searchAriaLabel="Search organisation Future State"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as FutureStateStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(FUTURE_STATE_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
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
