import { Archive } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  Comment,
  FileAsset,
  OrgUser,
  Requirement,
  RequirementAction,
  RequirementActionOutcome,
} from "../api/types";
import { REQUIREMENT_ACTION_OUTCOME_LABEL } from "../api/types";
import { CommentThread } from "../components/CommentThread";
import { FileAttachmentList } from "../components/FileAttachmentList";
import { Spinner } from "../components/Spinner";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Detail view for a single requirement action: an editable outcome-status
 * control (transitioning away from "pending" stamps `completed_at`/
 * `completed_by` server-side — see `RequirementActionUpdate`'s docstring),
 * the list of requirements this action is linked to (the reverse of
 * `RequirementDetailPage.tsx`'s Actions card), its own file attachments
 * (`FileAttachmentList`, always enabled — actions have no lock concept the
 * way a requirement does), and a reused `CommentThread` discussion.
 */
export function ActionDetailPage() {
  const { projectId, actionId } = useParams<{ projectId: string; actionId: string }>();
  const { user } = useAuth();
  const [action, setAction] = useState<RequirementAction | null>(null);
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [linkedRequirements, setLinkedRequirements] = useState<Requirement[]>([]);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);

  const [form, setForm] = useState({ title: "", description: "", actionTypeId: "", assigneeId: "", dueDate: "" });
  const [saveError, setSaveError] = useState<string | null>(null);

  async function reload() {
    if (!projectId || !actionId) return;
    const [a, types, comm, fls] = await Promise.all([
      api.get<RequirementAction>(`/api/v1/projects/${projectId}/actions/${actionId}`),
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/actions/${actionId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/actions/${actionId}/files`),
    ]);
    setAction(a);
    setActionTypes(types);
    setComments(comm);
    setFiles(fls);
    setForm({
      title: a.title, description: a.description, actionTypeId: a.action_type_id,
      assigneeId: a.assignee_id ?? "", dueDate: a.due_date ?? "",
    });

    // Every requirement in the project is fetched and filtered client-side
    // against `/requirements/{id}/actions` per requirement — mirrors how
    // `RequirementDetailPage.tsx` fetches the project's full action list
    // for its own "link existing" picker (no bulk "which requirements link
    // this action" endpoint exists, so this walks the small reverse set
    // instead of adding one for a single detail page).
    const allRequirements = await api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`);
    const linked = await Promise.all(
      allRequirements.map(async (r) => {
        const acts = await api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/requirements/${r.id}/actions`);
        return acts.some((la) => la.id === actionId) ? r : null;
      })
    );
    setLinkedRequirements(linked.filter((r): r is Requirement => r !== null));
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, actionId]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<{ organization_id: string }>(`/api/v1/projects/${projectId}`);
        setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`));
      } catch {
        // No org role reachable — the assignee select below simply has
        // nothing to offer besides "Unassigned"; not fatal to the page.
      }
    })();
  }, [projectId]);

  async function save() {
    setSaveError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}/actions/${actionId}`, {
        title: form.title,
        description: form.description,
        action_type_id: form.actionTypeId,
        assignee_id: form.assigneeId || null,
        due_date: form.dueDate || null,
      });
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function setOutcome(outcome: RequirementActionOutcome) {
    setSaveError(null);
    try {
      await api.patch(`/api/v1/projects/${projectId}/actions/${actionId}`, {
        title: form.title,
        description: form.description,
        action_type_id: form.actionTypeId,
        assignee_id: form.assigneeId || null,
        due_date: form.dueDate || null,
        outcome_status: outcome,
      });
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
    if (!window.confirm(strings.actions.archiveConfirm)) return;
    await api.post(`/api/v1/projects/${projectId}/actions/${actionId}/archive`);
    reload();
  }

  async function uploadFile(file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/actions/${actionId}/files`, file);
    reload();
  }

  async function removeFile(fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/actions/${actionId}/files/${fileId}`);
    reload();
  }

  async function postComment(body: string): Promise<Comment> {
    const comment = await api.post<Comment>(`/api/v1/projects/${projectId}/actions/${actionId}/comments`, { body });
    reload();
    return comment;
  }

  async function editComment(commentId: string, body: string) {
    await api.patch(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}`, { body });
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/files`, file);
    reload();
  }

  async function removeCommentAttachment(commentId: string, fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/files/${fileId}`);
    reload();
  }

  if (!action) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          {action.unique_code} — {action.title}
        </h1>
        {!action.is_archived && (
          <button className="btn btn-danger" onClick={archive}>
            <Archive size={14} /> {strings.actions.archiveAction}
          </button>
        )}
      </div>

      <div className="side-grid">
        <div className="stack">
          <div className="card stack">
            {action.is_archived && <div className="badge" style={{ alignSelf: "flex-start" }}>{strings.actions.archived}</div>}
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.name}
              <input
                className="input" value={form.title} disabled={action.is_archived}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.description}
              <textarea
                className="input" rows={3} value={form.description} disabled={action.is_archived}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </label>
            <div className="row">
              <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
                {strings.actions.actionType}
                {/* Explicit aria-label — see the equivalent select on
                    RequirementDetailPage.tsx for why a label-wrapped
                    <select>'s ARIA name otherwise folds in its own option
                    text too. */}
                <select
                  className="input" aria-label={strings.actions.actionType}
                  value={form.actionTypeId} disabled={action.is_archived}
                  onChange={(e) => setForm((f) => ({ ...f, actionTypeId: e.target.value }))}
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
                  value={form.assigneeId} disabled={action.is_archived}
                  onChange={(e) => setForm((f) => ({ ...f, assigneeId: e.target.value }))}
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
                <input
                  className="input" type="date" value={form.dueDate} disabled={action.is_archived}
                  onChange={(e) => setForm((f) => ({ ...f, dueDate: e.target.value }))}
                />
              </label>
            </div>
            {saveError && <div style={{ color: "var(--color-danger)" }}>{saveError}</div>}
            {!action.is_archived && (
              <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
                {strings.common.save}
              </button>
            )}
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.outcome}
              {/* Explicit aria-label, same reasoning as the type/assignee
                  selects above. */}
              <select
                className="input" aria-label={strings.actions.outcome}
                value={action.outcome_status} disabled={action.is_archived}
                onChange={(e) => setOutcome(e.target.value as RequirementActionOutcome)}
              >
                {(["pending", "completed", "failed"] as RequirementActionOutcome[]).map((o) => (
                  <option key={o} value={o}>
                    {REQUIREMENT_ACTION_OUTCOME_LABEL[o]}
                  </option>
                ))}
              </select>
            </label>
            {action.completed_at && (
              <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.actions.completedAt}: {new Date(action.completed_at).toLocaleString()}
              </span>
            )}
          </div>

          <div className="card stack">
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.actions.linkedRequirements}</h2>
            {linkedRequirements.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>{strings.actions.noLinkedRequirements}</p>
            ) : (
              linkedRequirements.map((r) => (
                <div key={r.id}>
                  <Link to={`/projects/${projectId}/requirements/${r.id}`}>
                    {r.unique_code} — {r.name}
                  </Link>
                </div>
              ))
            )}
          </div>

          <div className="card stack">
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.attachments}</h2>
            <FileAttachmentList files={files} onUpload={uploadFile} onRemove={removeFile} />
          </div>

          <div className="card stack">
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.discussion}</h2>
            <CommentThread
              comments={comments}
              onPost={postComment}
              onToggleReaction={toggleReaction}
              onUploadAttachment={uploadCommentAttachment}
              onRemoveAttachment={removeCommentAttachment}
              onEdit={editComment}
              currentUserId={user?.id}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
