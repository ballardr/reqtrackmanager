/**
 * Module: modules/decisions/ProjectDecisionsPage
 *
 * The Decision Management module's project-scoped route component
 * (docs/plans/module-04-decision-management-plan.md Phase 5), mounted at
 * `/projects/:projectId/modules/decisions` (`module.ts`). Mirrors
 * `modules/compliance/ProjectCompliancePage.tsx`'s own top-level shape: a
 * `Tabs` bar ("Decisions" — `DirectoryTable` + `FilterPanel`, a "New
 * decision" `Modal`, row click opens `DecisionDetailPanel` as a `SidePanel`;
 * "Decision Types" — `DecisionTypesPanel`), fetching the owning project's
 * `organization_id` once and passing it down wherever an org-scoped call is
 * needed (Decision Templates, org member list) — same "no `ProjectContext`
 * provider, fetch the project directly" convention that page's own docstring
 * describes.
 *
 * **Deliberately out of scope for Phase 5** (Decided by: Agent): a
 * `requirementDetailSections`/`requirementLinkPickerTabs` contribution
 * showing/adding Decision links from the *Requirement* Detail page's own
 * Links card — the reverse direction from `DecisionRelationshipsSection`'s
 * own Decision-side creation. The backend's Phase 4 API has no "list
 * Decision links touching a given Requirement" endpoint (only `GET
 * /{decision_id}/relationships`, decision-centric) — building the reverse
 * listing endpoint too wasn't in Phase 4's own shipped scope, and adding it
 * now would be scope creep beyond this plan's own Phase 5 text ("project-
 * scoped Decision list, detail page, create/edit form, and an approve/
 * reject/supersede action flow"). Every relationship is still fully
 * visible and creatable from the Decision's own detail panel in both
 * directions (`GET /{decision_id}/relationships` returns incoming and
 * outgoing links alike) — this only affects where in the UI it can be
 * *seen from*, not what can be expressed. Compliance's own Phase 34 drew
 * the identical one-direction-only line for its first pass (see that
 * module's `RequirementTraceabilityLinksSection.tsx` docstring); this
 * mirrors that precedent rather than inventing a new one. Revisit if a real
 * need for the reverse direction surfaces.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionDetailPanel } from "./DecisionDetailPanel";
import { DecisionFormModal } from "./DecisionFormModal";
import { DecisionTypesPanel } from "./DecisionTypesPanel";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionFieldValues, DecisionStatus, DecisionTemplate, DecisionTypeDefinition } from "./types";

type DecisionsTabKey = "decisions" | "decision-types";

export function ProjectDecisionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState<DecisionsTabKey>("decisions");
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

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Decision | null>(null);

  async function reloadDecisionTypes() {
    if (!projectId) return;
    setDecisionTypes(await decisionsApi.listDecisionTypes(projectId));
  }

  async function reloadDecisions() {
    if (!projectId) return;
    try {
      setDecisions(await decisionsApi.listDecisions(projectId, {
        search: search || undefined,
        status: statusFilter || undefined,
        decision_type_id: decisionTypeFilter || undefined,
        include_archived: includeArchived,
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
    void reloadDecisionTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    void reloadDecisions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, search, statusFilter, decisionTypeFilter, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decisions === null || project === null) return <Spinner />;

  const userOptions = orgUsers.map((u) => ({ id: u.user_id, display_name: u.display_name }));

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
      render: (d) => userOptions.find((u) => u.id === d.owner_id)?.display_name ?? "—",
    },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Decisions</h1>
      <Tabs<DecisionsTabKey>
        idPrefix="project-decisions"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "decisions", label: "Decisions" },
          { key: "decision-types", label: "Decision Types" },
        ]}
      />
      {tab === "decisions" && (
        <div className="stack" {...tabPanelProps("project-decisions", "decisions")}>
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
              <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
            </FilterPanel>
          </div>
        </div>
      )}
      {tab === "decision-types" && (
        <div {...tabPanelProps("project-decisions", "decision-types")}>
          <DecisionTypesPanel projectId={projectId} items={decisionTypes} onReload={reloadDecisionTypes} />
        </div>
      )}

      {creating && (
        <DecisionFormModal
          decisionTypes={decisionTypes}
          templates={templates}
          userOptions={userOptions}
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
        <DecisionDetailPanel
          projectId={projectId}
          decision={selected}
          decisionTypes={decisionTypes}
          orgUsers={orgUsers}
          currentUserId={user?.id}
          onClose={() => setSelected(null)}
          onChanged={async (updated) => {
            setSelected(updated);
            await reloadDecisions();
          }}
        />
      )}
    </div>
  );
}
