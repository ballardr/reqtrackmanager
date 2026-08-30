import { MessageSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  ChangeableRequirementField,
  ChangeEntry,
  ChangeRequest,
  ChangeRequestTask,
  ChangeRequestVoteChoice,
  ChangeRequestVoteTally,
  Comment,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementAction,
} from "../api/types";
import { CHANGE_REQUEST_STATUS_LABEL, CHANGEABLE_FIELD_LABEL, REQUIREMENT_LEVEL_LABEL } from "../api/types";
import { ActivityPanel } from "../components/ActivityPanel";
import { CommentThread } from "../components/CommentThread";
import { Modal } from "../components/Modal";
import { Spinner } from "../components/Spinner";
import { SubscribeButton } from "../components/SubscribeButton";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";

/** Change request detail: submit/withdraw/decide and its discussion thread (C-R-01).
 *
 * A MODIFY_REQUIREMENT change request only shows the fields it actually
 * proposes to change (`cr.changed_fields`) — a field not listed there was
 * never touched, so its `proposed_*` value (usually null) isn't rendered
 * at all, rather than showing a misleading "no change" line for every
 * possible field.
 */
export function ChangeRequestDetailPage() {
  const strings = useStrings();
  const { projectId, crId } = useParams<{ projectId: string; crId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const myRoles = useMyProjectRoles(projectId);
  const canDecide = myRoles.includes("project_manager");
  const canManageTasks = canDecide || myRoles.includes("project_administrator");
  const canVote = myRoles.includes("stakeholder") || canDecide;
  const [cr, setCr] = useState<ChangeRequest | null>(null);
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [decisionNote, setDecisionNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [activity, setActivity] = useState<ChangeEntry[]>([]);
  const [tasks, setTasks] = useState<ChangeRequestTask[]>([]);
  const [newTaskDescription, setNewTaskDescription] = useState("");
  const [tally, setTally] = useState<ChangeRequestVoteTally | null>(null);
  const [voteComment, setVoteComment] = useState("");
  const [showVoteComments, setShowVoteComments] = useState(false);
  // ADD_ACTION-only (item 514) — the action type list to resolve
  // `proposed_action_type_id` to a name, and (link-existing mode only) the
  // action being linked, so a reviewer can see what they're actually
  // approving rather than a bare id.
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [linkedActionPreview, setLinkedActionPreview] = useState<RequirementAction | null>(null);

  async function reload() {
    if (!projectId || !crId) return;
    const [crData, commentData, stageData, activityData, taskData, voteData] = await Promise.all([
      api.get<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests/${crId}`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/activity`),
      api.get<ChangeRequestTask[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks`),
      api.get<ChangeRequestVoteTally>(`/api/v1/projects/${projectId}/change-requests/${crId}/votes`),
    ]);
    setCr(crData);
    setComments(commentData);
    setStages(stageData);
    setActivity(activityData);
    setTasks(taskData);
    setTally(voteData);
    if (crData.requirement_id) {
      setRequirement(await api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${crData.requirement_id}`));
    } else {
      setRequirement(null);
    }
    if (crData.kind === "add_action") {
      setActionTypes(await api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`));
      setLinkedActionPreview(
        crData.proposed_action_link_id
          ? await api.get<RequirementAction>(`/api/v1/projects/${projectId}/actions/${crData.proposed_action_link_id}`)
          : null
      );
    } else {
      setActionTypes([]);
      setLinkedActionPreview(null);
    }
    try {
      const proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
      setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`));
    } catch {
      // No org role at all (rare) — reviewer names just fall back to raw ids.
    }
  }

  async function addTask() {
    if (!newTaskDescription.trim()) return;
    await api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks`, { description: newTaskDescription });
    setNewTaskDescription("");
    reload();
  }

  async function toggleTaskDone(task: ChangeRequestTask) {
    await api.patch(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks/${task.id}`, { is_done: !task.is_done });
    reload();
  }

  async function castVote(vote: ChangeRequestVoteChoice) {
    await api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/votes`, { vote, comment: voteComment || null });
    reload();
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function userDisplayName(userId: string | null) {
    if (!userId) return strings.reviews.unassigned;
    return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
  }

  function actionTypeName(id: string | null) {
    return actionTypes.find((t) => t.id === id)?.name ?? "—";
  }

  function targetLabel(): string {
    if (cr?.proposed_target_stage_id) return stageName(cr.proposed_target_stage_id);
    if (requirement) return stageName(requirement.target_stage_id);
    return strings.changeRequests.defaultTarget;
  }

  function levelLabel(): string {
    if (cr?.proposed_level) return REQUIREMENT_LEVEL_LABEL[cr.proposed_level];
    if (requirement) return REQUIREMENT_LEVEL_LABEL[requirement.level];
    return REQUIREMENT_LEVEL_LABEL.requirement;
  }

  function proposedValueDisplay(field: ChangeableRequirementField): string {
    if (!cr) return "";
    switch (field) {
      case "name":
        return cr.proposed_name ?? "";
      case "reasoning":
        return cr.proposed_reasoning ?? "";
      case "clarification":
        return cr.proposed_clarification ?? "";
      case "description":
        return cr.proposed_description ?? "";
      case "target_stage_id":
        return targetLabel();
      case "level":
        return levelLabel();
      case "review_date":
        return cr.proposed_review_date ?? strings.requirements.reviewNone;
      case "review_lead_days":
        return cr.proposed_review_lead_days != null ? String(cr.proposed_review_lead_days) : "";
      case "reviewer_id":
        return userDisplayName(cr.proposed_reviewer_id);
      case "custom_fields":
        return Object.keys(cr.custom_fields).length > 0 ? JSON.stringify(cr.custom_fields) : "";
      case "attachments":
        return `${cr.proposed_attachment_file_ids.length} file(s)`;
      default:
        return "";
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, crId]);

  async function act(action: () => Promise<unknown>, successMessage?: string) {
    setActionError(null);
    try {
      await action();
      reload();
      if (successMessage) showToast(successMessage);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function postComment(body: string): Promise<Comment> {
    const comment = await api.post<Comment>(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`, { body });
    reload();
    return comment;
  }

  async function editComment(commentId: string, body: string) {
    await api.patch(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}`, { body });
    reload();
  }

  async function removeCommentAttachment(commentId: string, fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/files/${fileId}`);
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/files`, file);
    reload();
  }

  async function toggleSubscription() {
    if (!cr) return;
    if (cr.is_subscribed) {
      await api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`);
    }
    reload();
  }

  if (!cr) return <Spinner />;

  const title = cr.proposed_name ?? requirement?.name ?? cr.id;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{title}</h1>
        <SubscribeButton subscribed={cr.is_subscribed} onToggle={toggleSubscription} />
      </div>
      <div className="side-grid">
      <div className="stack">
      <div className="card stack">
        <div className="row">
          <span className="badge">{CHANGE_REQUEST_STATUS_LABEL[cr.status]}</span>
          {cr.kind !== "add_action" && (
            <>
              <span className="badge">Target: {targetLabel()}</span>
              <span className="badge">Level: {levelLabel()}</span>
            </>
          )}
        </div>

        {cr.kind === "modify_requirement" ? (
          <div className="stack" style={{ gap: "0.5rem" }}>
            <strong>{strings.changeRequests.fieldsToChange}</strong>
            {cr.changed_fields.map((field) => (
              <div key={field}>
                <span className="text-muted">{CHANGEABLE_FIELD_LABEL[field]}:</span> {proposedValueDisplay(field)}
              </div>
            ))}
          </div>
        ) : cr.kind === "add_action" ? (
          <div className="stack" style={{ gap: "0.5rem" }}>
            <strong>
              {cr.proposed_action_link_id ? strings.changeRequests.proposedLinkAction : strings.changeRequests.proposedAddAction}
            </strong>
            {cr.proposed_action_link_id ? (
              <p>
                {linkedActionPreview
                  ? `${linkedActionPreview.unique_code} — ${linkedActionPreview.title}`
                  : cr.proposed_action_link_id}
              </p>
            ) : (
              <>
                <p>
                  <strong>{strings.actions.name}:</strong> {cr.proposed_action_title}
                </p>
                {cr.proposed_action_description && (
                  <p>
                    <strong>{strings.actions.description}:</strong> {cr.proposed_action_description}
                  </p>
                )}
                <p>
                  <strong>{strings.actions.actionType}:</strong> {actionTypeName(cr.proposed_action_type_id)}
                </p>
                <p>
                  <strong>{strings.actions.assignee}:</strong> {userDisplayName(cr.proposed_action_assignee_id)}
                </p>
                {cr.proposed_action_due_date && (
                  <p>
                    <strong>{strings.actions.dueDate}:</strong> {cr.proposed_action_due_date}
                  </p>
                )}
              </>
            )}
          </div>
        ) : (
          <div className="stack" style={{ gap: "0.5rem" }}>
            <p>
              <strong>{strings.requirements.reasoning}:</strong> {cr.proposed_reasoning}
            </p>
            {cr.proposed_clarification && (
              <p>
                <strong>{strings.requirements.clarification}:</strong> {cr.proposed_clarification}
              </p>
            )}
            {cr.proposed_description && (
              <p>
                <strong>{strings.requirements.description}:</strong> {cr.proposed_description}
              </p>
            )}
          </div>
        )}

        <p>
          <strong>{strings.changeRequests.reason}:</strong> {cr.reason}
        </p>
        {cr.decision_note && (
          <p>
            <strong>{strings.changeRequests.decisionNote}:</strong> {cr.decision_note}
          </p>
        )}
        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
        <div className="row">
          {cr.status === "draft" && (
            <button
              className="btn btn-primary"
              onClick={() =>
                act(
                  () => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/submit`),
                  strings.changeRequests.submittedToast
                )
              }
            >
              {strings.changeRequests.submit}
            </button>
          )}
          {(cr.status === "draft" || cr.status === "submitted") && (
            <button
              className="btn"
              onClick={() =>
                act(
                  () => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/withdraw`),
                  strings.changeRequests.withdrawnToast
                )
              }
            >
              {strings.changeRequests.withdraw}
            </button>
          )}
          {(cr.status === "submitted" || cr.status === "in_review") && canDecide && (
            <>
              <input
                className="input"
                style={{ maxWidth: 240 }}
                placeholder={strings.changeRequests.decisionNote}
                value={decisionNote}
                onChange={(e) => setDecisionNote(e.target.value)}
              />
              <button
                className="btn btn-primary"
                onClick={() =>
                  act(
                    () =>
                      api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
                        approve: true,
                        note: decisionNote,
                      }),
                    strings.changeRequests.approvedToast
                  )
                }
              >
                {strings.changeRequests.approve}
              </button>
              {/* C-G-11: an explicit, opt-in second action — shown only for
                  a MODIFY_REQUIREMENT change request whose target is
                  currently completed, since only then is there a
                  meaningful choice between "keep completion" (plain
                  Approve, above) and "this change is substantial enough to
                  need re-verifying" (this button). Every other case keeps
                  the single Approve button unchanged. */}
              {cr.kind === "modify_requirement" && requirement?.is_completed && (
                <button
                  className="btn"
                  onClick={() =>
                    act(
                      () =>
                        api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
                          approve: true,
                          note: decisionNote,
                          clear_completion: true,
                        }),
                      strings.changeRequests.approvedToast
                    )
                  }
                >
                  {strings.changeRequests.approveAndClearCompletion}
                </button>
              )}
              <button
                className="btn btn-danger"
                onClick={() =>
                  act(
                    () =>
                      api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
                        approve: false,
                        note: decisionNote,
                      }),
                    strings.changeRequests.rejectedToast
                  )
                }
              >
                {strings.changeRequests.reject}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.changeRequests.tasks}</h2>
        {tasks.map((task) => (
          <label key={task.id} className="row" style={{ gap: "0.5rem" }}>
            <input
              type="checkbox" checked={task.is_done}
              disabled={!(canManageTasks || task.assignee_id === user?.id)}
              onChange={() => toggleTaskDone(task)}
            />
            <span style={{ textDecoration: task.is_done ? "line-through" : "none" }}>{task.description}</span>
            {task.due_date && <span className="text-muted">({task.due_date})</span>}
          </label>
        ))}
        {canManageTasks && (
          <div className="row">
            <input
              className="input" placeholder={strings.changeRequests.taskDescription}
              value={newTaskDescription} onChange={(e) => setNewTaskDescription(e.target.value)}
            />
            <button className="btn" onClick={addTask}>
              {strings.changeRequests.newTask}
            </button>
          </div>
        )}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.changeRequests.votes}</h2>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.changeRequests.votingAdvisoryNotice}</p>
        {tally && (
          <div className="row">
            <span className="badge">
              {tally.approve_count} {strings.changeRequests.voteApproveCount}
            </span>
            <span className="badge">
              {tally.reject_count} {strings.changeRequests.voteRejectCount}
            </span>
            {tally.votes.some((v) => v.comment) && (
              <button className="btn" onClick={() => setShowVoteComments(true)}>
                <MessageSquare size={14} /> {strings.changeRequests.viewComments}
              </button>
            )}
          </div>
        )}
        {canVote && (cr.status === "submitted" || cr.status === "in_review") && (
          <div className="row">
            <input
              className="input" placeholder={strings.changeRequests.voteComment}
              value={voteComment} onChange={(e) => setVoteComment(e.target.value)}
            />
            <button className="btn btn-primary" onClick={() => castVote("approve")}>
              {strings.changeRequests.voteApprove}
            </button>
            <button className="btn btn-danger" onClick={() => castVote("reject")}>
              {strings.changeRequests.voteReject}
            </button>
          </div>
        )}
      </div>

      {showVoteComments && tally && (
        <Modal title={strings.changeRequests.voteComments} onClose={() => setShowVoteComments(false)}>
          <div className="stack">
            {tally.votes.filter((v) => v.comment).length === 0 && (
              <p className="text-muted">{strings.changeRequests.noVoteComments}</p>
            )}
            {tally.votes.filter((v) => v.comment).map((v) => (
              <div key={v.id} className="card stack" style={{ gap: "0.35rem" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 600 }}>{userDisplayName(v.user_id)}</span>
                  <span className="badge">
                    {v.vote === "approve" ? strings.changeRequests.voteApproveCount : strings.changeRequests.voteRejectCount}
                  </span>
                </div>
                <div>{v.comment}</div>
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                  {new Date(v.voted_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </Modal>
      )}

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

      <ActivityPanel entries={activity} />
      </div>
    </div>
  );
}
