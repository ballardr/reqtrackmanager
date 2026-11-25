/**
 * Module: modules/context_strategy/FutureStateDetailPage
 *
 * A single Future State's full detail: fields (including `target_date`), lifecycle status, versions, comments,
 * attachments, relationships and every lifecycle action. Its structure mirrors `StrategyDetailPage.tsx` field for
 * field, because the backend model mirrors Strategy's (same seven-state lifecycle, lock rule past `UNDER_REVIEW`,
 * owner/approver RBAC).
 *
 * Scope-aware: a Future State is organisation- or project-scoped, so one component serves both
 * `ProjectFutureStatesPage.tsx` and `OrgFutureStatesPanel.tsx` (`module.ts`'s `globalRoutes`, not gated by a project's
 * enabled modules).
 *
 * Mutating controls always render whatever the caller's role; the backend enforces `future_state_owner` /
 * `future_state_approver` (or the organisation equivalents) and a 403 surfaces as a toast. Content edit, archive and
 * file-attach controls are hidden once `futureState.is_locked`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgFutureStateApi, projectFutureStateApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { FUTURE_STATE_STATUS_LABEL, FUTURE_STATE_STATUS_TONE, FUTURE_STATE_STATUS_DESCRIPTION, REVIEWED_LOCKED_REASON } from "./types";
import type { FutureState, FutureStateComment, FutureStateFieldValues, FutureStateVersion } from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { lifecycleSteps } from "../../components/lifecycleSteps";
import { useApprovalStatus } from "../../hooks/useApprovalStatus";
import { useProjectLifecycle } from "../../hooks/useProjectLifecycle";
import { useSkipSteps } from "../../components/useSkipSteps";
import { withLifecycleSkip } from "../../api/client";
import type { LifecyclePromote } from "../../components/LifecycleTrack";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { RecordField } from "../../components/RecordDetailParts";
import { orgResourcesPath } from "../orgResources";
import { ORG_FUTURE_STATES_SECTION_KEY } from "./orgResourceKeys";

/** Every lifecycle action this page offers; keys the confirm-dialog copy, as `StrategyDetailPage.tsx`'s `TRANSITION_COPY` does. */
type TransitionAction = "approve" | "activate" | "supersede" | "retire";

const TRANSITION_COPY: Record<TransitionAction, { title: string; body: string; confirmLabel: string }> = {
  approve: {
    title: "Approve this Future State?",
    body: "This records a formal approval in the audit trail. A comment is optional.",
    confirmLabel: "Approve",
  },
  activate: {
    title: "Activate this Future State?",
    body: "This marks the Future State as currently in force. A comment is optional.",
    confirmLabel: "Activate",
  },
  supersede: {
    title: "Supersede this Future State?",
    body: "This Future State will be marked Superseded. A comment is optional. To record which Future State replaces it, use the Relationships section's \"Supersedes another Future State\" option instead.",
    confirmLabel: "Supersede",
  },
  retire: {
    title: "Retire this Future State?",
    body: "This marks the Future State's lifecycle as ended. A comment is optional.",
    confirmLabel: "Retire",
  },
};

const MAIN_PATH = ["draft", "proposed", "under_review", "approved", "active"] as const;

export function FutureStateDetailPage() {
  const { projectId, organizationId, futureStateId } = useParams<{
    projectId?: string;
    organizationId?: string;
    futureStateId: string;
  }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectFutureStateApi : orgFutureStateApi;
  const scopeId = projectId ?? organizationId;
  const backLink = projectId
    ? `/projects/${projectId}/modules/context_strategy/future-states`
    : organizationId ? orgResourcesPath(organizationId, ORG_FUTURE_STATES_SECTION_KEY) : "/org-resources";

  const [futureState, setFutureState] = useState<FutureState | null>(null);
  const lifecycle = useProjectLifecycle(projectId, "future_state");
  const approval = useApprovalStatus(
    projectId ? { projectId } : organizationId ? { organizationId } : null, "future_state", futureState?.id, futureState?.status,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<FutureStateVersion[] | null>(null);
  const [comments, setComments] = useState<FutureStateComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [sendingBack, setSendingBack] = useState(false);
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);

  useEffect(() => {
    if (!scopeId || !futureStateId) return;
    scopedApi.get(scopeId, futureStateId).then(setFutureState).catch((err) => {
      setLoadError(toErrorMessage(err, "This Future State could not be found, or you do not have access to it."));
    });
    scopedApi.listVersions(scopeId, futureStateId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, futureStateId]);

  async function reloadCommentsAndFiles() {
    if (!scopeId || !futureStateId) return;
    try {
      const [c, f] = await Promise.all([
        scopedApi.listComments(scopeId, futureStateId),
        scopedApi.listFiles(scopeId, futureStateId),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Future State's comments/files."), "error");
    }
  }

  useLoadOnChange(reloadCommentsAndFiles, [scopeId, futureStateId]);

  async function runTransition(action: () => Promise<FutureState>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setFutureState(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Future State."), "error");
    }
  }

  async function saveEdit(values: FutureStateFieldValues) {
    if (!scopeId || !futureState) return;
    setFormError(null);
    try {
      const updated = await scopedApi.update(scopeId, futureState.id, values);
      showToast("Future State updated.");
      setEditing(false);
      setFutureState(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Future State."));
    }
  }

  const archive = useArchiveAction({
    noun: "Future State",
    isArchived: futureState?.is_archived ?? false,
    hidden: !futureState,
    archiveBody: "This Future State will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!scopeId || !futureState) return;
      await runTransition(
        () => (futureState.is_archived ? scopedApi.unarchive(scopeId, futureState.id) : scopedApi.archive(scopeId, futureState.id)),
        futureState.is_archived ? "Future State unarchived." : "Future State archived.",
      );
    },
  });

  const codeOwner = useRecordOwnerCode(futureState ?? {});
  const skipSteps = useSkipSteps<FutureState>({
    lifecycle, current: futureState?.status ?? "", labels: FUTURE_STATE_STATUS_LABEL, noun: "Future State",
    move: (target, reason) => {
      if (!scopeId || !futureState) return Promise.reject(new Error("This move is not available."));
      if (target === "under_review") return withLifecycleSkip(reason, () => scopedApi.submitForReview(scopeId, futureState.id));
      if (target === "approved") return withLifecycleSkip(reason, () => scopedApi.approve(scopeId, futureState.id));
      return Promise.reject(new Error("This move is not available."));
    },
    onMoved: setFutureState,
  });

  if (!scopeId || !futureStateId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (futureState === null) return <Spinner />;

  /** Attaches a file to this record: the Attachments card and the Markdown fields' Picture button share it. */
  const uploadAttachment = async (file: File): Promise<FileAsset> => {
    const asset = await scopedApi.uploadFile(scopeId, futureState.id, file);
    setFiles((prev) => [...prev, asset]);
    return asset;
  };

  // The next forward move: a plain call, or the comment dialog of the approval and activation steps.
  // It goes to the next step the project uses (a project may turn Proposed and Under review off).
  const next = lifecycle.nextOnPath(MAIN_PATH, futureState.status);
  let promote: LifecyclePromote | undefined;
  if (next === "proposed") {
    promote = { to: "proposed", onPromote: () => runTransition(() => scopedApi.propose(scopeId, futureState.id), "Future State proposed.") };
  } else if (next === "under_review") {
    promote = { to: "under_review", onPromote: () => runTransition(() => scopedApi.submitForReview(scopeId, futureState.id), "Future State submitted for review.") };
  } else if (next === "approved") {
    promote = approval.approve("approved", () => setTransitionAction("approve"));
  } else if (next === "active") {
    promote = { to: "active", onPromote: () => setTransitionAction("activate") };
  }

  // An ended Future State sits after the last main step it reached: any retired one was approved, and was active if a version says so.
  const offPath = futureState.status === "superseded" || futureState.status === "retired"
    ? {
        key: futureState.status,
        label: FUTURE_STATE_STATUS_LABEL[futureState.status],
        description: FUTURE_STATE_STATUS_DESCRIPTION[futureState.status],
        locked: true,
        lockedReason: REVIEWED_LOCKED_REASON,
        after: futureState.status === "superseded" || versions?.some((v) => v.status === "active") ? "active" : "approved",
      }
    : undefined;

  return (
    <DetailLayout
      pictures={{ files, upload: futureState.is_locked ? undefined : uploadAttachment }}
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="future_state" artefactId={futureState.id} refreshToken={recordActivityKey(futureState)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="future_state"
          artefactId={futureState.id}
          actions={({ reload }) => (
            <SupersedeAction
              artefactLabel="Future State"
              onDone={reload}
              loadCandidates={async () =>
                (await scopedApi.list(scopeId))
                  .filter((other) => other.id !== futureState.id)
                  .map((other) => ({ id: other.id, label: other.title }))
              }
              onSupersede={async (oldId) => {
                await scopedApi.createSupersessionLink(scopeId, futureState.id, oldId);
              }}
            />
          )}
        />
      }
    >
      <RecordHeader
        recordLabel="Future State"
        title={futureState.title}
        code={futureState.unique_code}
        approval={approval.status}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="future_state" artefactId={futureState.id} /> : undefined}
        codeOwner={codeOwner}
        back={{ to: backLink, label: "Future States" }}
        badges={
          <>
          <Badge tone={FUTURE_STATE_STATUS_TONE[futureState.status]}>
            {FUTURE_STATE_STATUS_LABEL[futureState.status]}
          </Badge>
          </>
        }
        version={futureState.version_number}
        subtitle={futureState.target_date ? `Target date ${futureState.target_date}` : undefined}
        onEdit={futureState.is_locked ? undefined : () => setEditing(true)}
        actions={[
          skipSteps.menuRow,
          lifecycle.canMove(futureState.status, "draft", futureState.status === "proposed" || futureState.status === "under_review") && { label: "Send back", onSelect: () => setSendingBack(true) },
          futureState.status === "active" && { label: "Supersede", onSelect: () => setTransitionAction("supersede") },
          futureState.status === "active" && { label: "Retire", danger: true, onSelect: () => setTransitionAction("retire") },
          archive.item,
        ]}
        lifecycle={{
          steps: lifecycle.visibleSteps(
            lifecycleSteps(MAIN_PATH, FUTURE_STATE_STATUS_LABEL, { descriptions: FUTURE_STATE_STATUS_DESCRIPTION, locked: { approved: REVIEWED_LOCKED_REASON, active: REVIEWED_LOCKED_REASON } }),
            futureState.status,
          ),
          current: futureState.status,
          offPath,
          promote,
          skip: skipSteps.track,
        }}
      />
      {archive.dialog}


        <DetailCard>
          {futureState.current_state && <RecordField markdown label="Current state" value={futureState.current_state} />}
          <RecordField markdown label="Desired state" value={futureState.desired_state} />
          {futureState.outcomes && <RecordField markdown label="Outcomes" value={futureState.outcomes} />}
          {futureState.success_measures && <RecordField markdown label="Success measures" value={futureState.success_measures} />}
          {futureState.constraints && <RecordField markdown label="Constraints" value={futureState.constraints} />}
          {futureState.assumptions && <RecordField markdown label="Assumptions" value={futureState.assumptions} />}
        </DetailCard>


        {versions && versions.length > 1 && (
          <DetailCard heading="Versions" rank="supporting">
            <table className="table">
              <thead>
                <tr><th>Version</th><th>Status</th><th>Changed</th><th>Change note</th></tr>
              </thead>
              <tbody>
                {[...versions].reverse().map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_number}</td>
                    <td>{FUTURE_STATE_STATUS_LABEL[v.status]}</td>
                    <td>{new Date(v.valid_from).toLocaleString()}</td>
                    <td>{v.change_note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DetailCard>
        )}

        <DetailCard heading="Attachments" rank="supporting">
          <FileAttachmentList
            files={files}
            disabled={futureState.is_locked}
            emptyHint={futureState.is_locked ? "This Future State is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => { await uploadAttachment(file); }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, futureState.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

        <ArtefactCommentsSection
          comments={comments ?? []}
          currentUserId={user?.id}
          onPost={async (body) => {
            const comment = await scopedApi.addComment(scopeId, futureState.id, body);
            setComments((prev) => [...(prev ?? []), comment]);
            return comment;
          }}
          onEdit={async (commentId, body) => {
            const updated = await scopedApi.editComment(scopeId, futureState.id, commentId, body);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
          }}
          onUploadAttachment={async (commentId, file) => {
            const asset = await scopedApi.uploadCommentAttachment(scopeId, futureState.id, commentId, file);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
          }}
          onRemoveAttachment={async (commentId, fileId) => {
            await scopedApi.removeCommentAttachment(scopeId, futureState.id, commentId, fileId);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
          }}
        />

      {editing && (
        <FutureStateFormModal
          initial={futureState}
          scopeLabel={projectId ? "project" : "organisation"}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {skipSteps.dialog}

      {sendingBack && (
        <CommentConfirmDialog
          title="Send this Future State back to Draft?"
          intro="A comment explaining what needs rework is required."
          commentLabel="Send-back comment"
          commentRequired
          confirmLabel="Send back"
          onConfirm={async (comment) => {
            setSendingBack(false);
            await runTransition(() => scopedApi.sendBack(scopeId, futureState.id, comment), "Future State sent back to draft.");
          }}
          onCancel={() => setSendingBack(false)}
        />
      )}

      {transitionAction && (
        <CommentConfirmDialog
          title={TRANSITION_COPY[transitionAction].title}
          intro={TRANSITION_COPY[transitionAction].body}
          ariaLabel="Transition comment"
          confirmLabel={TRANSITION_COPY[transitionAction].confirmLabel}
          onConfirm={async (comment) => {
            const action = transitionAction;
            setTransitionAction(null);
            await runTransition(() => scopedApi[action](scopeId, futureState.id, comment), `Future State ${TRANSITION_COPY[action].confirmLabel.toLowerCase()}d.`);
          }}
          onCancel={() => setTransitionAction(null)}
        />
      )}

    </DetailLayout>
  );
}
