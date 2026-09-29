/**
 * Module: modules/context_strategy/OrgGuidingPrinciplesPanel
 *
 * The org-scoped equivalent of `ProjectGuidingPrinciplesPage.tsx` — an
 * organisation's own org-scoped Guiding Principle records (Phase 0 Q2's
 * org/project scope discriminator), rendered as an `OrgOverviewPage.tsx`
 * `ResourceMenu` group (`module.ts`'s `orgOverviewSections`).
 *
 * **Placement decision, Decided by: Agent — follows `OrgStrategiesPanel.tsx`/
 * `OrgFutureStatesPanel.tsx`'s own precedent directly, resolving that
 * precedent's own "revisit if a later org/project-scoped artefact suggests a
 * different placement" note.** An org-scoped Guiding Principle is the same
 * shape as an org-scoped Strategy/Future State — org-level *content* an
 * Owner/Approver works with day to day, not an admin-configuration table —
 * so it lands on `orgOverviewSections` (Org Dashboard) too, for the same
 * reasoning those two components' own docstrings already give. Pain Point
 * Type (Phase 7.3) landed on `orgAdminSections` instead because it *is* a
 * configuration table with no org-scoped artefact behind it at all — a
 * different case entirely, not a competing precedent for this one. No
 * deviation found worth flagging: Guiding Principle's org/project dual scope
 * is exactly the case that precedent's own "revisit" note anticipated, and
 * it confirms rather than overturns the existing placement.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE } from "./types";
import type { GuidingPrinciple, GuidingPrincipleFieldValues, GuidingPrinciplePriority, GuidingPrincipleStatus } from "./types";

export function OrgGuidingPrinciplesPanel({ orgId }: { orgId: string }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [guidingPrinciples, setGuidingPrinciples] = useState<GuidingPrinciple[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<GuidingPrincipleStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<GuidingPrinciplePriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadGuidingPrinciples() {
    try {
      setGuidingPrinciples(await orgGuidingPrincipleApi.list(orgId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    void reloadGuidingPrinciples();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, includeArchived]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciples === null) return <Spinner />;

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
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Guiding Principle
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Organisation Guiding Principles"
          columns={columns}
          rows={filtered}
          rowKey={(g) => g.id}
          onRowClick={(g) => navigate(`/orgs/${orgId}/modules/context_strategy/guiding-principles/${g.id}`)}
          emptyState={<p className="text-muted">No organisation-scoped Guiding Principle recorded yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.orgGuidingPrinciples.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Guiding Principles…" searchAriaLabel="Search organisation Guiding Principles"
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
          scopeLabel="organisation"
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: GuidingPrincipleFieldValues) => {
            setCreateError(null);
            try {
              await orgGuidingPrincipleApi.create(orgId, values);
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
