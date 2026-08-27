import { Activity as ActivityIcon, ArchiveRestore, CheckCircle, FolderOpen, GitPullRequest, Plus, Table as TableIcon, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  ChangeEntry,
  Comment,
  CustomFieldDefinition,
  FileAsset,
  LinkTypeDefinition,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementAction,
  RequirementLevel,
  RequirementLink,
  RequirementReviewOutcome,
  RequirementVersionEntry,
} from "../api/types";
import { REQUIREMENT_ACTION_OUTCOME_LABEL, REQUIREMENT_LEVEL_LABEL, REQUIREMENT_STATUS_LABEL } from "../api/types";
import { ActivityPanel } from "../components/ActivityPanel";
import { CommentThread } from "../components/CommentThread";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FileAttachmentList } from "../components/FileAttachmentList";
import { Modal } from "../components/Modal";
import { Popover } from "../components/Popover";
import { ResourcePickerModal } from "../components/ResourcePickerModal";
import { Spinner } from "../components/Spinner";
import { SubscribeButton } from "../components/SubscribeButton";
import { useAuth } from "../context/AuthContext";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useUiPreference } from "../hooks/useUiPreference";

/**
 * Requirement detail view: direct editing while unlocked, a discussion
 * thread (C-R-01), a change log that intentionally excludes discussion
 * comments (C-A-09 clarification), a Links card for typed bidirectional
 * traceability links to other requirements (C-G-09 — server-resolved
 * direction/display name, so this page never has to guess which of a link
 * type's forward/reverse names applies), and an Actions card for
 * requirement actions (review/test/etc.) linked via `RequirementActionLink`.
 * Links aren't gated by `is_locked` — they're metadata about the
 * requirement, not its own governed content. Actions *are* now gated
 * (2026-08 UX audit roadmap item 514, a deliberate reversal of this page's
 * own former "actions are metadata too" stance): once locked, adding or
 * linking one requires an `ADD_ACTION` change request instead of the
 * direct endpoint, the same change-request-only-once-locked rule the
 * requirement's own fields already follow (`services.requirements.
 * LOCKED_STATUSES`) — see `docs/decisions.md` for the reasoning.
 */
export function RequirementDetailPage() {
  const strings = useStrings();
  const { projectId, requirementId } = useParams<{ projectId: string; requirementId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();
  const myRoles = useMyProjectRoles(projectId);
  const orgLabelCap = useOrgLabelCapitalized();
  const canArchive = myRoles.includes("project_manager") || myRoles.includes("project_administrator");
  // Narrower than canArchive: C-U-03's clarification calls out requirement
  // approval as a Project Manager privilege specifically, not shared with
  // Administrator — the same split `decide_change_request` and
  // `update_requirement`'s own status=approved branch already enforce
  // server-side (2026-08 UX audit roadmap, "No requirement approval action").
  const canApprove = myRoles.includes("project_manager");
  const canEdit = canArchive || myRoles.includes("stakeholder");
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [history, setHistory] = useState<RequirementVersionEntry[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [form, setForm] = useState({
    name: "",
    reasoning: "",
    clarification: "",
    description: "",
    changeNote: "",
    targetStageId: "",
    level: "requirement" as RequirementLevel,
    reviewDate: "",
    reviewLeadDays: "",
    reviewerId: "",
  });
  // Guards `form` against `reload()` — called after every unrelated
  // mutation on this page (posting a comment, uploading a file, linking an
  // action, ...) and not awaited by its callers, so it can still be
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

  const [saveError, setSaveError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [activity, setActivity] = useState<ChangeEntry[]>([]);
  // History/Activity merged into one card with a view toggle (2026-08 UX
  // audit roadmap item 516) — server-synced per-user via `useUiPreference`,
  // the same mechanism `useViewMode` (tile/list) already uses, so the
  // user's last-selected view becomes their remembered default. Defaults to
  // "activity" (the broader feed) rather than "versions", since Activity
  // was the one of the two previously visible in the persistent sidebar
  // regardless of scroll position — a judgment call, see docs/decisions.md.
  const [historyViewRaw, setHistoryView] = useUiPreference<string>("requirement_detail_history_view", "activity");
  const historyView: "versions" | "activity" = historyViewRaw === "versions" ? "versions" : "activity";
  const [reviewOutcome, setReviewOutcome] = useState<RequirementReviewOutcome>("met");
  const [reviewComment, setReviewComment] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [reviewerPickerUnavailable, setReviewerPickerUnavailable] = useState(false);
  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false);
  // Organisation id, needed to browse that org's shared resources (style
  // guide "Pattern: resource picker dialog") — set as soon as the project
  // itself resolves, independent of whether the org-member-only calls
  // right after it (org users, link types) succeed for this user.
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [showResourcePicker, setShowResourcePicker] = useState(false);

  // --- Traceability links (C-G-09) ------------------------------------
  // Create (`Popover`, one door per style guide Principle 3) and remove
  // (`ConfirmDialog`, Tier 1) both converted from permanently-visible
  // inline/immediate interactions in the 2026-08 UX audit's sixth pass —
  // see docs/ux-audit-2026-08.md "Links and linked actions."
  const [links, setLinks] = useState<RequirementLink[]>([]);
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[]>([]);
  const [projectRequirements, setProjectRequirements] = useState<Requirement[]>([]);
  const [newLinkTargetId, setNewLinkTargetId] = useState("");
  const [newLinkTypeId, setNewLinkTypeId] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const [addLinkPopoverOpen, setAddLinkPopoverOpen] = useState(false);
  const addLinkTriggerRef = useRef<HTMLButtonElement>(null);
  const [linkToRemove, setLinkToRemove] = useState<RequirementLink | null>(null);

  // --- Linked requirement actions --------------------------------------
  // Same conversion as the links above: "link existing" is a one-field
  // `Popover` (a quick decision about an existing entity, not a create
  // flow), "create and link" opens a brand-new `Action` in a `Modal` (per
  // the revised Principle 3 — a new entity has no "what came before it" in
  // the app's reading order, so it doesn't belong in `SidePanel`'s
  // contextual-detail slot), and unlinking goes through `ConfirmDialog`
  // instead of firing immediately.
  const [linkedActions, setLinkedActions] = useState<RequirementAction[]>([]);
  const [projectActionTypes, setProjectActionTypes] = useState<ActionTypeDefinition[]>([]);
  const [projectActions, setProjectActions] = useState<RequirementAction[]>([]);
  const [existingActionToLink, setExistingActionToLink] = useState("");
  const [linkExistingActionPopoverOpen, setLinkExistingActionPopoverOpen] = useState(false);
  const linkExistingActionTriggerRef = useRef<HTMLButtonElement>(null);
  const [showCreateAction, setShowCreateAction] = useState(false);
  const [newActionTitle, setNewActionTitle] = useState("");
  const [newActionDescription, setNewActionDescription] = useState("");
  const [newActionTypeId, setNewActionTypeId] = useState("");
  const [newActionAssigneeId, setNewActionAssigneeId] = useState("");
  const [newActionDueDate, setNewActionDueDate] = useState("");
  // Once locked, both flows above route through an ADD_ACTION change
  // request instead of the direct endpoint (item 514) — same "reason for
  // change" field every other change request requires.
  const [addActionReason, setAddActionReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionToUnlink, setActionToUnlink] = useState<RequirementAction | null>(null);

  function userDisplayName(userId: string | null): string {
    if (!userId) return strings.reviews.unassigned;
    return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
  }

  async function reload() {
    if (!projectId || !requirementId) return;
    const [req, hist, comm, fls, defs, stgs, act, lnks, actTypes, linkedActs, allActs, reqs] = await Promise.all([
      api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${requirementId}`),
      api.get<RequirementVersionEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/history`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/activity`),
      api.get<RequirementLink[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/links`),
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/actions`),
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
    ]);
    setRequirement(req);
    setHistory(hist);
    setComments(comm);
    setFiles(fls);
    setCustomFieldDefs(defs);
    // Submitted together with `form` in the same save() PUT below, so it
    // shares formDirtyRef's guard against the same reload() race.
    if (!formDirtyRef.current) setCustomFieldValues(req.custom_fields);
    setStages(stgs);
    setActivity(act);
    setLinks(lnks);
    setProjectActionTypes(actTypes);
    setLinkedActions(linkedActs);
    setProjectActions(allActs);
    setProjectRequirements(reqs);
    if (!formDirtyRef.current) {
      setForm({
        name: req.name,
        reasoning: req.reasoning,
        clarification: req.clarification,
        description: req.description,
        changeNote: "",
        targetStageId: req.target_stage_id,
        level: req.level,
        reviewDate: req.review_date ?? "",
        reviewLeadDays: req.review_lead_days != null ? String(req.review_lead_days) : "",
        reviewerId: req.reviewer_id ?? "",
      });
    }
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  async function uploadFile(file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`, file);
    reload();
  }

  async function removeFile(fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/files/${fileId}`);
    reload();
  }

  /** Links one or more already-uploaded organisation shared resources onto
   * this requirement, via the `POST .../files/link` endpoint (previously
   * unused from the frontend — see docs/ux-audit-2026-08.md "Shared org
   * resources have almost no way to consume them"). One request per file
   * id, sequentially — the endpoint itself only accepts one id at a time. */
  async function linkOrgResources(fileIds: string[]) {
    for (const fileId of fileIds) {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/files/link`, { file_id: fileId });
    }
    await reload();
    showToast(strings.resourcePicker.attachedToast(fileIds.length));
  }

  async function addLink() {
    if (!newLinkTargetId || !newLinkTypeId) return;
    setLinkError(null);
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/links`, {
        target_requirement_id: newLinkTargetId,
        link_type_id: newLinkTypeId,
      });
      setNewLinkTargetId("");
      setNewLinkTypeId("");
      setAddLinkPopoverOpen(false);
      reload();
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function removeLink(linkId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/links/${linkId}`);
    reload();
  }

  async function linkExistingAction() {
    if (!existingActionToLink) return;
    setActionError(null);
    try {
      if (requirement?.is_locked) {
        if (!addActionReason.trim()) return;
        await api.post(`/api/v1/projects/${projectId}/change-requests`, {
          kind: "add_action", requirement_id: requirementId,
          proposed_action_link_id: existingActionToLink, reason: addActionReason,
        });
        showToast(strings.changeRequests.created);
      } else {
        await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions`, {
          action_id: existingActionToLink,
        });
        showToast(strings.requirements.linkExistingAction);
      }
      setExistingActionToLink("");
      setAddActionReason("");
      setLinkExistingActionPopoverOpen(false);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function createAndLinkAction() {
    if (!newActionTitle.trim() || !newActionTypeId) return;
    setActionError(null);
    try {
      if (requirement?.is_locked) {
        if (!addActionReason.trim()) return;
        await api.post(`/api/v1/projects/${projectId}/change-requests`, {
          kind: "add_action", requirement_id: requirementId,
          proposed_action_title: newActionTitle, proposed_action_description: newActionDescription,
          proposed_action_type_id: newActionTypeId, proposed_action_assignee_id: newActionAssigneeId || null,
          proposed_action_due_date: newActionDueDate || null, reason: addActionReason,
        });
        showToast(strings.changeRequests.created);
      } else {
        await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions/create-and-link`, {
          title: newActionTitle,
          description: newActionDescription,
          action_type_id: newActionTypeId,
          assignee_id: newActionAssigneeId || null,
          due_date: newActionDueDate || null,
        });
      }
      setNewActionTitle("");
      setNewActionDescription("");
      setNewActionTypeId("");
      setNewActionAssigneeId("");
      setNewActionDueDate("");
      setAddActionReason("");
      setShowCreateAction(false);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function unlinkAction(actionId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions/${actionId}`);
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        setOrganizationId(project.organization_id);
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`);
        setOrgUsers(users);
        setLinkTypes(await api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${project.organization_id}/link-types`));
      } catch {
        // Org member directory isn't reachable for this user (e.g. no org
        // role) — fall back to the plain user-ID input rather than break
        // the page. Link types are best-effort from the same call; the
        // Links card below already handles an empty `linkTypes` list by
        // simply having nothing to offer in its type picker.
        setReviewerPickerUnavailable(true);
      }
    })();
  }, [projectId]);

  async function save() {
    if (!requirement) return;
    setSaveError(null);
    try {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}`, {
        name: form.name,
        reasoning: form.reasoning,
        clarification: form.clarification,
        description: form.description,
        component_id: requirement.component_id,
        category_id: requirement.category_id,
        owner_id: requirement.owner_id,
        target_stage_id: form.targetStageId,
        level: form.level,
        keywords: requirement.keywords,
        custom_fields: customFieldValues,
        change_note: form.changeNote,
        review_date: form.reviewDate || null,
        review_lead_days: form.reviewLeadDays ? Number(form.reviewLeadDays) : null,
        reviewer_id: form.reviewerId || null,
      });
      formDirtyRef.current = false;
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
    setArchiveDialogOpen(false);
    try {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}`);
      showToast(strings.requirements.archived);
      navigate(`/projects/${projectId}/requirements`);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Restore: no `ConfirmDialog` (unlike archive above) — mirrors
  // `ProjectAdminPage.tsx`'s existing unarchive button, which also fires
  // immediately, since restoring is reversible again (archive it right
  // back) rather than a Tier-1-confirmed action (2026-08 UX audit roadmap:
  // unarchive endpoint + Restore button).
  async function restore() {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/unarchive`);
      showToast(strings.requirements.restored);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function approveRequirement() {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/approve`);
      showToast(strings.requirements.approved);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function markCompleted() {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/complete`);
      showToast(strings.requirements.completed);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function unmarkCompleted() {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/uncomplete`);
      showToast(strings.requirements.completionReverted);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function submitReview() {
    setReviewError(null);
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/reviews`, {
        outcome: reviewOutcome,
        comment: reviewComment || null,
      });
      setReviewComment("");
      reload();
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function toggleSubscription() {
    if (!requirement) return;
    if (requirement.is_subscribed) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    }
    reload();
  }

  async function postComment(body: string): Promise<Comment> {
    const comment = await api.post<Comment>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`, { body });
    reload();
    return comment;
  }

  async function editComment(commentId: string, body: string) {
    await api.patch(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}`, { body });
    reload();
  }

  async function removeCommentAttachment(commentId: string, fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/files/${fileId}`);
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  async function uploadCommentAttachment(commentId: string, file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/files`, file);
    reload();
  }

  if (!requirement) return <Spinner />;

  // UX review: Add Link was always clickable even with nothing left to link
  // to (every other requirement in the project already linked, or a
  // single-requirement project) — greyed out below once this is empty.
  const eligibleLinkTargets = projectRequirements.filter(
    (r) => r.id !== requirementId && !links.some((l) => l.other_requirement_id === r.id)
  );

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          {requirement.unique_code} — {requirement.name}
        </h1>
        <div className="row">
          <SubscribeButton subscribed={requirement.is_subscribed} onToggle={toggleSubscription} />
          {canApprove && requirement.requires_approval && (
            <button className="btn btn-primary" onClick={approveRequirement}>
              <CheckCircle size={14} /> {strings.requirements.approve}
            </button>
          )}
          {/* Only offered once the {requirement} is actually locked — a
              change request against a still-draft/reviewed one is rejected
              server-side (2026-08 UX audit roadmap, "No requirement approval
              action; change requests can target draft requirements"); an
              unlocked {requirement} is edited directly instead. */}
          {requirement.is_locked && (
            <Link className="btn" to={`/projects/${projectId}/change-requests?requirement=${requirementId}`}>
              <GitPullRequest size={14} /> {strings.requirements.makeChangeRequest}
            </Link>
          )}
          {canArchive && requirement.status === "approved" && (
            <button className="btn" onClick={markCompleted}>
              {strings.requirements.markCompleted}
            </button>
          )}
          {canArchive && requirement.status === "completed" && (
            <button className="btn" onClick={unmarkCompleted}>
              {strings.requirements.unmarkCompleted}
            </button>
          )}
          {canArchive && !requirement.is_archived && (
            <button className="btn btn-danger" onClick={() => setArchiveDialogOpen(true)}>
              {strings.requirements.archive}
            </button>
          )}
          {canArchive && requirement.is_archived && (
            <button className="btn" onClick={restore}>
              <ArchiveRestore size={14} /> {strings.requirements.restore}
            </button>
          )}
        </div>
      </div>

      {requirement.is_archived && (
        <div className="badge" style={{ alignSelf: "flex-start" }}>
          {strings.requirements.archivedBadge}
        </div>
      )}

      {archiveDialogOpen && (
        <ConfirmDialog
          title={strings.requirements.archiveTitle}
          message={strings.requirements.archiveConfirm}
          confirmLabel={strings.requirements.archive}
          onConfirm={archive}
          onCancel={() => setArchiveDialogOpen(false)}
        />
      )}

      {/* Was a two-column `.side-grid` (main content + a narrow persistent
          Activity sidebar) before the History/Activity merge above folded
          the sidebar's only content into the main column's card — a single
          `.stack` is the right shell now that there's nothing left for a
          second column to hold. */}
      <div className="stack">
      {requirement.is_locked || !canEdit ? (
        <div className="card stack">
          {requirement.is_locked && (
            <div className="badge" style={{ alignSelf: "flex-start" }}>
              {strings.requirements.locked} — {strings.requirements.lockedNotice}
            </div>
          )}
          <div>
            <div className="text-muted">{strings.requirements.reasoning}</div>
            <p style={{ marginTop: "0.25rem" }}>{requirement.reasoning}</p>
          </div>
          {requirement.clarification && (
            <div>
              <div className="text-muted">{strings.requirements.clarification}</div>
              <p style={{ marginTop: "0.25rem" }}>{requirement.clarification}</p>
            </div>
          )}
          {requirement.description && (
            <div>
              <div className="text-muted">{strings.requirements.description}</div>
              <p style={{ marginTop: "0.25rem" }}>{requirement.description}</p>
            </div>
          )}
          <div className="row">
            <span className="badge">{strings.requirements.status}: {REQUIREMENT_STATUS_LABEL[requirement.status]}</span>
            <span className="badge">Target: {stageName(requirement.target_stage_id)}</span>
            <span className="badge">Level: {REQUIREMENT_LEVEL_LABEL[requirement.level]}</span>
            {requirement.review_date && <span className="badge">{strings.requirements.reviewDate}: {requirement.review_date}</span>}
            {requirement.keywords.map((k) => (
              <span key={k} className="badge">
                {k}
              </span>
            ))}
          </div>
          <CustomFieldsForm definitions={customFieldDefs} values={customFieldValues} disabled onChange={() => {}} />
        </div>
      ) : (
        <div className="card stack">
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.name}
            <input className="input" value={form.name} onChange={(e) => updateForm((f) => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.reasoning}
            <textarea
              className="input"
              rows={3}
              value={form.reasoning}
              onChange={(e) => updateForm((f) => ({ ...f, reasoning: e.target.value }))}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.clarification}
            <textarea
              className="input"
              rows={2}
              value={form.clarification}
              onChange={(e) => updateForm((f) => ({ ...f, clarification: e.target.value }))}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.description}
            <textarea
              className="input"
              rows={2}
              value={form.description}
              onChange={(e) => updateForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.targetVersion}
              <select
                className="input"
                value={form.targetStageId}
                onChange={(e) => updateForm((f) => ({ ...f, targetStageId: e.target.value }))}
              >
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.level}
              <select
                className="input"
                value={form.level}
                onChange={(e) => updateForm((f) => ({ ...f, level: e.target.value as RequirementLevel }))}
              >
                <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
                <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
                <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
              </select>
            </label>
          </div>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewDate}
              <input
                className="input" type="date" value={form.reviewDate}
                onChange={(e) => updateForm((f) => ({ ...f, reviewDate: e.target.value }))}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewLeadDays}
              <input
                className="input" type="number" min={0} value={form.reviewLeadDays}
                onChange={(e) => updateForm((f) => ({ ...f, reviewLeadDays: e.target.value }))}
              />
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.reviewer}
              {reviewerPickerUnavailable ? (
                <input
                  className="input" placeholder={strings.admin.userId} value={form.reviewerId}
                  onChange={(e) => updateForm((f) => ({ ...f, reviewerId: e.target.value }))}
                />
              ) : (
                <select
                  className="input" value={form.reviewerId}
                  onChange={(e) => updateForm((f) => ({ ...f, reviewerId: e.target.value }))}
                >
                  <option value="">{strings.reviews.unassigned}</option>
                  {orgUsers.map((u) => (
                    <option key={u.user_id} value={u.user_id}>
                      {u.display_name} ({u.email})
                    </option>
                  ))}
                  {form.reviewerId && !orgUsers.some((u) => u.user_id === form.reviewerId) && (
                    <option value={form.reviewerId}>
                      {form.reviewerId} ({strings.requirements.reviewerNoLongerMember})
                    </option>
                  )}
                </select>
              )}
            </label>
          </div>
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => {
              formDirtyRef.current = true;
              setCustomFieldValues((v) => ({ ...v, [fieldId]: value }));
            }}
          />
          <input
            className="input"
            placeholder={strings.requirements.changeNote}
            value={form.changeNote}
            onChange={(e) => updateForm((f) => ({ ...f, changeNote: e.target.value }))}
          />
          {saveError && <div style={{ color: "var(--color-danger)" }}>{saveError}</div>}
          <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
            {strings.requirements.save}
          </button>
        </div>
      )}

      {requirement.review_date && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.reviewSection}</h2>
          <div className="row">
            <span className="badge">{strings.requirements.reviewDate}: {requirement.review_date}</span>
            <span className="badge">{strings.requirements.reviewer}: {userDisplayName(requirement.reviewer_id)}</span>
          </div>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.recordReviewOutcome}
            <select
              className="input" value={reviewOutcome}
              onChange={(e) => setReviewOutcome(e.target.value as RequirementReviewOutcome)}
            >
              <option value="met">{strings.requirements.reviewOutcomeMet}</option>
              <option value="failed">{strings.requirements.reviewOutcomeFailed}</option>
            </select>
          </label>
          {reviewOutcome === "failed" && (
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.requirements.reviewComment}
              <textarea
                className="input" rows={2} value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
          )}
          {reviewError && <div style={{ color: "var(--color-danger)" }}>{reviewError}</div>}
          <button className="btn btn-primary" onClick={submitReview} style={{ alignSelf: "flex-start" }}>
            {strings.requirements.submitReview}
          </button>
        </div>
      )}

      {/* History and Activity merged into one card with a view toggle
          (2026-08 UX audit roadmap item 516) — "Version history" is
          specifically this requirement's own approved version/status
          transitions (the RequirementVersion ledger); "Activity" is the
          broader audit-log feed covering everything that happened to it,
          including but not limited to those same version changes. Both
          renderings are kept, not one dropped in favour of the other — see
          docs/ux-style-guide.md's "Pattern: view toggle" for the shape this
          follows (a `useUiPreference`-backed toggle, same mechanism as
          tile/list view elsewhere), and docs/decisions.md for why this
          isn't literally the shared `ViewToggle` component (different
          icon/label pair, not tile-vs-list). */}
      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
            {historyView === "versions" ? strings.requirements.versionHistory : strings.requirements.activity}
          </h2>
          <div className="row" style={{ gap: "0.25rem" }}>
            <button
              className={`btn ${historyView === "versions" ? "btn-primary" : ""}`}
              onClick={() => setHistoryView("versions")}
              title={strings.requirements.versionHistory}
              aria-label={strings.requirements.versionHistory}
              aria-pressed={historyView === "versions"}
            >
              <TableIcon size={16} />
            </button>
            <button
              className={`btn ${historyView === "activity" ? "btn-primary" : ""}`}
              onClick={() => setHistoryView("activity")}
              title={strings.requirements.activity}
              aria-label={strings.requirements.activity}
              aria-pressed={historyView === "activity"}
            >
              <ActivityIcon size={16} />
            </button>
          </div>
        </div>
        {historyView === "versions" ? (
          <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>{strings.requirements.status}</th>
                <th>{strings.requirements.changeNote}</th>
                <th>{strings.requirements.changedBy}</th>
                <th>{strings.requirements.when}</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.version_number}>
                  <td>{h.version_number}</td>
                  <td>{REQUIREMENT_STATUS_LABEL[h.status]}</td>
                  <td>{h.change_note}</td>
                  <td>{userDisplayName(h.created_by)}</td>
                  <td>{new Date(h.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : (
          <ActivityPanel entries={activity} bare />
        )}
      </div>

      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.attachments}</h2>
          {!requirement.is_locked && organizationId && (
            <button className="btn" onClick={() => setShowResourcePicker(true)}>
              <FolderOpen size={14} /> {strings.resourcePicker.linkFromSharedResources}
            </button>
          )}
        </div>
        <FileAttachmentList
          files={files}
          onUpload={uploadFile}
          onRemove={removeFile}
          disabled={requirement.is_locked}
          emptyHint={strings.requirements.attachmentsLockedNotice}
        />
      </div>
      {showResourcePicker && organizationId && (
        <ResourcePickerModal
          title={strings.resourcePicker.linkFromSharedResources}
          sources={[
            {
              id: "org-resources",
              label: strings.resourcePicker.orgResourcesSource(orgLabelCap),
              loadFiles: () => api.get<FileAsset[]>(`/api/v1/orgs/${organizationId}/resources`),
            },
          ]}
          onClose={() => setShowResourcePicker(false)}
          onAttach={linkOrgResources}
        />
      )}

      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.links}</h2>
          <button
            ref={addLinkTriggerRef}
            className="btn btn-primary"
            disabled={eligibleLinkTargets.length === 0}
            title={eligibleLinkTargets.length === 0 ? strings.requirements.noEligibleLinkTargets : undefined}
            onClick={() => {
              setLinkError(null);
              setAddLinkPopoverOpen((o) => !o);
            }}
          >
            <Plus size={14} /> {strings.requirements.addLink}
          </button>
          {addLinkPopoverOpen && (
            <Popover anchorRef={addLinkTriggerRef} title={strings.requirements.addLink} onClose={() => setAddLinkPopoverOpen(false)}>
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.requirements.targetRequirement}
                <select
                  className="input" aria-label={strings.requirements.targetRequirement}
                  value={newLinkTargetId} onChange={(e) => setNewLinkTargetId(e.target.value)}
                >
                  <option value="">{strings.requirements.selectARequirementToLink}</option>
                  {eligibleLinkTargets.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.unique_code} — {r.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.requirements.linkType}
                <select
                  className="input" aria-label={strings.requirements.linkType}
                  value={newLinkTypeId} onChange={(e) => setNewLinkTypeId(e.target.value)}
                >
                  <option value="">{strings.requirements.linkType}</option>
                  {linkTypes.map((lt) => (
                    <option key={lt.id} value={lt.id}>
                      {lt.forward_name}
                    </option>
                  ))}
                </select>
              </label>
              {linkError && <div style={{ color: "var(--color-danger)" }}>{linkError}</div>}
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn" onClick={() => setAddLinkPopoverOpen(false)}>
                  {strings.common.cancel}
                </button>
                <button className="btn btn-primary" onClick={addLink} disabled={!newLinkTargetId || !newLinkTypeId}>
                  {strings.requirements.addLink}
                </button>
              </div>
            </Popover>
          )}
        </div>
        {links.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.requirements.noLinks}</p>}
        {[...links]
          .sort((a, b) => a.display_name.localeCompare(b.display_name) || a.other_requirement_unique_code.localeCompare(b.other_requirement_unique_code))
          .map((link) => (
            <div key={link.id} className="row" style={{ justifyContent: "space-between" }}>
              <span>
                <span className="badge">{link.display_name}</span>{" "}
                <Link to={`/projects/${projectId}/requirements/${link.other_requirement_id}`}>
                  {link.other_requirement_unique_code} — {link.other_requirement_name}
                </Link>
              </span>
              <button
                className="btn btn-danger"
                title={strings.requirements.removeLink}
                aria-label={strings.requirements.removeLink}
                onClick={() => setLinkToRemove(link)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        {linkToRemove && (
          <ConfirmDialog
            title={strings.requirements.removeLinkTitle}
            message={strings.requirements.removeLinkConfirm}
            confirmLabel={strings.requirements.removeLink}
            onConfirm={async () => {
              const id = linkToRemove.id;
              setLinkToRemove(null);
              await removeLink(id);
            }}
            onCancel={() => setLinkToRemove(null)}
          />
        )}
      </div>

      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.actionsSection}</h2>
          <div className="row">
            <button
              ref={linkExistingActionTriggerRef}
              className="btn"
              onClick={() => {
                setActionError(null);
                setLinkExistingActionPopoverOpen((o) => !o);
              }}
            >
              <Plus size={14} /> {strings.requirements.linkExistingAction}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => {
                setActionError(null);
                setShowCreateAction(true);
              }}
            >
              <Plus size={14} /> {strings.requirements.createAndLinkAction}
            </button>
          </div>
          {linkExistingActionPopoverOpen && (
            <Popover
              anchorRef={linkExistingActionTriggerRef}
              title={strings.requirements.linkExistingAction}
              onClose={() => setLinkExistingActionPopoverOpen(false)}
            >
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.requirements.linkExistingAction}
                <select
                  className="input" aria-label={strings.requirements.linkExistingAction}
                  value={existingActionToLink} onChange={(e) => setExistingActionToLink(e.target.value)}
                >
                  <option value="">{strings.requirements.selectAnActionToLink}</option>
                  {projectActions
                    .filter((a) => !linkedActions.some((la) => la.id === a.id))
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.unique_code} — {a.title}
                      </option>
                    ))}
                </select>
              </label>
              {requirement.is_locked && (
                <label className="stack" style={{ gap: "0.25rem" }}>
                  {strings.changeRequests.reason}
                  <textarea
                    className="input" rows={2} aria-label={strings.changeRequests.reason}
                    value={addActionReason} onChange={(e) => setAddActionReason(e.target.value)}
                  />
                </label>
              )}
              {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn" onClick={() => setLinkExistingActionPopoverOpen(false)}>
                  {strings.common.cancel}
                </button>
                <button
                  className="btn btn-primary" onClick={linkExistingAction}
                  disabled={!existingActionToLink || (requirement.is_locked && !addActionReason.trim())}
                >
                  {strings.requirements.linkExistingAction}
                </button>
              </div>
            </Popover>
          )}
        </div>
        {linkedActions.length === 0 && (
          <p className="text-muted" style={{ margin: 0 }}>{strings.requirements.noLinkedActions}</p>
        )}
        {linkedActions.map((a) => (
          <div key={a.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              <Link to={`/projects/${projectId}/actions/${a.id}`}>{a.unique_code} — {a.title}</Link>{" "}
              <span className="badge">{REQUIREMENT_ACTION_OUTCOME_LABEL[a.outcome_status]}</span>
            </span>
            <button
              className="btn btn-danger"
              title={strings.requirements.unlinkAction}
              aria-label={strings.requirements.unlinkAction}
              onClick={() => setActionToUnlink(a)}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {actionToUnlink && (
          <ConfirmDialog
            title={strings.requirements.unlinkActionTitle}
            message={strings.requirements.unlinkActionConfirm}
            confirmLabel={strings.requirements.unlinkAction}
            onConfirm={async () => {
              const id = actionToUnlink.id;
              setActionToUnlink(null);
              await unlinkAction(id);
            }}
            onCancel={() => setActionToUnlink(null)}
          />
        )}
        {showCreateAction && (
          <Modal title={strings.requirements.createAndLinkAction} onClose={() => setShowCreateAction(false)}>
            <input
              className="input" placeholder={strings.actions.name} value={newActionTitle}
              onChange={(e) => setNewActionTitle(e.target.value)}
            />
            <textarea
              className="input" rows={2} placeholder={strings.actions.description} value={newActionDescription}
              onChange={(e) => setNewActionDescription(e.target.value)}
            />
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.actionType}
              {/* An explicit `aria-label` (matching the visible label
                  text) is required here, not just the wrapping <label>:
                  a native <select>'s ARIA accessible-name computation
                  when label-wrapped folds in every descendant <option>'s
                  text too, not just the selected one, which would
                  otherwise make this resolve to something like
                  "TypeTypeReviewTest" instead of "Type" for automated
                  (Playwright) lookups — an aria-label always wins over
                  that content-based computation. */}
              <select
                className="input" aria-label={strings.actions.actionType}
                value={newActionTypeId} onChange={(e) => setNewActionTypeId(e.target.value)}
              >
                <option value="">{strings.actions.actionType}</option>
                {projectActionTypes.map((at) => (
                  <option key={at.id} value={at.id}>
                    {at.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.assignee}
              <select
                className="input" aria-label={strings.actions.assignee}
                value={newActionAssigneeId} onChange={(e) => setNewActionAssigneeId(e.target.value)}
              >
                <option value="">{strings.reviews.unassigned}</option>
                {orgUsers.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.display_name} ({u.email})
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.actions.dueDate}
              <input
                className="input" type="date" value={newActionDueDate}
                onChange={(e) => setNewActionDueDate(e.target.value)}
              />
            </label>
            {requirement.is_locked && (
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.changeRequests.reason}
                <textarea
                  className="input" rows={2} aria-label={strings.changeRequests.reason}
                  value={addActionReason} onChange={(e) => setAddActionReason(e.target.value)}
                />
              </label>
            )}
            {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}
            <button
              className="btn btn-primary" style={{ alignSelf: "flex-start" }}
              onClick={createAndLinkAction}
              disabled={!newActionTitle.trim() || !newActionTypeId || (requirement.is_locked && !addActionReason.trim())}
            >
              {strings.common.create}
            </button>
          </Modal>
        )}
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
  );
}
