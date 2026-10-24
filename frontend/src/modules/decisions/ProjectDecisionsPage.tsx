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
 * The list opens on Decisions still to be made (draft, proposed, under review): the
 * "Open only" filter is ticked and stays visible, and a link with a valid
 * `status`, or `open=0`, starts with it off (`hooks/useOpenOnly.ts`).
 *
 * Links to and from a Decision (Requirements, Pain Points, other Decisions, ...) are shown and
 * edited in the shared Links panel on `DecisionDetailPage.tsx`, and a Decision's links appear on
 * the other record's own page the same way — nothing here is Decision-specific.
 */
import { RecordCode } from "../../components/RecordCode";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import { DecisionQuickViewPanel } from "./DecisionQuickViewPanel";
import { DECISION_OPEN_STATUSES, DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionFieldValues, DecisionStatus, DecisionTemplate, DecisionTypeDefinition } from "./types";
import { Badge } from "../../components/Badge";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { addSharedListFilters } from "../../utils/listFilterParams";

export function ProjectDecisionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "decision");
  const commitTags = useCommitTags(projectId ?? "", "decision");
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [decisionTypes, setDecisionTypes] = useState<DecisionTypeDefinition[]>([]);
  const [templates, setTemplates] = useState<DecisionTemplate[]>([]);
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Filters live in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(DECISION_STATUS_LABEL) as DecisionStatus[]);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, Object.keys(DECISION_STATUS_LABEL));
  const [decisionTypeFilter, setDecisionTypeFilter] = useUrlText("type");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const [ownedByMe, setOwnedByMe] = useUrlFlag("mine");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

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
        tags: tagFilter.tags,
        tag_mode: tagFilter.mode,
        project_scope: projectScope.scope,
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

  useLoadOnChange(reloadDecisions, [projectId, search, statusFilter, decisionTypeFilter, includeArchived, ownedByMe, tagFilter.query, projectScope.scope]);

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (decisionTypeFilter) params.set("type", decisionTypeFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (ownedByMe) params.set("mine", "true");
    if (openOnly) params.set("open_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decisions === null || project === null) return <Spinner />;

  const rows = openOnly ? decisions.filter((d) => DECISION_OPEN_STATUSES.includes(d.status)) : decisions;
  // An empty list the "Open only" default caused says so, so it is not read as "nothing recorded".
  const emptyBecauseOfOpenOnly = openOnly && rows.length === 0 && decisions.length > 0;

  const columns: DirectoryColumn<Decision>[] = [
    { key: "unique_code", label: "Code", render: (d) => <RecordCode code={d.unique_code} ownerProjectCode={d.from_project_code} /> },
    { key: "title", label: "Title", render: (d) => <>{d.title}<ProjectScopeLabel row={d} /></> },
    {
      key: "type", label: "Type",
      render: (d) => decisionTypes.find((t) => t.id === d.decision_type_id)?.name ?? "—",
    },
    {
      key: "status", label: "Status",
      render: (d) => <Badge tone={DECISION_STATUS_TONE[d.status]}>{DECISION_STATUS_LABEL[d.status]}</Badge>,
    },
    {
      key: "owner", label: "Owner",
      render: (d) => <PrincipalBadge principal={d.owner} />,
    },
  ];

  return (
    <div className="container stack">
      <ListPageLayout
        title="Decisions"
        records={{ projectId, recordType: "decision", filters: filterParams().toString(), onImported: reloadDecisions }}
        actions={
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New decision
          </button>
        }
        filter={
          <FilterPanel
            sectionKey="decisions.list" total={rows.length}
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
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <FilterCheckbox label="Owned by me or my groups" checked={ownedByMe} onChange={setOwnedByMe} />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Decisions"
          columns={columns}
          rows={rows}
          rowKey={(d) => d.id}
          onRowClick={setSelected}
          emptyState={
            <p className="text-muted">
              {emptyBecauseOfOpenOnly
                ? "No open Decisions. Untick Open only to include approved, rejected and superseded ones."
                : decisions.length > 0
                  ? "No Decisions match these filters."
                  : "No Decisions recorded for this project yet."}
            </p>
          }
        />
      </ListPageLayout>

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
          onSave={async (values: DecisionFieldValues, quickLinks, tags) => {
            setCreateError(null);
            try {
              const created = await decisionsApi.createDecision(projectId, values);
              showToast("Decision created.");
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
              await reloadDecisions();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create decision."));
            }
          }}
        />
      )}

      {selected && (
        <DecisionQuickViewPanel
          projectId={rowProjectId(selected, projectId)}
          decision={selected}
          decisionTypes={decisionTypes}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
