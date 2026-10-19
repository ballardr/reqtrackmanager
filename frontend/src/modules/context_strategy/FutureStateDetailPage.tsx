/**
 * Module: modules/context_strategy/FutureStateDetailPage
 *
 * A single Future State's full detail — full field display (including `target_date`),
 * current lifecycle status, version history, comments, attachments, and
 * relationships, plus every lifecycle action. Mirrors
 * `StrategyDetailPage.tsx`'s exact structure field-for-field, since Future
 * State's backend is itself "an exact structural mirror" of Strategy's
 * — same seven-state lifecycle, same lock rule
 * (past `UNDER_REVIEW`), same owner/approver RBAC shape, same comments/
 * attachments/relationships sections.
 *
 * **Scope-aware, Decided by: Agent**, for the exact same reason
 * `StrategyDetailPage.tsx` is: a Future State is org- **or** project-scoped,
 * so this one component serves both
 * `ProjectFutureStatesPage.tsx`'s row-click navigation and
 * `OrgFutureStatesPanel.tsx`'s own (`module.ts`'s `globalRoutes`, org-scoped,
 * not gated by any one project's own enabled-modules list).
 *
 * Every mutating control always renders regardless of the caller's actual
 * role (same posture `StrategyDetailPage.tsx` establishes) — the backend
 * enforces `future_state_owner`/`future_state_approver` (or their org-scoped
 * equivalents) and a 403 surfaces as a toast. Edit/archive/file-attach
 * controls specifically for *content* are hidden (not just toast-blocked)
 * once `futureState.is_locked`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgFutureStateApi, projectFutureStateApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { FUTURE_STATE_STATUS_LABEL, FUTURE_STATE_STATUS_TONE } from "./types";
import type { FutureState, FutureStateComment, FutureStateFieldValues, FutureStateVersion } from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { TextAreaField } from "../../components/FormFields";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";

/** Every lifecycle action this page can offer, keyed by the action itself —
 * used to build the confirm-dialog copy generically instead of repeating it
 * per call site. Exact mirror of `StrategyDetailPage.tsx`'s own
 * `TransitionAction`/`TRANSITION_COPY`. */
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
    : `/org-overview`;
  const backLabel = projectId ? "← Future State" : "← Organisation overview";

  const [futureState, setFutureState] = useState<FutureState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<FutureStateVersion[] | null>(null);
  const [comments, setComments] = useState<FutureStateComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [sendingBack, setSendingBack] = useState(false);
  const [sendBackComment, setSendBackComment] = useState("");
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);
  const [transitionComment, setTransitionComment] = useState("");

  useEffect(() => {
    if (!scopeId || !futureStateId) return;
    scopedApi.get(scopeId, futureStateId).then(setFutureState).catch((err) => {
      setLoadError(toErrorMessage(err, "This Future State could not be found, or you don't have access to it."));
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
  if (!scopeId || !futureStateId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (futureState === null) return <Spinner />;

  return (
    <DetailLayout
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="future_state" artefactId={futureState.id} /> : undefined}
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
        codeOwner={codeOwner}
        back={{ to: backLink, label: backLabel }}
        badges={
          <>
          <Badge tone={FUTURE_STATE_STATUS_TONE[futureState.status]}>
            {FUTURE_STATE_STATUS_LABEL[futureState.status]}
          </Badge>
          </>
        }
        subtitle={
          <>
            {futureState.target_date ? `Target date ${futureState.target_date} · ` : ""}v{futureState.version_number}
          </>
        }
        onEdit={futureState.is_locked ? undefined : () => setEditing(true)}
        actions={[archive.item]}
        transitions={
          <>
          {futureState.status === "draft" && (
            <button className="btn btn-primary" onClick={() => runTransition(() => scopedApi.propose(scopeId, futureState.id), "Future State proposed.")}>
              Propose
            </button>
          )}
          {futureState.status === "proposed" && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => runTransition(() => scopedApi.submitForReview(scopeId, futureState.id), "Future State submitted for review.")}
              >
                Submit for review
              </button>
              <button className="btn" onClick={() => setSendingBack(true)}>Send back</button>
            </>
              )}
              {futureState.status === "under_review" && (
                <>
                  <button className="btn btn-primary" onClick={() => setTransitionAction("approve")}>Approve</button>
                  <button className="btn" onClick={() => setSendingBack(true)}>Send back</button>
                </>
              )}
              {futureState.status === "approved" && (
                <button className="btn btn-primary" onClick={() => setTransitionAction("activate")}>Activate</button>
              )}
              {futureState.status === "active" && (
                <>
                  <button className="btn" onClick={() => setTransitionAction("supersede")}>Supersede</button>
                  <button className="btn btn-danger" onClick={() => setTransitionAction("retire")}>Retire</button>
                </>
              )}
          </>
        }
      />
      {archive.dialog}

      <div className="stack">

        {futureState.current_state && <Field label="Current state" value={futureState.current_state} />}
        <Field label="Desired state" value={futureState.desired_state} />
        {futureState.outcomes && <Field label="Outcomes" value={futureState.outcomes} />}
        {futureState.success_measures && <Field label="Success measures" value={futureState.success_measures} />}
        {futureState.constraints && <Field label="Constraints" value={futureState.constraints} />}
        {futureState.assumptions && <Field label="Assumptions" value={futureState.assumptions} />}


        {versions && versions.length > 1 && (
          <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Versions</h3>
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
          </div>
        )}

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Attachments</h3>
          <FileAttachmentList
            files={files}
            disabled={futureState.is_locked}
            emptyHint={futureState.is_locked ? "This Future State is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await scopedApi.uploadFile(scopeId, futureState.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, futureState.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </div>

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
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
        </div>
      </div>

      {editing && (
        <FutureStateFormModal
          initial={futureState}
          scopeLabel={projectId ? "project" : "organisation"}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {sendingBack && (
        <ConfirmDialog
          title="Send this Future State back to Draft?"
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>A comment explaining what needs rework is required.</span>
              <TextAreaField label="Send-back comment" value={sendBackComment} onChange={setSendBackComment} rows={2} />
            </span>
          }
          confirmLabel="Send back"
          confirmDisabled={!sendBackComment.trim()}
          onConfirm={async () => {
            setSendingBack(false);
            const comment = sendBackComment;
            setSendBackComment("");
            await runTransition(() => scopedApi.sendBack(scopeId, futureState.id, comment), "Future State sent back to draft.");
          }}
          onCancel={() => { setSendingBack(false); setSendBackComment(""); }}
        />
      )}

      {transitionAction && (
        <ConfirmDialog
          title={TRANSITION_COPY[transitionAction].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{TRANSITION_COPY[transitionAction].body}</span>
              <TextAreaField
                label="Comment"
                ariaLabel="Transition comment"
                value={transitionComment}
                onChange={setTransitionComment}
                rows={2}
              />
            </span>
          }
          confirmLabel={TRANSITION_COPY[transitionAction].confirmLabel}
          onConfirm={async () => {
            const action = transitionAction;
            const comment = transitionComment;
            setTransitionAction(null);
            setTransitionComment("");
            await runTransition(() => scopedApi[action](scopeId, futureState.id, comment), `Future State ${TRANSITION_COPY[action].confirmLabel.toLowerCase()}d.`);
          }}
          onCancel={() => { setTransitionAction(null); setTransitionComment(""); }}
        />
      )}

    </DetailLayout>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}
