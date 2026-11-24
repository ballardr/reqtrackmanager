/**
 * Module: modules/decisions/ProjectDecisionsPage
 *
 * The Decision Management module's project-scoped route component, mounted at `/projects/:projectId/modules/decisions`
 * (`module.ts`): a `DirectoryTable` + `FilterPanel` list and a "New decision" `Modal`. A row is a link to
 * `DecisionDetailPage.tsx` in the row's own project (`rowProjectId`), as in every other record list. It fetches the project's
 * `organization_id` once and passes it down wherever an organisation-scoped call is needed (Decision Templates,
 * organisation member list), without a `ProjectContext` provider, as `ProjectCompliancePage.tsx` does.
 *
 * It also fetches the project's decision types (`decisionTypes`) for the Type column and filter and the create and
 * detail forms; their CRUD is in Project Admin's `projectAdminSections` entry.
 *
 * The list opens on Decisions still to be made (draft, proposed, under review): the "Open only" filter is ticked and
 * visible, and a link with a valid `status`, or `open=0`, starts with it off (`hooks/useOpenOnly.ts`).
 *
 * Links to and from a Decision are shown and edited in the shared Links panel on `DecisionDetailPage.tsx`, and appear
 * on the other record's page the same way; nothing here is Decision-specific.
 */
import { RecordCode } from "../../components/RecordCode";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import { DECISION_OPEN_STATUSES, DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionFieldValues, DecisionStatus, DecisionTemplate, DecisionTypeDefinition } from "./types";
import { Badge } from "../../components/Badge";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { addSortParams, TIME_SORT_KEYS, useListSort } from "../../hooks/useListSort";
import { SortField } from "../../components/SortField";
import { sortRows, TIME_SORT_VALUES } from "../../utils/sortRows";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useCreatedToast } from "../../hooks/useCreatedToast";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { useStrings } from "../../context/TerminologyContext";
import { labelOptions } from "../../utils/labelOptions";

const DECISION_SORT_KEYS = ["unique_code", "title", "type", "status", "owner", ...TIME_SORT_KEYS] as const;

export function ProjectDecisionsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "decision");
  const commitTags = useCommitTags(projectId ?? "", "decision");
  const announceCreated = useCreatedToast(projectId ?? "", "decision");
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
  const listSort = useListSort("decisions", DECISION_SORT_KEYS, "unique_code");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadDecisions() {
    if (!projectId) return;
    try {
      setDecisions(await decisionsApi.listDecisions(projectId, {
        search: search || undefined,
        status: statusFilter || undefined,
        decision_type_id: decisionTypeFilter || undefined,
        include_archived: includeArchived,
        owner_mine: ownedByMe,
        ...tagFilter.listFilters,
        project_scope: projectScope.scope,
      }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Decisions module is not enabled for this project's organisation, or you do not have access to it."));
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
    addSortParams(params, listSort.sort);
    return params;
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decisions === null || project === null) return <Spinner />;

  const rows = openOnly ? decisions.filter((d) => DECISION_OPEN_STATUSES.includes(d.status)) : decisions;
  // An empty list the "Open only" default caused says so, so it is not read as "nothing recorded".
  const emptyBecauseOfOpenOnly = openOnly && rows.length === 0 && decisions.length > 0;
  const typeName = (d: Decision) => decisionTypes.find((t) => t.id === d.decision_type_id)?.name ?? null;
  const sorted = sortRows(rows, listSort.sort, {
    ...TIME_SORT_VALUES,
    unique_code: (d) => d.unique_code,
    title: (d) => d.title,
    type: typeName,
    status: (d) => DECISION_STATUS_LABEL[d.status],
    owner: (d) => d.owner?.label ?? null,
  });

  const columns: DirectoryColumn<Decision>[] = [
    { key: "unique_code", label: "Code", sortable: true, render: (d) => <RecordCode code={d.unique_code} ownerProjectCode={d.from_project_code} /> },
    { key: "title", label: "Title", sortable: true, render: (d) => <>{d.title}<ProjectScopeLabel row={d} /></> },
    {
      key: "type", label: "Type", sortable: true,
      render: (d) => decisionTypes.find((t) => t.id === d.decision_type_id)?.name ?? "—",
    },
    {
      key: "status", label: "Status", sortable: true,
      render: (d) => <Badge tone={DECISION_STATUS_TONE[d.status]}>{DECISION_STATUS_LABEL[d.status]}</Badge>,
    },
    {
      key: "owner", label: "Owner", sortable: true,
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
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              allLabel="All statuses"
              options={labelOptions(DECISION_STATUS_LABEL)}
            />
            <FilterSelect
              label="Decision type"
              value={decisionTypeFilter}
              onChange={setDecisionTypeFilter}
              allLabel="All types"
              options={decisionTypes.map((t) => ({ value: t.id, label: t.name }))}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <FilterCheckbox label="Owned by me or my groups" checked={ownedByMe} onChange={setOwnedByMe} />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <SortField list={listSort} columns={columns} codeKey="unique_code" />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Decisions"
          columns={columns}
          rows={sorted}
          sort={listSort.sort}
          onSort={listSort.onHeaderSort}
          rowKey={(d) => d.id}
          placements={{ projectId, artefactType: "decision", rowId: (d) => d.id }}
          rowHref={(d) => `/projects/${rowProjectId(d, projectId)}/modules/decisions/${d.id}`}
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
              announceCreated("Decision", created);
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
    </div>
  );
}
