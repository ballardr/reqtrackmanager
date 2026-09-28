/**
 * Module: modules/context_strategy/ProjectStrategiesPage
 *
 * The Context & Strategy module's project-scoped Strategy list route
 * (docs/plans/module-01-context-and-strategy-plan.md Phase 7.1), mounted at
 * `/projects/:projectId/modules/context_strategy/strategies` (`module.ts`,
 * reached via this module's new nav-rail entry — Phase 0 Q7's "five
 * separate top-level entries," this is the first of the five to actually
 * ship a route). Mirrors `modules/decisions/ProjectDecisionsPage.tsx`'s
 * `DirectoryTable` + `FilterPanel` + "New X" `Modal` shape, minus the
 * quick-view `SidePanel` tier: a row click navigates straight to
 * `StrategyDetailPage.tsx` (**Decided by: Agent** — Strategy has no
 * equivalent of Decision's `unique_code` identity shown as a clickable
 * table cell driving a *separate* quick-view panel; a direct navigation is
 * the simpler, equally style-guide-compliant choice here, and avoids
 * building a `StrategyQuickViewPanel` this phase's own brief never asked
 * for).
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectStrategyApi } from "./api";
import { StrategyFormModal } from "./StrategyFormModal";
import { STRATEGY_PRIORITY_LABEL, STRATEGY_STATUS_LABEL, STRATEGY_STATUS_TONE } from "./types";
import type { Strategy, StrategyFieldValues, StrategyPriority, StrategyStatus } from "./types";

export function ProjectStrategiesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StrategyStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<StrategyPriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadStrategies() {
    if (!projectId) return;
    try {
      setStrategies(await projectStrategyApi.list(projectId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
  }, [projectId]);

  useEffect(() => {
    void reloadStrategies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (strategies === null || project === null) return <Spinner />;

  const filtered = strategies.filter((s) => {
    if (statusFilter && s.status !== statusFilter) return false;
    if (priorityFilter && s.priority !== priorityFilter) return false;
    if (search && !s.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<Strategy>[] = [
    { key: "title", label: "Title", render: (s) => s.title },
    { key: "priority", label: "Priority", render: (s) => STRATEGY_PRIORITY_LABEL[s.priority] },
    {
      key: "status", label: "Status",
      render: (s) => <span className={`badge badge--${STRATEGY_STATUS_TONE[s.status]}`}>{STRATEGY_STATUS_LABEL[s.status]}</span>,
    },
    { key: "version", label: "Version", render: (s) => `v${s.version_number}` },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Strategy</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Strategy
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Strategies"
          columns={columns}
          rows={filtered}
          rowKey={(s) => s.id}
          onRowClick={(s) => navigate(`/projects/${projectId}/modules/context_strategy/strategies/${s.id}`)}
          emptyState={<p className="text-muted">No Strategy recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.strategies.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Strategy…" searchAriaLabel="Search Strategy"
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
          scopeLabel="project"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: StrategyFieldValues) => {
            setCreateError(null);
            try {
              await projectStrategyApi.create(projectId, values);
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
