import { useMutation } from "../hooks/useMutation";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  Comment,
  FileAsset,
  OrgUser,
  PrincipalRef,
  RequirementAction,
  RequirementActionOutcome,
} from "../api/types";
import { principalRef, REQUIREMENT_ACTION_OUTCOME_LABEL, savedPrincipalDisplay } from "../api/types";
import { ArtefactLinksPanel } from "../components/ArtefactLinksPanel";
import { RecordActivity } from "../components/RecordActivity";
import { CommentThread } from "../components/CommentThread";
import { DetailLayout } from "../components/DetailLayout";
import { FileAttachmentList } from "../components/FileAttachmentList";
import { PrincipalBadge } from "../components/PrincipalBadge";
import { Spinner } from "../components/Spinner";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Badge } from "../components/Badge";
import { RecordHeader } from "../components/RecordHeader";
import { useConfirmedAction } from "../components/useConfirmedAction";
import { ActionFields } from "../components/ActionFields";
import { LabeledSelect } from "../components/LabeledSelect";
import { useLoadOnChange } from "../hooks/useLoadOnChange";

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
  const run = useMutation();
  const strings = useStrings();
  const { projectId, actionId } = useParams<{ projectId: string; actionId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const [action, setAction] = useState<RequirementAction | null>(null);
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);

  const [form, setForm] = useState<{
    title: string; description: string; actionTypeId: string; assignee: PrincipalRef | null; dueDate: string;
  }>({ title: "", description: "", actionTypeId: "", assignee: null, dueDate: "" });
  const [saveError, setSaveError] = useState<string | null>(null);
  // Guards `form` against `reload()` — called after every unrelated
  // mutation on this page (posting a comment, uploading a file, linking a
  // requirement, ...) and not awaited by its callers, so it can still be
  // mid-flight when the user edits and saves this form right after
  // triggering one of those other actions, clobbering the edit back to
  // its last-saved value before Save is even clicked. Same real,
  // CI-reproducible race as OrgAdminPage.tsx's advancedDirtyRef — see its
  // own comment and docs/decisions.md. Set by every field's onChange via
  // `updateForm` below, cleared once `save()` succeeds.
  const formDirtyRef = useRef(false);

  function updateForm(updater: (f: typeof form) => typeof form) {
    formDirtyRef.current = true;
    setForm(updater);
  }

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
    if (!formDirtyRef.current) {
      setForm({
        title: a.title, description: a.description, actionTypeId: a.action_type_id,
        assignee: principalRef(a.assignee), dueDate: a.due_date ?? "",
      });
    }
  }

  useLoadOnChange(reload, [projectId, actionId]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<{ organization_id: string }>(`/api/v1/projects/${projectId}`);
        setOrganizationId(project.organization_id);
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
        assignee: form.assignee,
        due_date: form.dueDate || null,
      });
      formDirtyRef.current = false;
      showToast(strings.mutation.success("action", strings.mutation.past.save));
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
        assignee: form.assignee,
        due_date: form.dueDate || null,
        outcome_status: outcome,
      });
      formDirtyRef.current = false;
      showToast(strings.mutation.success("outcome", strings.mutation.past.update));
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
    try {
      await api.post(`/api/v1/projects/${projectId}/actions/${actionId}/archive`);
      showToast(strings.actions.archivedToast);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Restore: no `ConfirmDialog` (unlike archive above) — mirrors
  // `ProjectAdminPage.tsx`'s existing unarchive button, which also fires
  // immediately, since restoring is reversible again (archive it right
  // back) rather than a Tier-1-confirmed action.
  async function restore() {
    try {
      await api.post(`/api/v1/projects/${projectId}/actions/${actionId}/unarchive`);
      showToast(strings.actions.restoredToast);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function uploadFile(file: File) {
    if (!(await run(() => api.postFile(`/api/v1/projects/${projectId}/actions/${actionId}/files`, file), "upload", "file"))) return;
    reload();
  }

  async function removeFile(fileId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/actions/${actionId}/files/${fileId}`), "remove", "file"))) return;
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
    const url = `/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/reaction`;
    if (!(await run(() => (reacted ? api.delete(url) : api.put(url)), { failure: "Could not update the reaction." }))) return;
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/files`, file);
    reload();
  }

  async function removeCommentAttachment(commentId: string, fileId: string) {
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/actions/${actionId}/comments/${commentId}/files/${fileId}`), "remove", "comment attachment"))) return;
    reload();
  }

  const archiveAction = useConfirmedAction(
    action && {
      label: action.is_archived ? strings.actions.restoreAction : strings.actions.archiveAction,
      danger: !action.is_archived,
      immediate: action.is_archived,
      title: strings.actions.archiveTitle,
      message: strings.actions.archiveConfirm,
      confirmLabel: strings.actions.archiveAction,
      onConfirm: action.is_archived ? restore : archive,
    },
  );

  if (!action) return <Spinner />;

  return (
    <DetailLayout
      activity={projectId && actionId ? <RecordActivity projectId={projectId} artefactType="requirement_action" artefactId={actionId} /> : undefined}
      contained={false}
      aside={
        projectId && actionId ? (
          <ArtefactLinksPanel projectId={projectId} artefactType="requirement_action" artefactId={actionId} />
        ) : null
      }
    >
      <RecordHeader
        recordLabel={strings.actions.recordLabel}
        title={action.title}
        code={action.unique_code}
        badges={action.is_archived ? <Badge>{strings.actions.archived}</Badge> : undefined}
        actions={[archiveAction.item]}
      />
      {archiveAction.dialog}

      <div className="stack">
          <div className="card stack">
            <ActionFields
              values={form}
              onChange={(v) => updateForm(() => v)}
              actionTypes={actionTypes}
              orgUsers={orgUsers}
              organizationId={organizationId}
              projectId={projectId}
              disabled={action.is_archived}
              assigneeDisplay={savedPrincipalDisplay(form.assignee, action.assignee)}
              archivedAssignee={<PrincipalBadge principal={action.assignee} placeholder={strings.reviews.unassigned} />}
            />
            {saveError && <div style={{ color: "var(--color-danger)" }}>{saveError}</div>}
            {!action.is_archived && (
              <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
                {strings.common.save}
              </button>
            )}
            <LabeledSelect
              label={strings.actions.outcome}
              value={action.outcome_status}
              onChange={(next) => setOutcome(next as RequirementActionOutcome)}
              options={(["pending", "completed", "failed"] as RequirementActionOutcome[]).map((o) => ({
                value: o, label: REQUIREMENT_ACTION_OUTCOME_LABEL[o],
              }))}
              placeholder={null}
              disabled={action.is_archived}
            />
            {action.completed_at && (
              <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.actions.completedAt}: {new Date(action.completed_at).toLocaleString()}
              </span>
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
    </DetailLayout>
  );
}
