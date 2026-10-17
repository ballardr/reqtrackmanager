/**
 * Module: modules/decisions/ProjectDecisionsPage
 *
 * The Decision Management module's project-scoped route component,
 * mounted at
 * `/projects/:projectId/modules/decisions` (`module.ts`): a `DirectoryTable`
 * + `FilterPanel` list, a "New decision" `Modal`, and a row click opening
 * `DecisionQuickViewPanel` as a minimal read-only `SidePanel` peek — whose
 * own "View full details" link leads to `DecisionDetailPage.tsx`'s full
 * page for management and full context (see that
 * page's own docstring and `docs/ux-style-guide.md`'s "Pattern: entity
 * detail panel" checklist for why the two-tier shape replaced the original
 * SidePanel-only `DecisionDetailPanel.tsx`). Fetches the owning project's
 * `organization_id` once and passes it down wherever an org-scoped call is
 * needed (Decision Templates, org member list) — same "no `ProjectContext`
 * provider, fetch the project directly" convention `ProjectCompliancePage
 * .tsx` describes.
 *
 * Decision Types moved off this page's own tab bar to Project Admin's
 * `projectAdminSections` contribution (grouped with the
 * project's other definition-table settings — Action Types, Custom
 * Fields — rather than the module's day-to-day working page); this page
 * still fetches the project's decision types (`decisionTypes` state) for
 * the list's Type column/filter and the create/detail forms, it just no
 * longer hosts their CRUD UI.
 *
 * Links to and from a Decision (Requirements, Pain Points, other Decisions, ...) are shown and
 * edited in the shared Links panel on `DecisionDetailPage.tsx`, and a Decision's links appear on
 * the other record's own page the same way — nothing here is Decision-specific.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import { DecisionQuickViewPanel } from "./DecisionQuickViewPanel";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionFieldValues, DecisionStatus, DecisionTemplate, DecisionTypeDefinition } from "./types";

export function ProjectDecisionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [decisionTypes, setDecisionTypes] = useState<DecisionTypeDefinition[]>([]);
  const [templates, setTemplates] = useState<DecisionTemplate[]>([]);
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<DecisionStatus | "">("");
  const [decisionTypeFilter, setDecisionTypeFilter] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [ownedByMe, setOwnedByMe] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Decision | null>(null);

  async function reloadDecisions() {
    if (!projectId) return;
    try {
      setDecisions(await decisionsApi.listDecisions(projectId, {
        search: search || undefined,
        status: statusFilter || undefined,
        decision_type_id: decisionTypeFilter || undefined,
        include_archived: includeArchived,
        owner_mine: ownedByMe,
      }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Decisions module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers);
      decisionsApi.listDecisionTemplates(proj.organization_id).then(setTemplates).catch(() => setTemplates([]));
    });
    decisionsApi.listDecisionTypes(projectId).then(setDecisionTypes);
  }, [projectId]);

  useEffect(() => {
    void reloadDecisions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, search, statusFilter, decisionTypeFilter, includeArchived, ownedByMe]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decisions === null || project === null) return <Spinner />;

  const columns: DirectoryColumn<Decision>[] = [
    { key: "unique_code", label: "Code", render: (d) => d.unique_code },
    { key: "title", label: "Title", render: (d) => d.title },
    {
      key: "type", label: "Type",
      render: (d) => decisionTypes.find((t) => t.id === d.decision_type_id)?.name ?? "—",
    },
    {
      key: "status", label: "Status",
      render: (d) => <span className={`badge badge--${DECISION_STATUS_TONE[d.status]}`}>{DECISION_STATUS_LABEL[d.status]}</span>,
    },
    {
      key: "owner", label: "Owner",
      render: (d) => <PrincipalBadge principal={d.owner} />,
    },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Decisions</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New decision
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Decisions"
          columns={columns}
          rows={decisions}
          rowKey={(d) => d.id}
          onRowClick={setSelected}
          emptyState={<p className="text-muted">No Decisions recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="decisions.list" total={decisions.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search decisions…" searchAriaLabel="Search decisions"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as DecisionStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(DECISION_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Decision type">
            <select className="input" value={decisionTypeFilter} onChange={(e) => setDecisionTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {decisionTypes.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Owned by me or my groups" checked={ownedByMe} onChange={setOwnedByMe} />
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <DecisionFormModal
          decisionTypes={decisionTypes}
          templates={templates}
          orgUsers={orgUsers}
          organizationId={project.organization_id}
          projectId={projectId}
          currentUserId={user?.id}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: DecisionFieldValues) => {
            setCreateError(null);
            try {
              await decisionsApi.createDecision(projectId, values);
              showToast("Decision created.");
              setCreating(false);
              await reloadDecisions();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create decision."));
            }
          }}
        />
      )}

      {selected && (
        <DecisionQuickViewPanel
          projectId={projectId}
          decision={selected}
          decisionTypes={decisionTypes}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
