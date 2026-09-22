/**
 * Module: modules/decisions/DecisionDetailPage
 *
 * A single Decision's full detail — management and full context — as its
 * own routed page (`/projects/:projectId/modules/decisions/:decisionId`,
 * `module.ts`), replacing the `SidePanel`-only `DecisionDetailPanel.tsx`
 * (Phase 9, 2026-09-22). `docs/ux-style-guide.md`'s "Pattern: entity detail
 * panel" checklist called for a page here: a Decision's detail carries a
 * comment thread, file attachments, a relationships section, and 3+
 * lifecycle actions each with their own `ConfirmDialog` — all four of the
 * checklist's "too much for a SidePanel" markers. `ProjectDecisionsPage
 * .tsx`'s list opens `DecisionQuickViewPanel` (a minimal read-only peek) on
 * row click instead; that panel's own "View full details" link is what
 * lands here.
 *
 * Fetches its own data on mount (`project`, `orgUsers`, `decisionTypes`,
 * and the `Decision` itself via `decisionsApi.getDecision`) — the same
 * self-contained-page shape `RequirementDetailPage.tsx` already uses,
 * appropriate now that this is a real, bookmarkable/deep-linkable route
 * rather than a panel handed data by its parent list page.
 *
 * Every mutating control always renders regardless of the caller's actual
 * role (same posture `DecisionDetailPanel.tsx` established — see
 * `ProjectCompliancePage.tsx`'s own docstring for the precedent) — the
 * backend enforces `decision_owner`/`decision_approver` and a 403 surfaces
 * as a toast. Edit/archive/file-attach controls specifically for *content*
 * are hidden (not just toast-blocked) once `decision.is_locked`.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionCommentsSection } from "./DecisionCommentsSection";
import { DecisionFormModal } from "./DecisionFormModal";
import { DecisionRelationshipsSection } from "./DecisionRelationshipsSection";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionComment, DecisionFieldValues, DecisionTypeDefinition } from "./types";
import type { FileAsset } from "../../api/types";

export function DecisionDetailPage() {
  const { projectId, decisionId } = useParams<{ projectId: string; decisionId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [decisionTypes, setDecisionTypes] = useState<DecisionTypeDefinition[]>([]);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveComment, setApproveComment] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);
  const [comments, setComments] = useState<DecisionComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  useEffect(() => {
    if (!projectId || !decisionId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers);
    });
    decisionsApi.listDecisionTypes(projectId).then(setDecisionTypes);
    decisionsApi.getDecision(projectId, decisionId).then(setDecision).catch((err) => {
      setLoadError(toErrorMessage(err, "This Decision could not be found, or you don't have access to it."));
    });
  }, [projectId, decisionId]);

  async function reloadCommentsAndFiles() {
    if (!projectId || !decisionId) return;
    try {
      const [c, f] = await Promise.all([
        decisionsApi.listDecisionComments(projectId, decisionId),
        decisionsApi.listDecisionFiles(projectId, decisionId),
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
  }, [projectId, decisionId]);

  async function runTransition(action: () => Promise<Decision>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setDecision(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Decision."), "error");
    }
  }

  async function saveEdit(values: DecisionFieldValues) {
    if (!projectId || !decision) return;
    setFormError(null);
    try {
      const updated = await decisionsApi.updateDecision(projectId, decision.id, values);
      showToast("Decision updated.");
      setEditing(false);
      setDecision(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Decision."));
    }
  }

  if (!projectId || !decisionId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decision === null || project === null) return <Spinner />;

  const decisionType = decisionTypes.find((t) => t.id === decision.decision_type_id);
  const userOptions = orgUsers.map((u) => ({ id: u.user_id, display_name: u.display_name }));

  return (
    <div className="container stack">
      <Link to={`/projects/${projectId}/modules/decisions`}>← Decisions</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{decision.unique_code}</h1>
        <span className={`badge badge--${DECISION_STATUS_TONE[decision.status]}`}>
          {DECISION_STATUS_LABEL[decision.status]}
        </span>
      </div>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>{decision.title}</h2>
          {!decision.is_locked && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>
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

        <DecisionRelationshipsSection projectId={projectId} decision={decision} onChanged={() => setDecision(decision)} />

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
            currentUserId={user?.id}
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
          currentUserId={user?.id}
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
    </div>
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
