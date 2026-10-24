/**
 * Module: modules/context_strategy/OrgStrategiesPanel
 *
 * The org-scoped equivalent of `ProjectStrategiesPage.tsx` — an
 * organisation's own org-scoped Strategy records (the org/project
 * scope discriminator), rendered as an `OrgOverviewPage.tsx` `ResourceMenu`
 * group (`module.ts`'s `orgOverviewSections`).
 *
 * **Placement decision, Decided by: Agent:** checked this module's own
 * existing precedent before picking a surface — `modules/compliance/
 * module.ts` puts its org-wide *dashboards* (Compliance by standard,
 * Outstanding) on `orgOverviewSections` (Org Dashboard) and its
 * *management* surfaces (standards/action types CRUD) on the standalone
 * `/standards` nav tab; `modules/decisions/module.ts` puts its org-scoped
 * *template library* on `orgAdminSections` (Org Management), reasoning
 * explicitly that "an org admin manages the template library on Org
 * Management, not the Org Dashboard." An org-scoped **Strategy** is neither
 * a dashboard nor a pure admin-configuration table — it's org-level
 * *content* a Strategy Owner/Approver works with day to day, the closest
 * analogue being Decision Management's own Decision list (which has no org
 * scope to compare against directly). Landed on `orgOverviewSections`
 * (Org Dashboard) rather than `orgAdminSections` (Org Management):
 * `OrgOverviewPage.tsx` is this codebase's "what's the current state of
 * things in this organisation" surface (stats header, Compliance's own
 * dashboard panels), which fits an org-level Strategy list better than
 * Org Management's administration-focused framing (roles, modules, org
 * settings) — a Strategy Owner reviewing/approving Strategy is checking on
 * organisational state, not configuring the org. Revisit if a later
 * artefact type (e.g. Guiding Principle, also org/project
 * scoped) suggests a different, more consistent placement across all of
 * Context & Strategy's org-scoped surfaces.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ListActions } from "../../components/ListActions";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStrategyApi } from "./api";
import { StrategyFormModal } from "./StrategyFormModal";
import { STRATEGY_PRIORITY_LABEL, STRATEGY_STATUS_LABEL, STRATEGY_STATUS_TONE } from "./types";
import type { Strategy, StrategyFieldValues, StrategyPriority, StrategyStatus } from "./types";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { filterString } from "../../utils/listFilterParams";

export function OrgStrategiesPanel({ orgId }: { orgId: string }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StrategyStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<StrategyPriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadStrategies() {
    try {
      setStrategies(await orgStrategyApi.list(orgId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this organisation, or you don't have access to it."));
    }
  }

  useLoadOnChange(reloadStrategies, [orgId, includeArchived]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (strategies === null) return <Spinner />;

  const filtered = strategies.filter((s) => {
    if (statusFilter && s.status !== statusFilter) return false;
    if (priorityFilter && s.priority !== priorityFilter) return false;
    if (search && !`${s.unique_code} ${s.title}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<Strategy>[] = [
    { key: "title", label: "Title", render: (s) => s.title },
    { key: "code", label: "Code", render: (s) => <span className="text-muted"><ScopedRecordCode record={s} /></span> },
    { key: "priority", label: "Priority", render: (s) => STRATEGY_PRIORITY_LABEL[s.priority] },
    {
      key: "status", label: "Status",
      render: (s) => <Badge tone={STRATEGY_STATUS_TONE[s.status]}>{STRATEGY_STATUS_LABEL[s.status]}</Badge>,
    },
    { key: "version", label: "Version", render: (s) => `v${s.version_number}` },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-3)", alignSelf: "flex-start" }}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New Strategy
        </button>
        <ListActions
          organizationId={orgId} recordType="strategy" filters={filterString({ status: statusFilter, priority: priorityFilter, search, include_archived: includeArchived })} onImported={reloadStrategies}
        />
      </div>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Organisation Strategy"
          columns={columns}
          rows={filtered}
          rowKey={(s) => s.id}
          onRowClick={(s) => navigate(`/orgs/${orgId}/modules/context_strategy/strategies/${s.id}`)}
          emptyState={<p className="text-muted">No organisation-scoped Strategy recorded yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.orgStrategies.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Strategy…" searchAriaLabel="Search organisation Strategy"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StrategyStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(STRATEGY_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Priority">
            <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as StrategyPriority | "")}>
              <option value="">All priorities</option>
              {Object.entries(STRATEGY_PRIORITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <StrategyFormModal
          scopeLabel="organisation"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: StrategyFieldValues) => {
            setCreateError(null);
            try {
              await orgStrategyApi.create(orgId, values);
              showToast("Strategy created.");
              setCreating(false);
              await reloadStrategies();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Strategy."));
            }
          }}
        />
      )}
    </div>
  );
}
