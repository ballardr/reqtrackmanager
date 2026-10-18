import { Bell, BellOff, CheckCircle, FolderOpen, GitPullRequest, Plus, Trash2 } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  Comment,
  CustomFieldDefinition,
  FileAsset,
  Organization,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementAction,
  RequirementLevel,
  RequirementReviewOutcome,
  PrincipalRef,
  RequirementVersionEntry,
} from "../api/types";
import {
  ENTITY_ACCENT_COLOR,
  REQUIREMENT_ACTION_OUTCOME_LABEL,
  REQUIREMENT_ACTION_OUTCOME_TONE,
  REQUIREMENT_LEVEL_LABEL,
  REQUIREMENT_STATUS_LABEL,
  principalRef,
  REQUIREMENT_STATUS_TONE,
  savedPrincipalDisplay,
} from "../api/types";
import { ArtefactLinksPanel, type LinksChangeRequestMode } from "../components/ArtefactLinksPanel";
import { RecordActivity } from "../components/RecordActivity";
import { PrincipalBadge } from "../components/PrincipalBadge";
import { WatchingGroupsPanel } from "../components/WatchingGroupsPanel";
import { PrincipalFormField } from "../components/PrincipalFormField";
import { CommentThread } from "../components/CommentThread";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { DetailLayout } from "../components/DetailLayout";
import { FileAttachmentList } from "../components/FileAttachmentList";
import { Modal } from "../components/Modal";
import { Popover } from "../components/Popover";
import { ResourcePickerModal } from "../components/ResourcePickerModal";
import { Spinner } from "../components/Spinner";
import { RecordHeader } from "../components/RecordHeader";
import { useConfirmedAction } from "../components/useConfirmedAction";
import { useAuth } from "../context/AuthContext";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useProjectEnabledModules } from "../hooks/useProjectEnabledModules";
import { getInstalledModule } from "../modules/registry";
import { Badge } from "../components/Badge";

/**
 * Requirement detail view: direct editing while unlocked, a discussion
 * thread (C-R-01), a change log that intentionally excludes discussion
 * comments (C-A-09 clarification), a Links card for typed bidirectional
 * traceability links to other requirements (C-G-09 — server-resolved
 * direction/display name, so this page never has to guess which of a link
 * type's forward/reverse names applies), and an Actions card for
 * requirement actions (review/test/etc.) linked via `RequirementActionLink`.
 * Links aren't gated by `is_locked` — they're metadata about the
 * requirement, not its own governed content, *by default* — a project (or
 * an org-wide force, minus a per-project exemption) can opt into gating
 * link add/remove too (platform review 2026-09:
 * `Project.require_change_request_for_approved_links`/
 * `Organization.force_require_change_request_for_approved_links`), routing
 * through `ADD_LINK`/`REMOVE_LINK` change requests the same way actions
 * already do. Actions *are* always gated once locked: once
 * locked, adding, linking, or removing one requires an `ADD_ACTION`/
 * `REMOVE_ACTION` change request instead of the direct endpoint, the same
 * change-request-only-once-locked rule the requirement's own fields
 * already follow (`services.requirements.LOCKED_STATUSES`) — see
 * `docs/decisions.md` for the reasoning.
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
  // server-side.
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
    owner: null as PrincipalRef | null,
    reviewer: null as PrincipalRef | null,
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
  const [reviewOutcome, setReviewOutcome] = useState<RequirementReviewOutcome>("met");
  const [reviewComment, setReviewComment] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  // Organisation id, needed to browse that org's shared resources (style
  // guide "Pattern: resource picker dialog") — set as soon as the project
  // itself resolves, independent of whether the org-member-only calls
  // right after it (org users, link types) succeed for this user.
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [showResourcePicker, setShowResourcePicker] = useState(false);
  // The project's own
  // `require_change_request_for_approved_links` plus the org's
  // `force_require_change_request_for_approved_links` (minus this
  // project's `exempt_from_org_link_lock`) determine whether link
  // add/remove is gated the same way actions already are. Best-effort: if
  // the org fetch fails (e.g. this user has no org role at all, the same
  // "org member directory isn't reachable" case the org users/link types
  // fetch below already tolerates), `orgForceLinksLocked` just stays
  // false rather than breaking the page.
  const [project, setProject] = useState<Project | null>(null);
  const [orgForceLinksLocked, setOrgForceLinksLocked] = useState(false);

  // --- Traceability links (C-G-09) ------------------------------------
  // Links are shown and edited by the shared Links panel in the aside
  // (`ArtefactLinksPanel`) —
  // requirement-to-requirement, module-origin (Decisions, Pain Points,
  // Compliance, ...) and cross-project links alike. This page only decides
  // whether link changes must go through a change request (`linksLockedForCR`,
  // below) and supplies the two calls for that. Bumped after anything on this
  // page that could change the links, so the panel reloads.
  const [linksRefreshToken, setLinksRefreshToken] = useState(0);
  // Extra module-contributed sections (`requirementDetailSections`), rendered under
  // the Links panel in the aside. This page renders whatever each currently-enabled
  // module hands it and never imports a specific module's entity itself, mirroring
  // `ProjectOverviewPage.tsx`'s identical `projectOverviewTiles` convention.
  const { modules: enabledModules } = useProjectEnabledModules(projectId ?? null);
  const contributedLinkSections =
    projectId && requirementId && organizationId
      ? enabledModules.flatMap((entry) =>
          (getInstalledModule(entry.module_key)?.requirementDetailSections ?? []).map((section) => ({
            key: `${entry.module_key}:${section.key}`,
            node: section.render({ projectId, requirementId, organizationId, refreshToken: linksRefreshToken }),
          }))
        )
      : [];

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
  const [newActionAssignee, setNewActionAssignee] = useState<PrincipalRef | null>(null);
  const [newActionDueDate, setNewActionDueDate] = useState("");
  // Once locked, both flows above route through an ADD_ACTION change
  // request instead of the direct endpoint — same "reason for
  // change" field every other change request requires.
  const [addActionReason, setAddActionReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionToUnlink, setActionToUnlink] = useState<RequirementAction | null>(null);
  // Only rendered/required once
  // `requirement.is_locked` (unlinking an action is unconditionally gated
  // once locked, unlike links above).
  const [unlinkActionReason, setUnlinkActionReason] = useState("");

  function userDisplayName(userId: string | null): string {
    if (!userId) return strings.reviews.unassigned;
    return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
  }

  async function reload() {
    if (!projectId || !requirementId) return;
    const [req, hist, comm, fls, defs, stgs, actTypes, linkedActs, allActs] = await Promise.all([
      api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${requirementId}`),
      api.get<RequirementVersionEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/history`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions`),
      api.get<RequirementAction[]>(`/api/v1/projects/${projectId}/actions`),
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
    setProjectActionTypes(actTypes);
    setLinkedActions(linkedActs);
    setProjectActions(allActs);
    setLinksRefreshToken((t) => t + 1);
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
        owner: principalRef(req.owner),
        reviewer: principalRef(req.reviewer),
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
   * unused from the frontend — "Shared org
   * resources have almost no way to consume them"). One request per file
   * id, sequentially — the endpoint itself only accepts one id at a time. */
  async function linkOrgResources(fileIds: string[]) {
    for (const fileId of fileIds) {
      await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/files/link`, { file_id: fileId });
    }
    await reload();
    showToast(strings.resourcePicker.attachedToast(fileIds.length));
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
          proposed_action_type_id: newActionTypeId, proposed_action_assignee: newActionAssignee,
          proposed_action_due_date: newActionDueDate || null, reason: addActionReason,
        });
        showToast(strings.changeRequests.created);
      } else {
        await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions/create-and-link`, {
          title: newActionTitle,
          description: newActionDescription,
          action_type_id: newActionTypeId,
          assignee: newActionAssignee,
          due_date: newActionDueDate || null,
        });
      }
      setNewActionTitle("");
      setNewActionDescription("");
      setNewActionTypeId("");
      setNewActionAssignee(null);
      setNewActionDueDate("");
      setAddActionReason("");
      setShowCreateAction(false);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  /** `unlink_action` previously had no
   * lock check at all, an asymmetry with the already-gated add side (item
   * 514); unconditional across every project, unlike `removeLink` above
   * which only gates when `linksLockedForCR`. */
  async function unlinkAction(actionId: string, reason?: string) {
    if (requirement?.is_locked) {
      await api.post(`/api/v1/projects/${projectId}/change-requests`, {
        kind: "remove_action", requirement_id: requirementId,
        proposed_action_link_id: actionId, reason: reason ?? "",
      });
      showToast(strings.changeRequests.created);
    } else {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/actions/${actionId}`);
    }
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId]);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      let proj: Project;
      try {
        proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
      } catch {
        return;
      }
      setOrganizationId(proj.organization_id);
      setProject(proj);
      try {
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`);
        setOrgUsers(users);
        // `OrganizationOut.
        // force_require_change_request_for_approved_links` is readable by
        // any org member (unlike most other org policy toggles), so this
        // shares the same try/catch as the org-member-only calls above.
        const org = await api.get<Organization>(`/api/v1/orgs/${proj.organization_id}`);
        setOrgForceLinksLocked(org.force_require_change_request_for_approved_links);
      } catch {
        // Org member directory isn't reachable for this user (e.g. no org
        // role) — the owner and reviewer pickers search the server instead
        // and stay usable. `orgForceLinksLocked` stays at its default
        // (false) — see its own state comment.
      }
    })();
  }, [projectId]);

  // Mirrors `services.requirements.
  // requires_change_request_for_links`'s resolution exactly: the project's
  // own opt-in always wins when set; otherwise the org's force applies
  // unless this project is marked exempt.
  const requiresCRForLinks = !!(
    project?.require_change_request_for_approved_links ||
    (orgForceLinksLocked && !project?.exempt_from_org_link_lock)
  );
  const linksLockedForCR = !!requirement?.is_locked && requiresCRForLinks;

  /** Once `linksLockedForCR`, the Links panel
   * proposes link changes as `add_link`/`remove_link` change requests instead of
   * calling the link endpoints (the same branch `linkExistingAction` below takes
   * for `add_action`). `undefined` when links are not locked. An `add_link` request
   * carries the one link the dialog chose (any record the panel can link to, from
   * either end); the reason is required by the panel before it calls. */
  const linksChangeRequest: LinksChangeRequestMode | undefined = linksLockedForCR
    ? {
        onPropose: async (link, reason) => {
          await api.post(`/api/v1/projects/${projectId}/change-requests`, {
            kind: "add_link", requirement_id: requirementId, proposed_links: [link], reason,
          });
          showToast(strings.changeRequests.created);
        },
        onProposeRemove: async (linkId, reason) => {
          await api.post(`/api/v1/projects/${projectId}/change-requests`, {
            kind: "remove_link", requirement_id: requirementId, proposed_link_id: linkId, reason,
          });
          showToast(strings.changeRequests.created);
        },
      }
    : undefined;

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
        owner: form.owner,
        target_stage_id: form.targetStageId,
        level: form.level,
        keywords: requirement.keywords,
        custom_fields: customFieldValues,
        change_note: form.changeNote,
        review_date: form.reviewDate || null,
        review_lead_days: form.reviewLeadDays ? Number(form.reviewLeadDays) : null,
        reviewer: form.reviewer,
      });
      formDirtyRef.current = false;
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
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
  // back) rather than a Tier-1-confirmed action.
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

  const archiveAction = useConfirmedAction(
    requirement && {
      label: requirement.is_archived ? strings.requirements.restore : strings.requirements.archive,
      danger: !requirement.is_archived,
      hidden: !canArchive,
      immediate: requirement.is_archived,
      title: strings.requirements.archiveTitle,
      message: strings.requirements.archiveConfirm,
      confirmLabel: strings.requirements.archive,
      onConfirm: requirement.is_archived ? restore : archive,
    },
  );

  if (!requirement) return <Spinner />;

  return (
    <DetailLayout
      activity={projectId && requirementId ? <RecordActivity projectId={projectId} artefactType="requirement" artefactId={requirementId} refreshToken={linksRefreshToken} /> : undefined}
      contained={false}
      aside={
        projectId && requirementId ? (
          <>
            <ArtefactLinksPanel
              projectId={projectId}
              artefactType="requirement"
              artefactId={requirementId}
              refreshToken={linksRefreshToken}
              changeRequest={linksChangeRequest}
              hideStructuralLinks
            />
            {contributedLinkSections.map(({ key, node }) => (
              <div key={key}>{node}</div>
            ))}
          </>
        ) : null
      }
    >
      <RecordHeader
        recordLabel={strings.requirements.recordLabel}
        title={requirement.name}
        code={requirement.unique_code}
        badges={
          <>
            {requirement.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
            {requirement.is_subscribed && <Badge tone="info">{strings.requirements.subscribed}</Badge>}
          </>
        }
        actions={[
          {
            label: requirement.is_subscribed ? strings.requirements.unsubscribe : strings.requirements.subscribe,
            icon: requirement.is_subscribed ? <BellOff /> : <Bell />,
            onSelect: toggleSubscription,
          },
          archiveAction.item,
        ]}
        transitions={
          <>
            {canApprove && requirement.requires_approval && (
              <button className="btn btn-primary" onClick={approveRequirement}>
                <CheckCircle /> {strings.requirements.approve}
              </button>
            )}
            {/* Only offered once the {requirement} is actually locked — a
                change request against a still-draft/reviewed one is rejected
                server-side; an
                unlocked {requirement} is edited directly instead. */}
            {requirement.is_locked && (
              <Link className="btn" to={`/projects/${projectId}/change-requests?requirement=${requirementId}`}>
                <GitPullRequest /> {strings.requirements.makeChangeRequest}
              </Link>
            )}
            {canArchive && requirement.status === "approved" && !requirement.is_completed && (
              <button className="btn" onClick={markCompleted}>
                {strings.requirements.markCompleted}
              </button>
            )}
            {canArchive && requirement.is_completed && (
              <button className="btn" onClick={unmarkCompleted}>
                {strings.requirements.unmarkCompleted}
              </button>
            )}
          </>
        }
      />
      {archiveAction.dialog}

      {projectId && (
        <WatchingGroupsPanel
          recordPath={`/api/v1/projects/${projectId}/requirements/${requirementId}`}
          organizationId={organizationId ?? undefined} projectId={projectId} canManage={canArchive}
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
            <Badge>
              {strings.requirements.locked} — {strings.requirements.lockedNotice}
            </Badge>
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
            <Badge tone={REQUIREMENT_STATUS_TONE[requirement.status]}>
              {strings.requirements.status}: {REQUIREMENT_STATUS_LABEL[requirement.status]}
            </Badge>
            {/* C-G-11: completion is a separate overlay marker from lifecycle
                status — rendered as its own badge rather than merged into the
                status badge above, since the two are now independent
                concepts (a completed requirement's status badge still reads
                "Approved"). */}
            {requirement.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
            <Badge>Target: {stageName(requirement.target_stage_id)}</Badge>
            <Badge>Level: {REQUIREMENT_LEVEL_LABEL[requirement.level]}</Badge>
            {requirement.review_date && <Badge>{strings.requirements.reviewDate}: {requirement.review_date}</Badge>}
            <Badge>
              {strings.requirements.owner}: <PrincipalBadge principal={requirement.owner} />
            </Badge>
            {requirement.keywords.map((k) => (
              <Badge key={k}>
                {k}
              </Badge>
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
            <div style={{ flex: 1 }}>
              <PrincipalFormField
                label={strings.requirements.reviewer} orgUsers={orgUsers} organizationId={organizationId ?? undefined}
                projectId={projectId} value={form.reviewer} display={savedPrincipalDisplay(form.reviewer, requirement.reviewer)}
                onChange={(reviewer) => updateForm((f) => ({ ...f, reviewer }))}
                ariaLabel={strings.requirements.reviewer} placeholder={strings.reviews.unassigned}
              />
            </div>
          </div>
          <PrincipalFormField
            label={strings.requirements.owner} orgUsers={orgUsers} organizationId={organizationId ?? undefined}
            projectId={projectId} value={form.owner} display={savedPrincipalDisplay(form.owner, requirement.owner)}
            onChange={(owner) => updateForm((f) => ({ ...f, owner }))}
            ariaLabel={strings.requirements.owner} placeholder={strings.reviews.unassigned} clearLabel="Clear"
          />
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
          <button className="btn btn-primary" onClick={save} disabled={!form.owner} style={{ alignSelf: "flex-start" }}>
            {strings.requirements.save}
          </button>
        </div>
      )}

      {requirement.review_date && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.reviewSection}</h2>
          <div className="row">
            <Badge>{strings.requirements.reviewDate}: {requirement.review_date}</Badge>
            <Badge>
              {strings.requirements.reviewer}: <PrincipalBadge principal={requirement.reviewer} placeholder={strings.reviews.unassigned} />
            </Badge>
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

      {/* The requirement's own version ledger stays in the body (a wide table never goes in the
          aside); what happened to it, links included, is the aside's Activity tab. */}
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.versions}</h2>
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
      </div>

      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.attachments}</h2>
          {!requirement.is_locked && organizationId && (
            <button className="btn" onClick={() => setShowResourcePicker(true)}>
              <FolderOpen /> {strings.resourcePicker.linkFromSharedResources}
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
              <Plus /> {strings.requirements.linkExistingAction}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => {
                setActionError(null);
                setShowCreateAction(true);
              }}
            >
              <Plus /> {strings.requirements.createAndLinkAction}
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
                        <RecordCode code={a.unique_code} /> — {a.title}
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
          <div
            key={a.id}
            className="row entity-accent-card"
            style={{
              justifyContent: "space-between",
              paddingLeft: "0.5rem",
              ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.action,
            }}
          >
            <span>
              <Link to={`/projects/${projectId}/actions/${a.id}`}><RecordCode code={a.unique_code} /> — {a.title}</Link>{" "}
              <Badge tone={REQUIREMENT_ACTION_OUTCOME_TONE[a.outcome_status]}>
                {REQUIREMENT_ACTION_OUTCOME_LABEL[a.outcome_status]}
              </Badge>
            </span>
            <button
              className="btn btn-danger"
              title={strings.requirements.unlinkAction}
              aria-label={strings.requirements.unlinkAction}
              onClick={() => {
                setUnlinkActionReason("");
                setActionToUnlink(a);
              }}
            >
              <Trash2 />
            </button>
          </div>
        ))}
        {actionToUnlink && (
          <ConfirmDialog
            title={requirement.is_locked ? strings.requirements.unlinkActionViaChangeRequestTitle : strings.requirements.unlinkActionTitle}
            message={
              requirement.is_locked ? (
                <span className="stack" style={{ gap: "0.5rem" }}>
                  <span>{strings.requirements.unlinkActionViaChangeRequestConfirm}</span>
                  <label className="stack" style={{ gap: "0.25rem" }}>
                    {strings.changeRequests.reason}
                    <textarea
                      className="input" rows={2} aria-label={strings.changeRequests.reason}
                      value={unlinkActionReason} onChange={(e) => setUnlinkActionReason(e.target.value)}
                    />
                  </label>
                </span>
              ) : (
                strings.requirements.unlinkActionConfirm
              )
            }
            confirmLabel={strings.requirements.unlinkAction}
            confirmDisabled={requirement.is_locked && !unlinkActionReason.trim()}
            onConfirm={async () => {
              const id = actionToUnlink.id;
              const reason = unlinkActionReason;
              setActionToUnlink(null);
              await unlinkAction(id, reason);
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
            <PrincipalFormField
              label={strings.actions.assignee}
              orgUsers={orgUsers}
              organizationId={organizationId ?? undefined}
              projectId={projectId}
              value={newActionAssignee}
              onChange={setNewActionAssignee}
              ariaLabel={strings.actions.assignee}
            />
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
    </DetailLayout>
  );
}
