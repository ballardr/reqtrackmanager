/**
 * Module: modules/context_strategy/ProjectFutureStatesPage
 *
 * The Context & Strategy module's project-scoped Future State list route
 * (docs/plans/module-01-context-and-strategy-plan.md Phase 7.2), mounted at
 * `/projects/:projectId/modules/context_strategy/future-states`
 * (`module.ts`, reached via this module's second nav-rail entry — Phase 0
 * Q7's "five separate top-level entries"). Mirrors `ProjectStrategiesPage.tsx`'s
 * `DirectoryTable` + `FilterPanel` + "New X" `Modal` shape exactly, minus a
 * priority filter (Future State has no `priority` field — see `types.ts`'s
 * own docstring) and minus the target-date column here (shown in the full
 * detail page, not worth a list column of its own for a nullable field).
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectFutureStateApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { FUTURE_STATE_STATUS_LABEL, FUTURE_STATE_STATUS_TONE } from "./types";
import type { FutureState, FutureStateFieldValues, FutureStateStatus } from "./types";

export function ProjectFutureStatesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [futureStates, setFutureStates] = useState<FutureState[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<FutureStateStatus | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadFutureStates() {
    if (!projectId) return;
    try {
      setFutureStates(await projectFutureStateApi.list(projectId, { include_archived: includeArchived }));
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
    void reloadFutureStates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (futureStates === null || project === null) return <Spinner />;

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
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Future State</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Future State
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Future States"
          columns={columns}
          rows={filtered}
          rowKey={(fs) => fs.id}
          onRowClick={(fs) => navigate(`/projects/${projectId}/modules/context_strategy/future-states/${fs.id}`)}
          emptyState={<p className="text-muted">No Future State recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.futureStates.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Future State…" searchAriaLabel="Search Future State"
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
          scopeLabel="project"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: FutureStateFieldValues) => {
            setCreateError(null);
            try {
              await projectFutureStateApi.create(projectId, values);
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
