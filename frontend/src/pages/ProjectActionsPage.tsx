import { Plus } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { CollectedLink } from "../api/artefactLinks";
import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  OrgUser,
  PrincipalRef,
  Project,
  RequirementAction,
  RequirementActionOutcome,
} from "../api/types";
import { ENTITY_ACCENT_COLOR, REQUIREMENT_ACTION_OUTCOME_LABEL, REQUIREMENT_ACTION_OUTCOME_TONE } from "../api/types";
import { FilterBadge } from "../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { PrincipalBadge } from "../components/PrincipalBadge";
import { QuickLinkField } from "../components/QuickLinkField";
import { SortableHeader } from "../components/SortableHeader";
import { cycleSort } from "../components/sortState";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { Spinner } from "../components/Spinner";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { useCommitQuickLinks } from "../hooks/useCommitQuickLinks";
import { useCommitTags } from "../hooks/useCommitTags";
import { useProjectScope } from "../hooks/useProjectScope";
import { useTagFilter } from "../hooks/useTagFilter";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { TagField } from "../components/TagField";
import { TagFilterField } from "../components/TagFilterField";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { ActionFields } from "../components/ActionFields";
import { useLoadOnChange } from "../hooks/useLoadOnChange";

const strings = t();

const OUTCOME_OPTIONS: RequirementActionOutcome[] = ["pending", "completed", "failed"];

const ACTION_SORT_KEYS = ["unique_code", "title", "outcome_status", "due_date"] as const;
type ActionSortKey = (typeof ACTION_SORT_KEYS)[number];

/**
 * Project-wide list of requirement actions (review/test/etc.) — a
 * `RequirementAction` has its own project-scoped identity independent of
 * any single requirement (it may be linked from several, or none yet), so
 * this page is the project-level home for browsing/creating them,
 * separate from any one requirement's own "linked actions" card
 * (`RequirementDetailPage.tsx`). Filters mirror the backend's own query
 * params (`outcome_status`, `action_type_id`, `include_archived`).
 */
export function ProjectActionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "requirement_action");
  const commitTags = useCommitTags(projectId ?? "", "requirement_action");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [newTags, setNewTags] = useState<string[]>([]);
  const [actions, setActions] = useState<RequirementAction[] | null>(null);
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  // Filters and sort live in the URL so the list comes back as it was left after a visit to a record.
  const [outcomeFilter, setOutcomeFilter] = useUrlChoice("outcome", Object.keys(REQUIREMENT_ACTION_OUTCOME_LABEL) as RequirementActionOutcome[]);
  const [typeFilter, setTypeFilter] = useUrlText("type");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  // Column-header sorting — this list has no
  // backend pagination at all (`routers/actions.py::list_actions` always
  // returns every match), so sorting the already-loaded array client-side
  // is safe: unlike `RequirementsPage`/`ChangeRequestsPage`, there's no
  // partially-loaded page to misrepresent by sorting only what's visible.
  const [sort, setSort] = useUrlSort(ACTION_SORT_KEYS);

  const [showNewForm, setShowNewForm] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newActionTypeId, setNewActionTypeId] = useState("");
  const [newAssignee, setNewAssignee] = useState<PrincipalRef | null>(null);
  const [newDueDate, setNewDueDate] = useState("");
  const [newQuickLinks, setNewQuickLinks] = useState<CollectedLink[]>([]);

  function listParams(): string {
    const params = new URLSearchParams();
    if (outcomeFilter) params.set("outcome_status", outcomeFilter);
    if (typeFilter) params.set("action_type_id", typeFilter);
    if (includeArchived) params.set("include_archived", "true");
    for (const tag of tagFilter.tags) params.append("tag", tag);
    if (tagFilter.active) params.set("tag_mode", tagFilter.mode);
    if (projectScope.widened) params.set("project_scope", projectScope.scope);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }

  function toggleOutcomeFilter(outcome: RequirementActionOutcome) {
    setOutcomeFilter((current) => (current === outcome ? "" : outcome));
  }

  // Request-sequencing guard, same shape as `RequirementsPage.tsx`'s: a
  // filter change starts a new load while the previous one may still be in
  // flight, and the slower, stale response must not overwrite the newer
  // one (e.g. toggling "Include archived" right after the page loads).
  const beginLoad = useRequestSequence();

  async function reload() {
    if (!projectId) return;
    const isLatest = beginLoad();
    setActions(null);
    const [types, list] = await Promise.all([
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/actions${listParams()}`),
    ]);
    if (!isLatest()) return;
    setActionTypes(types);
    setActions(list);
    if (!newActionTypeId && types[0]) setNewActionTypeId(types[0].id);
  }

  useLoadOnChange(reload, [projectId, outcomeFilter, typeFilter, includeArchived, tagFilter.query, projectScope.scope]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        setOrganizationId(project.organization_id);
        setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`));
      } catch {
        // No org role reachable for this user — assignee names simply
        // fall back to raw user ids below.
      }
    })();
  }, [projectId]);

  async function createAction() {
    if (!newTitle.trim() || !newActionTypeId) return;
    try {
      const created = await api.post<RequirementAction>(`/api/v1/projects/${projectId}/actions`, {
        title: newTitle,
        description: newDescription,
        action_type_id: newActionTypeId,
        assignee: newAssignee,
        due_date: newDueDate || null,
      });
      setNewTitle("");
      setNewDescription("");
      setNewAssignee(null);
      setNewDueDate("");
      setShowNewForm(false);
      reload();
      showToast(strings.actions.created);
      await commitQuickLinks(created.id, newQuickLinks);
      setNewQuickLinks([]);
      await commitTags(created.id, newTags);
      setNewTags([]);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  function compareActions(a: RequirementAction, b: RequirementAction, key: ActionSortKey): number {
    if (key === "due_date") {
      // Nulls (no due date set) always sort last, in either direction.
      if (a.due_date === b.due_date) return 0;
      if (a.due_date === null) return 1;
      if (b.due_date === null) return -1;
      return a.due_date < b.due_date ? -1 : 1;
    }
    const av = a[key].toLowerCase();
    const bv = b[key].toLowerCase();
    return av < bv ? -1 : av > bv ? 1 : 0;
  }

  const sortedActions = useMemo(() => {
    if (!actions || !sort) return actions;
    const sorted = [...actions].sort((a, b) => compareActions(a, b, sort.key));
    return sort.direction === "desc" ? sorted.reverse() : sorted;
  }, [actions, sort]);

  function actionTypeName(id: string) {
    return actionTypes.find((t2) => t2.id === id)?.name ?? "—";
  }

  return (
    <div className="stack">
      <ListPageLayout
        title={strings.actions.title}
        actions={
          <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
            <Plus /> {strings.actions.newAction}
          </button>
        }
        filter={
          <FilterPanel sectionKey="projectActionsFilters">
            <FilterField label={strings.actions.actionType}>
              <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">{strings.actions.allTypes}</option>
                {actionTypes.map((at) => (
                  <option key={at.id} value={at.id}>
                    {at.name}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label={strings.actions.outcome}>
              <select className="input" value={outcomeFilter} onChange={(e) => setOutcomeFilter(e.target.value as RequirementActionOutcome | "")}>
                <option value="">{strings.actions.allOutcomes}</option>
                {OUTCOME_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {REQUIREMENT_ACTION_OUTCOME_LABEL[o]}
                  </option>
                ))}
              </select>
            </FilterField>
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label={strings.actions.includeArchived} checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        {showNewForm && (
          <div className="card stack">
            <ActionFields
              values={{ title: newTitle, description: newDescription, actionTypeId: newActionTypeId, assignee: newAssignee, dueDate: newDueDate }}
              onChange={(v) => {
                setNewTitle(v.title);
                setNewDescription(v.description);
                setNewActionTypeId(v.actionTypeId);
                setNewAssignee(v.assignee);
                setNewDueDate(v.dueDate);
              }}
              actionTypes={actionTypes}
              orgUsers={orgUsers}
              organizationId={organizationId}
              projectId={projectId}
            />
            <QuickLinkField projectId={projectId ?? ""} artefactType="requirement_action" preferredType="requirement" value={newQuickLinks} onChange={setNewQuickLinks} />
            <TagField projectId={projectId ?? ""} artefactType="requirement_action" value={newTags} onChange={setNewTags} />
            <button
              className="btn btn-primary" style={{ alignSelf: "flex-start" }}
              onClick={createAction} disabled={!newTitle.trim() || !newActionTypeId}
            >
              {strings.common.create}
            </button>
          </div>
        )}
          <div className="stack">
            {!actions && <Spinner />}
            {actions && actions.length === 0 && <p className="text-muted">{strings.actions.empty}</p>}
            {actions && actions.length > 0 && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <SortableHeader
                        label={strings.actions.uniqueCode} sortKey="unique_code" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        label={strings.actions.name} sortKey="title" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <th>{strings.actions.actionType}</th>
                      <SortableHeader
                        label={strings.actions.outcome} sortKey="outcome_status" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <th>{strings.actions.assignee}</th>
                      <SortableHeader
                        label={strings.actions.dueDate} sortKey="due_date" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {(sortedActions ?? actions).map((a) => (
                      <tr
                        key={a.id}
                        className="entity-accent-row"
                        style={{ ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.action }}
                      >
                        <td className="text-muted"><RecordCode code={a.unique_code} ownerProjectCode={a.from_project_code} /></td>
                        <td>
                          <Link to={`/projects/${rowProjectId(a, projectId ?? "")}/actions/${a.id}`}>{a.title}</Link>
                          <ProjectScopeLabel row={a} />
                          {a.is_archived && <Badge className="badge-after">{strings.actions.archived}</Badge>}
                        </td>
                        <td className="text-muted">{actionTypeName(a.action_type_id)}</td>
                        <td>
                          <FilterBadge
                            active={outcomeFilter === a.outcome_status}
                            tone={REQUIREMENT_ACTION_OUTCOME_TONE[a.outcome_status]}
                            onClick={() => toggleOutcomeFilter(a.outcome_status)}
                          >
                            {REQUIREMENT_ACTION_OUTCOME_LABEL[a.outcome_status]}
                          </FilterBadge>
                        </td>
                        <td className="text-muted"><PrincipalBadge principal={a.assignee} placeholder={strings.reviews.unassigned} /></td>
                        <td className="text-muted">{a.due_date ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
      </ListPageLayout>
    </div>
  );
}
