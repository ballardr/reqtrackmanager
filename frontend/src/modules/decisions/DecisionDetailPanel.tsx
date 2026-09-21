/**
 * Module: modules/decisions/DecisionDetailPanel
 *
 * A single Decision's detail view — rendered in a `SidePanel` by
 * `ProjectDecisionsPage.tsx` (style guide's 2026-08-24 revision: `SidePanel`
 * is for viewing/editing an *existing* entity in context of the list behind
 * it; creation uses `Modal` instead — `DecisionFormModal` is shared by both
 * via its `initial` prop). Shows the Decision's fields, its lifecycle
 * action buttons (propose/submit-for-review/approve/reject, gated by
 * `status`), archive/unarchive, its relationships
 * (`DecisionRelationshipsSection`), comments (`DecisionCommentsSection`),
 * and direct file attachments (`FileAttachmentList`).
 *
 * Every mutating control always renders regardless of the caller's actual
 * role — the backend enforces `decision_owner`/`decision_approver` and a
 * 403 surfaces as a toast — the same "no client-side can-i-manage
 * precomputation" posture `ProjectCompliancePage.tsx`'s own module
 * docstring establishes (no "my effective roles including module roles"
 * endpoint exists to check against without adding one). Edit/archive/file-
 * attach controls specifically for *content* are hidden (not just
 * toast-blocked) once `decision.is_locked`, since that's a real, always-true
 * state the client already has — the same distinction `RequirementDetailPage
 * .tsx`'s own lock-after-approval UI already draws between "might be
 * forbidden, ask the server" and "is definitely forbidden, don't even ask."
 */
import { useEffect, useState } from "react";
import { Pencil } from "lucide-react";

import type { OrgUser } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { SidePanel } from "../../components/SidePanel";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionCommentsSection } from "./DecisionCommentsSection";
import { DecisionFormModal } from "./DecisionFormModal";
import { DecisionRelationshipsSection } from "./DecisionRelationshipsSection";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionComment, DecisionFieldValues, DecisionTypeDefinition } from "./types";
import type { FileAsset } from "../../api/types";

export function DecisionDetailPanel({
  projectId,
  decision,
  decisionTypes,
  orgUsers,
  currentUserId,
  onClose,
  onChanged,
}: {
  projectId: string;
  decision: Decision;
  decisionTypes: DecisionTypeDefinition[];
  orgUsers: OrgUser[];
  currentUserId?: string;
  onClose: () => void;
  /** Called with the fresh `Decision` after any successful mutation — the
   * caller (`ProjectDecisionsPage.tsx`) owns the canonical list and this
   * panel's own `decision` prop, so this panel never mutates its own copy
   * directly. */
  onChanged: (updated: Decision) => void;
}) {
  const { showToast } = useToast();
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveComment, setApproveComment] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);
  const [comments, setComments] = useState<DecisionComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const decisionType = decisionTypes.find((t) => t.id === decision.decision_type_id);
  const userOptions = orgUsers.map((u) => ({ id: u.user_id, display_name: u.display_name }));

  async function reloadCommentsAndFiles() {
    try {
      const [c, f] = await Promise.all([
        decisionsApi.listDecisionComments(projectId, decision.id),
        decisionsApi.listDecisionFiles(projectId, decision.id),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Decision's comments/files."), "error");
    }
  }

  useEffect(() => {
    void reloadCommentsAndFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, decision.id]);

  async function runTransition(action: () => Promise<Decision>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      onChanged(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Decision."), "error");
    }
  }

  async function saveEdit(values: DecisionFieldValues) {
    setFormError(null);
    try {
      const updated = await decisionsApi.updateDecision(projectId, decision.id, values);
      showToast("Decision updated.");
      setEditing(false);
      onChanged(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Decision."));
    }
  }

  return (
    <SidePanel title={decision.unique_code} onClose={onClose}>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span className={`badge badge--${DECISION_STATUS_TONE[decision.status]}`}>
            {DECISION_STATUS_LABEL[decision.status]}
          </span>
          {!decision.is_locked && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>
        <h2 style={{ margin: 0 }}>{decision.title}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{decisionType?.name ?? "—"}</p>
        <p style={{ margin: 0 }}>{decision.decision_statement}</p>

        {decision.context && <Field label="Context" value={decision.context} />}
        {decision.options_considered && <Field label="Options considered" value={decision.options_considered} />}
        {decision.chosen_option && <Field label="Chosen option" value={decision.chosen_option} />}
        {decision.rationale && <Field label="Rationale" value={decision.rationale} />}
        {decision.consequences && <Field label="Consequences" value={decision.consequences} />}
        {decision.assumptions && <Field label="Assumptions" value={decision.assumptions} />}
        {decision.constraints && <Field label="Constraints" value={decision.constraints} />}

        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
          {decision.status === "draft" && (
            <button className="btn btn-primary" onClick={() => runTransition(() => decisionsApi.proposeDecision(projectId, decision.id), "Decision proposed.")}>
              Propose
            </button>
          )}
          {decision.status === "proposed" && (
            <button
              className="btn btn-primary"
              onClick={() => runTransition(() => decisionsApi.submitDecisionForReview(projectId, decision.id), "Decision submitted for review.")}
            >
              Submit for review
            </button>
          )}
          {decision.status === "under_review" && (
            <>
              <button className="btn btn-primary" onClick={() => setApproving(true)}>Approve</button>
              <button className="btn btn-danger" onClick={() => setRejecting(true)}>Reject</button>
            </>
          )}
          <button className="btn" onClick={() => setArchiveConfirm(true)}>
            {decision.is_archived ? "Unarchive" : "Archive"}
          </button>
        </div>

        <DecisionRelationshipsSection projectId={projectId} decision={decision} onChanged={() => onChanged(decision)} />

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Attachments</h3>
          <FileAttachmentList
            files={files}
            disabled={decision.is_locked}
            emptyHint={decision.is_locked ? "This Decision is approved or superseded; new attachments can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await decisionsApi.uploadDecisionFile(projectId, decision.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await decisionsApi.unlinkDecisionFile(projectId, decision.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </div>

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <DecisionCommentsSection
            comments={comments ?? []}
            currentUserId={currentUserId}
            onPost={async (body) => {
              const comment = await decisionsApi.addDecisionComment(projectId, decision.id, body);
              setComments((prev) => [...(prev ?? []), comment]);
              return comment;
            }}
            onEdit={async (commentId, body) => {
              const updated = await decisionsApi.editDecisionComment(projectId, decision.id, commentId, body);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
            }}
            onUploadAttachment={async (commentId, file) => {
              const asset = await decisionsApi.uploadDecisionCommentAttachment(projectId, decision.id, commentId, file);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
            }}
            onRemoveAttachment={async (commentId, fileId) => {
              await decisionsApi.removeDecisionCommentAttachment(projectId, decision.id, commentId, fileId);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
            }}
          />
        </div>
      </div>

      {editing && (
        <DecisionFormModal
          initial={decision}
          decisionTypes={decisionTypes}
          userOptions={userOptions}
          currentUserId={currentUserId}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {approving && (
        <ConfirmDialog
          title="Approve this Decision?"
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>This records a formal approval in the audit trail. A comment is optional.</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Approval comment
                <textarea
                  className="input" rows={2} aria-label="Approval comment"
                  value={approveComment} onChange={(e) => setApproveComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel="Approve"
          onConfirm={async () => {
            setApproving(false);
            const comment = approveComment;
            setApproveComment("");
            await runTransition(() => decisionsApi.approveDecision(projectId, decision.id, comment), "Decision approved.");
          }}
          onCancel={() => { setApproving(false); setApproveComment(""); }}
        />
      )}

      {rejecting && (
        <ConfirmDialog
          title="Reject this Decision?"
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>A comment explaining the rejection is required.</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Rejection comment
                <textarea
                  className="input" rows={2} aria-label="Rejection comment"
                  value={rejectComment} onChange={(e) => setRejectComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel="Reject"
          confirmDisabled={!rejectComment.trim()}
          onConfirm={async () => {
            setRejecting(false);
            const comment = rejectComment;
            setRejectComment("");
            await runTransition(() => decisionsApi.rejectDecision(projectId, decision.id, comment), "Decision rejected.");
          }}
          onCancel={() => { setRejecting(false); setRejectComment(""); }}
        />
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={decision.is_archived ? "Unarchive this Decision?" : "Archive this Decision?"}
          message={
            decision.is_archived
              ? "This Decision will count as active again."
              : "This Decision will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes."
          }
          confirmLabel={decision.is_archived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await runTransition(
              () => (decision.is_archived ? decisionsApi.unarchiveDecision(projectId, decision.id) : decisionsApi.archiveDecision(projectId, decision.id)),
              decision.is_archived ? "Decision unarchived." : "Decision archived."
            );
          }}
          onCancel={() => setArchiveConfirm(false)}
        />
      )}
    </SidePanel>
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
