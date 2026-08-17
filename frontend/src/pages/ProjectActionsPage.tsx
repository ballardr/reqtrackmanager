import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ActionTypeDefinition, OrgUser, Project, RequirementAction, RequirementActionOutcome } from "../api/types";
import { REQUIREMENT_ACTION_OUTCOME_LABEL } from "../api/types";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

const OUTCOME_OPTIONS: RequirementActionOutcome[] = ["pending", "completed", "failed"];

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
  const [actions, setActions] = useState<RequirementAction[] | null>(null);
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [outcomeFilter, setOutcomeFilter] = useState<RequirementActionOutcome | "">("");
  const [typeFilter, setTypeFilter] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [showNewForm, setShowNewForm] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newActionTypeId, setNewActionTypeId] = useState("");
  const [newAssigneeId, setNewAssigneeId] = useState("");
  const [newDueDate, setNewDueDate] = useState("");

  function listParams(): string {
    const params = new URLSearchParams();
    if (outcomeFilter) params.set("outcome_status", outcomeFilter);
    if (typeFilter) params.set("action_type_id", typeFilter);
    if (includeArchived) params.set("include_archived", "true");
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }

  async function reload() {
    if (!projectId) return;
    setActions(null);
    const [types, list] = await Promise.all([
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/actions${listParams()}`),
    ]);
    setActionTypes(types);
    setActions(list);
    if (!newActionTypeId && types[0]) setNewActionTypeId(types[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, outcomeFilter, typeFilter, includeArchived]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`));
      } catch {
        // No org role reachable for this user — assignee names simply
        // fall back to raw user ids below.
      }
    })();
  }, [projectId]);

  async function createAction() {
    if (!newTitle.trim() || !newActionTypeId) return;
    await api.post(`/api/v1/projects/${projectId}/actions`, {
      title: newTitle,
      description: newDescription,
      action_type_id: newActionTypeId,
      assignee_id: newAssigneeId || null,
      due_date: newDueDate || null,
    });
    setNewTitle("");
    setNewDescription("");
    setNewAssigneeId("");
    setNewDueDate("");
    setShowNewForm(false);
    reload();
  }

  function actionTypeName(id: string) {
    return actionTypes.find((t2) => t2.id === id)?.name ?? "—";
  }
  function assigneeName(id: string | null) {
    if (!id) return strings.reviews.unassigned;
    return orgUsers.find((u) => u.user_id === id)?.display_name ?? id;
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.actions.title}</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> {strings.actions.newAction}
        </button>
      </div>

      {showNewForm && (
        <div className="card stack">
          <input className="input" placeholder={strings.actions.name} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
          <textarea
            className="input" rows={2} placeholder={strings.actions.description} value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
          />
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.actions.actionType}
              {/* Explicit aria-label — see the equivalent select in
                  RequirementDetailPage.tsx for why a label-wrapped
                  <select>'s ARIA name otherwise folds in its own option
                  text too. */}
              <select
                className="input" aria-label={strings.actions.actionType}
                value={newActionTypeId} onChange={(e) => setNewActionTypeId(e.target.value)}
              >
                {actionTypes.map((at) => (
                  <option key={at.id} value={at.id}>
                    {at.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.actions.assignee}
              <select
                className="input" aria-label={strings.actions.assignee}
                value={newAssigneeId} onChange={(e) => setNewAssigneeId(e.target.value)}
              >
                <option value="">{strings.reviews.unassigned}</option>
                {orgUsers.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.display_name} ({u.email})
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.actions.dueDate}
              <input className="input" type="date" value={newDueDate} onChange={(e) => setNewDueDate(e.target.value)} />
            </label>
          </div>
          <button
            className="btn btn-primary" style={{ alignSelf: "flex-start" }}
            onClick={createAction} disabled={!newTitle.trim() || !newActionTypeId}
          >
            {strings.common.create}
          </button>
        </div>
      )}

      <div className="side-grid">
        <div className="stack">
          {!actions && <Spinner />}
          {actions && actions.length === 0 && <p className="text-muted">{strings.actions.empty}</p>}
          {actions && actions.length > 0 && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>{strings.actions.uniqueCode}</th>
                    <th>{strings.actions.name}</th>
                    <th>{strings.actions.actionType}</th>
                    <th>{strings.actions.outcome}</th>
                    <th>{strings.actions.assignee}</th>
                    <th>{strings.actions.dueDate}</th>
                  </tr>
                </thead>
                <tbody>
                  {actions.map((a) => (
                    <tr key={a.id}>
                      <td className="text-muted">{a.unique_code}</td>
                      <td>
                        <Link to={`/projects/${projectId}/actions/${a.id}`}>{a.title}</Link>
                        {a.is_archived && <span className="badge" style={{ marginLeft: "0.4rem" }}>{strings.actions.archived}</span>}
                      </td>
                      <td className="text-muted">{actionTypeName(a.action_type_id)}</td>
                      <td>
                        <span className="badge">{REQUIREMENT_ACTION_OUTCOME_LABEL[a.outcome_status]}</span>
                      </td>
                      <td className="text-muted">{assigneeName(a.assignee_id)}</td>
                      <td className="text-muted">{a.due_date ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
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
          <FilterCheckbox label={strings.actions.includeArchived} checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>
    </div>
  );
}
