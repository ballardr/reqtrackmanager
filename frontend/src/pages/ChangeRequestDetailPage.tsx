import { useApprovalStatus } from "../hooks/useApprovalStatus";
import { useMutation } from "../hooks/useMutation";
import { Bell, BellOff, MessageSquare } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  ChangeableRequirementField,
  ChangeRequest,
  ChangeRequestTask,
  ChangeRequestVoteChoice,
  ChangeRequestVoteTally,
  Comment,
  OrgUser,
  PrincipalRef,
  Project,
  ProjectStage,
  Requirement,
  RequirementAction,
  RequirementLink,
} from "../api/types";
import {
  CHANGE_REQUEST_STATUS_LABEL,
  CHANGEABLE_FIELD_LABEL,
  principalText,
  REQUIREMENT_LEVEL_LABEL,
} from "../api/types";
import { ArtefactLinksPanel } from "../components/ArtefactLinksPanel";
import { DetailLayout } from "../components/DetailLayout";
import { RecordActivity } from "../components/RecordActivity";
import { RecordTags } from "../components/RecordTags";
import { ApproveChangeRequestDialog } from "../components/ApproveChangeRequestDialog";
import { CommentThread } from "../components/CommentThread";
import { PrincipalBadge } from "../components/PrincipalBadge";
import { useWatchingTab } from "../hooks/useWatchingTab";
import { PrincipalFormField } from "../components/PrincipalFormField";
import { Modal } from "../components/Modal";
import { ProposedLinksSection } from "../components/ProposedLinksSection";
import { Spinner } from "../components/Spinner";
import type { LifecyclePromote } from "../components/LifecycleTrack";
import { lifecycleSteps } from "../components/lifecycleSteps";
import { RecordHeader } from "../components/RecordHeader";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { Badge } from "../components/Badge";
import { TextField } from "../components/FormFields";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { DetailCard } from "../components/DetailCard";
import { MarkdownView } from "../components/MarkdownView";
import { markdownPlainText } from "../utils/markdownPlain";

/** Change request detail: submit/withdraw/decide and its discussion thread (C-R-01).
 *
 * A MODIFY_REQUIREMENT request renders only the fields listed in
 * `cr.changed_fields`; an unlisted field has no proposed value to show.
 */
export function ChangeRequestDetailPage() {
  const run = useMutation();
  const strings = useStrings();
  const { projectId, crId } = useParams<{ projectId: string; crId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const myRoles = useMyProjectRoles(projectId);
  const canDecide = myRoles.includes("project_manager");
  const canManageTasks = canDecide || myRoles.includes("project_administrator");
  const canVote = myRoles.includes("stakeholder") || canDecide;
  const [cr, setCr] = useState<ChangeRequest | null>(null);
  const approval = useApprovalStatus(projectId ? { projectId } : null, "change_request", cr?.id, cr?.status);
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [decisionNote, setDecisionNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  // Bumped on every reload so the aside's Links and Activity tabs follow the record.
  const [refreshToken, setRefreshToken] = useState(0);
  const [tasks, setTasks] = useState<ChangeRequestTask[]>([]);
  const [newTaskDescription, setNewTaskDescription] = useState("");
  const [newTaskAssignee, setNewTaskAssignee] = useState<PrincipalRef | null>(null);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  const watchingTab = useWatchingTab({
    recordPath: projectId && crId ? `/api/v1/projects/${projectId}/change-requests/${crId}` : undefined,
    organizationId, projectId, canManage: canManageTasks, refreshKey: cr?.is_subscribed,
  });
  const [tally, setTally] = useState<ChangeRequestVoteTally | null>(null);
  const [voteComment, setVoteComment] = useState("");
  const [showVoteComments, setShowVoteComments] = useState(false);
  // ADD_ACTION/REMOVE_ACTION only: action types resolve `proposed_action_type_id` to a name and
  // the preview shows the linked action (link-existing/remove mode), so a reviewer sees more than an id.
  const [actionTypes, setActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [linkedActionPreview, setLinkedActionPreview] = useState<RequirementAction | null>(null);
  // REMOVE_LINK only: the existing link, server-resolved as on the Links card.
  // Links an add-link, new or modify request proposes arrive resolved on `cr.proposed_links`.
  const [linkPreview, setLinkPreview] = useState<RequirementLink | null>(null);
  // Approving a request that proposes links goes through a dialog where the approver
  // chooses which to merge; `clearCompletion` carries the second approve button.
  const [approving, setApproving] = useState<{ clearCompletion: boolean } | null>(null);

  const [loadError, setLoadError] = useState<string | null>(null);
  async function reload() {
    if (!projectId || !crId) return;
    const [crData, commentData, stageData, taskData, voteData] = await Promise.all([
      api.get<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests/${crId}`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/comments`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeRequestTask[]>(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks`),
      api.get<ChangeRequestVoteTally>(`/api/v1/projects/${projectId}/change-requests/${crId}/votes`),
    ]);
    setCr(crData);
    setComments(commentData);
    setStages(stageData);
    setRefreshToken((t) => t + 1);
    setTasks(taskData);
    setTally(voteData);
    if (crData.requirement_id) {
      setRequirement(await api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${crData.requirement_id}`));
    } else {
      setRequirement(null);
    }
    if (crData.kind === "add_action" || crData.kind === "remove_action") {
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
    if (crData.kind === "remove_link" && crData.requirement_id) {
      const links = await api.get<RequirementLink[]>(
        `/api/v1/projects/${projectId}/requirements/${crData.requirement_id}/links`
      );
      setLinkPreview(links.find((l) => l.id === crData.proposed_link_id) ?? null);
    } else {
      setLinkPreview(null);
    }
    try {
      const proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
      setOrganizationId(proj.organization_id);
      setOrgUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`));
    } catch {
      // No org role at all (rare) — reviewer names just fall back to raw ids.
    }
  }

  async function addTask() {
    if (!newTaskDescription.trim()) return;
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks`, {
      description: newTaskDescription, assignee: newTaskAssignee,
    }), "add", "task"))) return;
    setNewTaskDescription("");
    setNewTaskAssignee(null);
    reload();
  }

  async function toggleTaskDone(task: ChangeRequestTask) {
    if (!(await run(() => api.patch(`/api/v1/projects/${projectId}/change-requests/${crId}/tasks/${task.id}`, { is_done: !task.is_done }), { failure: "Could not toggle task done." }))) return;
    reload();
  }

  async function castVote(vote: ChangeRequestVoteChoice) {
    if (!(await run(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/votes`, { vote, comment: voteComment || null }), "cast", "vote"))) return;
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
        return cr.proposed_reviewer ? principalText(cr.proposed_reviewer) : strings.reviews.unassigned;
      case "custom_fields":
        return Object.keys(cr.custom_fields).length > 0 ? JSON.stringify(cr.custom_fields) : "";
      case "attachments":
        return `${cr.proposed_attachment_file_ids.length} file(s)`;
      default:
        return "";
    }
  }

  // The initial load reports a missing or inaccessible record instead of leaving the spinner up.
  async function loadRecord() {
    try {
      await reload();
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "This change request could not be found, or you do not have access to it."));
    }
  }

  useLoadOnChange(loadRecord, [projectId, crId]);

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

  /** Submits a draft request for a decision. */
  function submit() {
    return act(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/submit`), strings.changeRequests.submittedToast);
  }

  /** Withdraws a draft or submitted request. */
  function withdraw() {
    return act(() => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/withdraw`), strings.changeRequests.withdrawnToast);
  }

  /**
   * Approves the request with the decision note. A request that proposes links opens the dialog where the approver
   * chooses which links to merge.
   *
   * @param clearCompletion Also clears the completion of a completed target requirement so the change is re-verified.
   */
  function approve(clearCompletion: boolean) {
    if (cr && cr.proposed_link_count > 0) {
      setApproving({ clearCompletion });
      return Promise.resolve();
    }
    return act(
      () => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, {
        approve: true, note: decisionNote, ...(clearCompletion ? { clear_completion: true } : {}),
      }),
      strings.changeRequests.approvedToast,
    );
  }

  /** Rejects the request with the decision note. */
  function reject() {
    return act(
      () => api.post(`/api/v1/projects/${projectId}/change-requests/${crId}/decide`, { approve: false, note: decisionNote }),
      strings.changeRequests.rejectedToast,
    );
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
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/files/${fileId}`), "remove", "comment attachment"))) return;
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (!(await run(() => (reacted ? api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`) : api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/reaction`)), { failure: "Could not update the reaction." }))) return;
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/change-requests/${crId}/comments/${commentId}/files`, file);
    reload();
  }

  async function toggleSubscription() {
    if (!cr) return;
    if (!(await run(() => (cr.is_subscribed ? api.delete(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`) : api.put(`/api/v1/projects/${projectId}/change-requests/${crId}/subscription`)), { failure: "Could not update the subscription." }))) return;
    reload();
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (!cr) return <Spinner />;

  // A draft is promoted by submitting it; a submitted or in-review request by approving it (project managers).
  const isDecidable = cr.status === "submitted" || cr.status === "in_review";
  let nextPromotion: LifecyclePromote | undefined;
  if (cr.status === "draft") nextPromotion = { to: "submitted", onPromote: submit };
  else if (isDecidable) {
    nextPromotion = canDecide
      ? approval.approve("approved", () => approve(false))
      : { to: "approved", blockedReason: strings.lifecycle.notPermitted(CHANGE_REQUEST_STATUS_LABEL.approved) };
  }

  const title = cr.proposed_name ?? requirement?.name ?? cr.id;

  return (
    <DetailLayout
      contained={false}
      extraTabs={watchingTab ? [watchingTab] : []}
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="change_request" artefactId={cr.id} refreshToken={refreshToken} /> : undefined}
      aside={projectId ? <ArtefactLinksPanel projectId={projectId} artefactType="change_request" artefactId={cr.id} refreshToken={refreshToken} /> : null}
    >
      <RecordHeader
        recordLabel="Change request"
        back={projectId ? { to: `/projects/${projectId}/change-requests`, label: strings.changeRequests.title } : undefined}
        title={title}
        code={cr.unique_code}
        approval={approval.status}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="change_request" artefactId={cr.id} /> : undefined}
        badges={cr.is_subscribed ? <Badge tone="info">{strings.requirements.subscribed}</Badge> : undefined}
        actions={[
          {
            label: cr.is_subscribed ? strings.requirements.unsubscribe : strings.requirements.subscribe,
            icon: cr.is_subscribed ? <BellOff /> : <Bell />,
            onSelect: toggleSubscription,
          },
          isDecidable && canDecide && cr.kind === "modify_requirement" && requirement?.is_completed && {
            label: strings.changeRequests.approveAndClearCompletion, onSelect: () => approve(true),
          },
          isDecidable && canDecide && { label: strings.changeRequests.reject, danger: true, onSelect: reject },
          (cr.status === "draft" || cr.status === "submitted") && { label: strings.changeRequests.withdraw, onSelect: withdraw },
        ]}
        lifecycle={{
          steps: lifecycleSteps(["draft", "submitted", "in_review", "approved"], CHANGE_REQUEST_STATUS_LABEL, {
            descriptions: strings.changeRequests.stateDescription,
          }),
          current: cr.status,
          offPath: cr.status === "rejected" || cr.status === "withdrawn"
            ? { key: cr.status, label: CHANGE_REQUEST_STATUS_LABEL[cr.status], description: strings.changeRequests.stateDescription[cr.status] }
            : undefined,
          promote: nextPromotion,
        }}
      />
      <DetailCard>
        <div className="row">
          {cr.kind !== "add_action" && cr.kind !== "remove_action" && cr.kind !== "add_link" && cr.kind !== "remove_link" && (
            <>
              <Badge>Target: {targetLabel()}</Badge>
              <Badge>Level: {levelLabel()}</Badge>
            </>
          )}
        </div>

        {cr.kind === "modify_requirement" ? (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            <strong>{strings.changeRequests.fieldsToChange}</strong>
            {cr.changed_fields.map((field) => (
              <div key={field}>
                <span className="text-muted">{CHANGEABLE_FIELD_LABEL[field]}:</span> {proposedValueDisplay(field)}
              </div>
            ))}
          </div>
        ) : cr.kind === "add_action" ? (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
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
                  <div>
                    <strong>{strings.actions.description}:</strong>
                    <MarkdownView text={cr.proposed_action_description} />
                  </div>
                )}
                <p>
                  <strong>{strings.actions.actionType}:</strong> {actionTypeName(cr.proposed_action_type_id)}
                </p>
                <p>
                  <strong>{strings.actions.assignee}:</strong> <PrincipalBadge principal={cr.proposed_action_assignee} placeholder={strings.reviews.unassigned} />
                </p>
                {cr.proposed_action_due_date && (
                  <p>
                    <strong>{strings.actions.dueDate}:</strong> {cr.proposed_action_due_date}
                  </p>
                )}
              </>
            )}
          </div>
        ) : cr.kind === "remove_action" ? (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            <strong>{strings.changeRequests.proposedRemoveAction}</strong>
            <p>
              {linkedActionPreview
                ? `${linkedActionPreview.unique_code} — ${linkedActionPreview.title}`
                : cr.proposed_action_link_id}
            </p>
          </div>
        ) : cr.kind === "add_link" ? (
          <ProposedLinksSection links={cr.proposed_links} title={strings.changeRequests.proposedAddLink} />
        ) : cr.kind === "remove_link" ? (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            <strong>{strings.changeRequests.proposedRemoveLink}</strong>
            <p>
              {linkPreview
                ? `${linkPreview.display_name} — ${linkPreview.other_requirement_unique_code} — ${linkPreview.other_requirement_name}`
                : cr.proposed_link_id}
            </p>
          </div>
        ) : (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            <div>
              <strong>{strings.requirements.reasoning}:</strong> <MarkdownView math text={cr.proposed_reasoning ?? ""} />
            </div>
            {cr.proposed_clarification && (
              <div>
                <strong>{strings.requirements.clarification}:</strong> <MarkdownView math text={cr.proposed_clarification} />
              </div>
            )}
            {cr.proposed_description && (
              <div>
                <strong>{strings.requirements.description}:</strong> <MarkdownView math text={cr.proposed_description} />
              </div>
            )}
          </div>
        )}

        {cr.kind !== "add_link" && cr.proposed_links.length > 0 && <ProposedLinksSection links={cr.proposed_links} />}

        <div>
          <strong>{strings.changeRequests.reason}:</strong> <MarkdownView math text={cr.reason} />
        </div>
        {cr.decision_note && (
          <div>
            <strong>{strings.changeRequests.decisionNote}:</strong> <MarkdownView text={cr.decision_note} />
          </div>
        )}
        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
        {isDecidable && canDecide && (
          <TextField helpNotNeeded
            label={strings.changeRequests.decisionNote}
            value={decisionNote}
            onChange={setDecisionNote}
          />
        )}
      </DetailCard>

      <DetailCard heading={strings.changeRequests.tasks}>
        {tasks.map((task) => (
          <label key={task.id} className="row" style={{ gap: "var(--space-3)" }}>
            <input
              type="checkbox" checked={task.is_done}
              disabled={!(canManageTasks || task.can_mark_done)}
              onChange={() => toggleTaskDone(task)}
            />
            <span style={{ textDecoration: task.is_done ? "line-through" : "none" }}>{markdownPlainText(task.description)}</span>
            {task.assignee && <PrincipalBadge principal={task.assignee} />}
            {task.due_date && <span className="text-muted">({task.due_date})</span>}
          </label>
        ))}
        {canManageTasks && (
          <div className="row" style={{ alignItems: "flex-end" }}>
            <TextField helpNotNeeded
              label={strings.changeRequests.taskDescription} placeholder={strings.changeRequests.taskDescription}
              value={newTaskDescription} onChange={setNewTaskDescription}
            />
            <PrincipalFormField helpNotNeeded
              label={strings.actions.assignee} orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
              value={newTaskAssignee} onChange={setNewTaskAssignee} ariaLabel={`${strings.changeRequests.newTask} ${strings.actions.assignee}`}
            />
            <button className="btn" onClick={addTask}>
              {strings.changeRequests.newTask}
            </button>
          </div>
        )}
      </DetailCard>

      <DetailCard heading={strings.changeRequests.votes}>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.changeRequests.votingAdvisoryNotice}</p>
        {tally && (
          <div className="row">
            <Badge>
              {tally.approve_count} {strings.changeRequests.voteApproveCount}
            </Badge>
            <Badge>
              {tally.reject_count} {strings.changeRequests.voteRejectCount}
            </Badge>
            {tally.votes.some((v) => v.comment) && (
              <button className="btn" onClick={() => setShowVoteComments(true)}>
                <MessageSquare /> {strings.changeRequests.viewComments}
              </button>
            )}
          </div>
        )}
        {canVote && (cr.status === "submitted" || cr.status === "in_review") && (
          <div className="row" style={{ alignItems: "flex-end" }}>
            <TextField helpNotNeeded
              label={strings.changeRequests.voteComment} placeholder={strings.changeRequests.voteComment}
              value={voteComment} onChange={setVoteComment}
            />
            <button className="btn btn-primary" onClick={() => castVote("approve")}>
              {strings.changeRequests.voteApprove}
            </button>
            <button className="btn btn-danger" onClick={() => castVote("reject")}>
              {strings.changeRequests.voteReject}
            </button>
          </div>
        )}
      </DetailCard>

      {approving && projectId && crId && (
        <ApproveChangeRequestDialog
          projectId={projectId}
          crId={crId}
          kind={cr.kind}
          note={decisionNote}
          clearCompletion={approving.clearCompletion}
          onApproved={() => {
            setApproving(null);
            reload();
            showToast(strings.changeRequests.approvedToast);
          }}
          onClose={() => setApproving(null)}
        />
      )}

      {showVoteComments && tally && (
        <Modal title={strings.changeRequests.voteComments} onClose={() => setShowVoteComments(false)}>
          <div className="stack">
            {tally.votes.filter((v) => v.comment).length === 0 && (
              <p className="text-muted">{strings.changeRequests.noVoteComments}</p>
            )}
            {tally.votes.filter((v) => v.comment).map((v) => (
              <div key={v.id} className="card stack" style={{ gap: "var(--space-2)" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 600 }}>{userDisplayName(v.user_id)}</span>
                  <Badge>
                    {v.vote === "approve" ? strings.changeRequests.voteApproveCount : strings.changeRequests.voteRejectCount}
                  </Badge>
                </div>
                <MarkdownView text={v.comment ?? ""} />
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                  {new Date(v.voted_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </Modal>
      )}

      <DetailCard heading={strings.requirements.discussion} rank="discussion">
        <CommentThread
          comments={comments}
          onPost={postComment}
          onToggleReaction={toggleReaction}
          onUploadAttachment={uploadCommentAttachment}
          onRemoveAttachment={removeCommentAttachment}
          onEdit={editComment}
          currentUserId={user?.id}
        />
      </DetailCard>
    </DetailLayout>
  );
}
