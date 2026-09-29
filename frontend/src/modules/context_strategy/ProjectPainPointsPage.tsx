/**
 * Module: modules/context_strategy/ProjectPainPointsPage
 *
 * The Context & Strategy module's project-scoped Pain Point list route
 * (docs/plans/module-01-context-and-strategy-plan.md Phase 7.3), mounted at
 * `/projects/:projectId/modules/context_strategy/pain-points`, reached via
 * this module's third top-level nav-rail entry (Phase 0 Q7). Mirrors
 * `ProjectStrategiesPage.tsx`'s exact `DirectoryTable` + `FilterPanel` +
 * "New X" `Modal` shape — Pain Point is project-scoped only (source overview
 * §6), so unlike that page there is no org-scoped sibling panel.
 *
 * Also loads this project's effective Pain Point type list
 * (`projectPainPointApi.listTypes`) once, up front — both the type filter
 * dropdown and `PainPointFormModal`'s own type picker need it, and loading
 * it here (rather than inside the modal) avoids a load flash every time the
 * "New Pain Point" modal opens.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import { PAIN_POINT_PRIORITY_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE } from "./types";
import type { EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority, PainPointStatus } from "./types";

export function ProjectPainPointsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[] | null>(null);
  const [types, setTypes] = useState<EffectivePainPointType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<PainPointStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<PainPointPriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadPainPoints() {
    if (!projectId) return;
    try {
      setPainPoints(await projectPainPointApi.list(projectId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
    void projectPainPointApi.listTypes(projectId).then(setTypes).catch(() => setTypes([]));
  }, [projectId]);

  useEffect(() => {
    void reloadPainPoints();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (painPoints === null || project === null) return <Spinner />;

  const filtered = painPoints.filter((p) => {
    if (statusFilter && p.status !== statusFilter) return false;
    if (priorityFilter && p.priority !== priorityFilter) return false;
    if (search && !p.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<PainPoint>[] = [
    { key: "title", label: "Title", render: (p) => p.title },
    { key: "type", label: "Type", render: (p) => p.pain_point_type_name },
    { key: "priority", label: "Priority", render: (p) => PAIN_POINT_PRIORITY_LABEL[p.priority] },
    {
      key: "status", label: "Status",
      render: (p) => <span className={`badge badge--${PAIN_POINT_STATUS_TONE[p.status]}`}>{PAIN_POINT_STATUS_LABEL[p.status]}</span>,
    },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Pain Point</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Pain Point
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Pain Points"
          columns={columns}
          rows={filtered}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/projects/${projectId}/modules/context_strategy/pain-points/${p.id}`)}
          emptyState={<p className="text-muted">No Pain Points recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.pain_points.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Pain Points…" searchAriaLabel="Search Pain Points"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as PainPointStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(PAIN_POINT_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Priority">
            <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as PainPointPriority | "")}>
              <option value="">All priorities</option>
              {Object.entries(PAIN_POINT_PRIORITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <PainPointFormModal
          types={types}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: PainPointFieldValues) => {
            setCreateError(null);
            try {
              await projectPainPointApi.create(projectId, values);
              showToast("Pain Point created.");
              setCreating(false);
              await reloadPainPoints();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Pain Point."));
            }
          }}
        />
      )}
    </div>
  );
}
