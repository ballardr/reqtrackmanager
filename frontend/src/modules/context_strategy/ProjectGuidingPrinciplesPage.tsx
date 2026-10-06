/**
 * Module: modules/context_strategy/ProjectGuidingPrinciplesPage
 *
 * The Context & Strategy module's project-scoped Guiding Principle list
 * route (docs/plans/module-01-context-and-strategy-plan.md Phase 7.4),
 * mounted at `/projects/:projectId/modules/context_strategy/guiding-principles`
 * (`module.ts`, reached via this phase's new "Guiding Principle" nav-rail
 * entry — the fourth of Phase 0 Q7's five planned top-level entries).
 * Mirrors `ProjectStrategiesPage.tsx`'s exact `DirectoryTable` + `FilterPanel`
 * + "New X" `Modal` shape, minus the quick-view `SidePanel` tier, for the
 * same reasons that page's own docstring gives.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { oneOf, useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { projectGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE } from "./types";
import type { GuidingPrinciple, GuidingPrincipleFieldValues, GuidingPrinciplePriority, GuidingPrincipleStatus } from "./types";

export function ProjectGuidingPrinciplesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [guidingPrinciples, setGuidingPrinciples] = useState<GuidingPrinciple[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<GuidingPrincipleStatus | "">(() => oneOf(initial.get("status"), Object.keys(GUIDING_PRINCIPLE_STATUS_LABEL) as GuidingPrincipleStatus[]));
  const [priorityFilter, setPriorityFilter] = useState<GuidingPrinciplePriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadGuidingPrinciples() {
    if (!projectId) return;
    try {
      setGuidingPrinciples(await projectGuidingPrincipleApi.list(projectId, { include_archived: includeArchived }));
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
    void reloadGuidingPrinciples();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciples === null || project === null) return <Spinner />;

  const filtered = guidingPrinciples.filter((g) => {
    if (statusFilter && g.status !== statusFilter) return false;
    if (priorityFilter && g.priority !== priorityFilter) return false;
    if (search && !g.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<GuidingPrinciple>[] = [
    { key: "name", label: "Name", render: (g) => g.name },
    { key: "priority", label: "Priority", render: (g) => GUIDING_PRINCIPLE_PRIORITY_LABEL[g.priority] },
    {
      key: "status", label: "Status",
      render: (g) => <span className={`badge badge--${GUIDING_PRINCIPLE_STATUS_TONE[g.status]}`}>{GUIDING_PRINCIPLE_STATUS_LABEL[g.status]}</span>,
    },
    { key: "version", label: "Version", render: (g) => `v${g.version_number}` },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Guiding Principle</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Guiding Principle
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Guiding Principles"
          columns={columns}
          rows={filtered}
          rowKey={(g) => g.id}
          onRowClick={(g) => navigate(`/projects/${projectId}/modules/context_strategy/guiding-principles/${g.id}`)}
          emptyState={<p className="text-muted">No Guiding Principle recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.guidingPrinciples.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Guiding Principles…" searchAriaLabel="Search Guiding Principles"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as GuidingPrincipleStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(GUIDING_PRINCIPLE_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Priority">
            <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as GuidingPrinciplePriority | "")}>
              <option value="">All priorities</option>
              {Object.entries(GUIDING_PRINCIPLE_PRIORITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <GuidingPrincipleFormModal
          scopeLabel="project"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: GuidingPrincipleFieldValues) => {
            setCreateError(null);
            try {
              await projectGuidingPrincipleApi.create(projectId, values);
              showToast("Guiding Principle created.");
              setCreating(false);
              await reloadGuidingPrinciples();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Guiding Principle."));
            }
          }}
        />
      )}
    </div>
  );
}
