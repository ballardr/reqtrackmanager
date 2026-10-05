/**
 * Module: modules/context_strategy/StrategyDetailPage
 *
 * A single Strategy's full detail (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 7.1) — full field display, current lifecycle
 * status, version history, comments, attachments, and relationships, plus
 * every lifecycle action. Mirrors `modules/decisions/DecisionDetailPage.tsx`'s
 * exact structure and its `docs/ux-style-guide.md` "Pattern: entity detail
 * panel" reasoning for being a real routed page rather than a `SidePanel`:
 * a comment thread, file attachments, a relationships section, and several
 * lifecycle actions each with their own `ConfirmDialog` are all present
 * here too.
 *
 * **Scope-aware, Decided by: Agent:** unlike Decision (project-scoped
 * only), a Strategy is org- **or** project-scoped (Phase 0 Q2), so this one
 * component serves both `ProjectStrategiesPage.tsx`'s row-click navigation
 * (`/projects/:projectId/modules/context_strategy/strategies/:strategyId`,
 * registered via `module.ts`'s `routes`) and `OrgStrategiesPanel.tsx`'s own
 * (`/orgs/:organizationId/modules/context_strategy/strategies/:strategyId`,
 * registered via `module.ts`'s `globalRoutes` — org-scoped, not gated by
 * any one project's own enabled-modules list, the same reasoning Compliance's
 * Standards detail route already established for a cross-cutting entity)
 * — exactly one of `projectId`/`organizationId` route params is present at
 * a time, mirroring the backend's own scope discriminator exactly, rather
 * than building two near-identical page components.
 *
 * Every mutating control always renders regardless of the caller's actual
 * role (same posture `DecisionDetailPage.tsx` establishes) — the backend
 * enforces `strategy_owner`/`strategy_approver` (or their org-scoped
 * equivalents) and a 403 surfaces as a toast. Edit/archive/file-attach
 * controls specifically for *content* are hidden (not just toast-blocked)
 * once `strategy.is_locked`.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";

import type { FileAsset } from "../../api/types";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStrategyApi, projectStrategyApi } from "./api";
import { StrategyFormModal } from "./StrategyFormModal";
import { StrategyRelationshipsSection } from "./StrategyRelationshipsSection";
import { STRATEGY_PRIORITY_LABEL, STRATEGY_STATUS_LABEL, STRATEGY_STATUS_TONE, STRATEGY_TIME_HORIZON_LABEL } from "./types";
import type { Strategy, StrategyComment, StrategyFieldValues, StrategyVersion } from "./types";

/** Every lifecycle action this page can offer, keyed by the action itself —
 * used to build the confirm-dialog copy generically instead of repeating it
 * per call site. */
type TransitionAction = "approve" | "activate" | "supersede" | "retire";

const TRANSITION_COPY: Record<TransitionAction, { title: string; body: string; confirmLabel: string }> = {
  approve: {
    title: "Approve this Strategy?",
    body: "This records a formal approval in the audit trail. A comment is optional.",
    confirmLabel: "Approve",
  },
  activate: {
    title: "Activate this Strategy?",
    body: "This marks the Strategy as currently in force. A comment is optional.",
    confirmLabel: "Activate",
  },
  supersede: {
    title: "Supersede this Strategy?",
    body: "This Strategy will be marked Superseded. A comment is optional. To record which Strategy replaces it, use the Relationships section's \"Supersedes another Strategy\" option instead.",
    confirmLabel: "Supersede",
  },
  retire: {
    title: "Retire this Strategy?",
    body: "This marks the Strategy's lifecycle as ended. A comment is optional.",
    confirmLabel: "Retire",
  },
};

export function StrategyDetailPage() {
  const { projectId, organizationId, strategyId } = useParams<{
    projectId?: string;
    organizationId?: string;
    strategyId: string;
  }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectStrategyApi : orgStrategyApi;
  const scopeId = projectId ?? organizationId;
  const backLink = projectId
    ? `/projects/${projectId}/modules/context_strategy/strategies`
    : `/org-overview`;
  const backLabel = projectId ? "← Strategy" : "← Organisation overview";

  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null);
  const [comments, setComments] = useState<StrategyComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [sendingBack, setSendingBack] = useState(false);
  const [sendBackComment, setSendBackComment] = useState("");
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);
  const [transitionComment, setTransitionComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);

  useEffect(() => {
    if (!scopeId || !strategyId) return;
    scopedApi.get(scopeId, strategyId).then(setStrategy).catch((err) => {
      setLoadError(toErrorMessage(err, "This Strategy could not be found, or you don't have access to it."));
    });
    scopedApi.listVersions(scopeId, strategyId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, strategyId]);

  async function reloadCommentsAndFiles() {
    if (!scopeId || !strategyId) return;
    try {
      const [c, f] = await Promise.all([
        scopedApi.listComments(scopeId, strategyId),
        scopedApi.listFiles(scopeId, strategyId),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Strategy's comments/files."), "error");
    }
  }

  useEffect(() => {
    void reloadCommentsAndFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, strategyId]);

  async function runTransition(action: () => Promise<Strategy>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setStrategy(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Strategy."), "error");
    }
  }

  async function saveEdit(values: StrategyFieldValues) {
    if (!scopeId || !strategy) return;
    setFormError(null);
    try {
      const updated = await scopedApi.update(scopeId, strategy.id, values);
      showToast("Strategy updated.");
      setEditing(false);
      setStrategy(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Strategy."));
    }
  }

  if (!scopeId || !strategyId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (strategy === null) return <Spinner />;

  return (
    <div className="container stack">
      <Link to={backLink}>{backLabel}</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{strategy.title}</h1>
        <span className={`badge badge--${STRATEGY_STATUS_TONE[strategy.status]}`}>
          {STRATEGY_STATUS_LABEL[strategy.status]}
        </span>
      </div>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <p className="text-muted" style={{ margin: 0 }}>
            {STRATEGY_PRIORITY_LABEL[strategy.priority]} priority · {STRATEGY_TIME_HORIZON_LABEL[strategy.time_horizon]} · v{strategy.version_number}
          </p>
          {!strategy.is_locked && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>

        <Field label="Objective / strategic theme" value={strategy.objective} />
        {strategy.current_state && <Field label="Current state" value={strategy.current_state} />}
        {strategy.desired_future_state && <Field label="Desired future state" value={strategy.desired_future_state} />}
        {strategy.rationale && <Field label="Rationale" value={strategy.rationale} />}
        {strategy.expected_outcomes && <Field label="Expected outcomes" value={strategy.expected_outcomes} />}
        {strategy.constraints && <Field label="Constraints" value={strategy.constraints} />}
        {strategy.measures_of_success && <Field label="Measures of success" value={strategy.measures_of_success} />}

        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
          {strategy.status === "draft" && (
            <button className="btn btn-primary" onClick={() => runTransition(() => scopedApi.propose(scopeId, strategy.id), "Strategy proposed.")}>
              Propose
            </button>
          )}
          {strategy.status === "proposed" && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => runTransition(() => scopedApi.submitForReview(scopeId, strategy.id), "Strategy submitted for review.")}
              >
                Submit for review
              </button>
              <button className="btn" onClick={() => setSendingBack(true)}>Send back</button>
            </>
          )}
          {strategy.status === "under_review" && (
            <>
              <button className="btn btn-primary" onClick={() => setTransitionAction("approve")}>Approve</button>
              <button className="btn" onClick={() => setSendingBack(true)}>Send back</button>
            </>
          )}
          {strategy.status === "approved" && (
            <button className="btn btn-primary" onClick={() => setTransitionAction("activate")}>Activate</button>
          )}
          {strategy.status === "active" && (
            <>
              <button className="btn" onClick={() => setTransitionAction("supersede")}>Supersede</button>
              <button className="btn btn-danger" onClick={() => setTransitionAction("retire")}>Retire</button>
            </>
          )}
          <button className="btn" onClick={() => setArchiveConfirm(true)}>
            {strategy.is_archived ? "Unarchive" : "Archive"}
          </button>
        </div>

        <StrategyRelationshipsSection
          strategy={strategy}
          projectId={projectId}
          organizationId={organizationId}
          onChanged={() => scopedApi.get(scopeId, strategy.id).then(setStrategy)}
        />

        {versions && versions.length > 1 && (
          <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Version history</h3>
            <table className="table">
              <thead>
                <tr><th>Version</th><th>Status</th><th>Changed</th><th>Change note</th></tr>
              </thead>
              <tbody>
                {[...versions].reverse().map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_number}</td>
                    <td>{STRATEGY_STATUS_LABEL[v.status]}</td>
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
            disabled={strategy.is_locked}
            emptyHint={strategy.is_locked ? "This Strategy is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await scopedApi.uploadFile(scopeId, strategy.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, strategy.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </div>

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <ArtefactCommentsSection
            comments={comments ?? []}
            currentUserId={user?.id}
            onPost={async (body) => {
              const comment = await scopedApi.addComment(scopeId, strategy.id, body);
              setComments((prev) => [...(prev ?? []), comment]);
              return comment;
            }}
            onEdit={async (commentId, body) => {
              const updated = await scopedApi.editComment(scopeId, strategy.id, commentId, body);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
            }}
            onUploadAttachment={async (commentId, file) => {
              const asset = await scopedApi.uploadCommentAttachment(scopeId, strategy.id, commentId, file);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
            }}
            onRemoveAttachment={async (commentId, fileId) => {
              await scopedApi.removeCommentAttachment(scopeId, strategy.id, commentId, fileId);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
            }}
          />
        </div>
      </div>

      {editing && (
        <StrategyFormModal
          initial={strategy}
          scopeLabel={projectId ? "project" : "organisation"}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {sendingBack && (
        <ConfirmDialog
          title="Send this Strategy back to Draft?"
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>A comment explaining what needs rework is required.</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Send-back comment
                <textarea
                  className="input" rows={2} aria-label="Send-back comment"
                  value={sendBackComment} onChange={(e) => setSendBackComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel="Send back"
          confirmDisabled={!sendBackComment.trim()}
          onConfirm={async () => {
            setSendingBack(false);
            const comment = sendBackComment;
            setSendBackComment("");
            await runTransition(() => scopedApi.sendBack(scopeId, strategy.id, comment), "Strategy sent back to draft.");
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
              <label className="stack" style={{ gap: "0.25rem" }}>
                Comment
                <textarea
                  className="input" rows={2} aria-label="Transition comment"
                  value={transitionComment} onChange={(e) => setTransitionComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel={TRANSITION_COPY[transitionAction].confirmLabel}
          onConfirm={async () => {
            const action = transitionAction;
            const comment = transitionComment;
            setTransitionAction(null);
            setTransitionComment("");
            await runTransition(() => scopedApi[action](scopeId, strategy.id, comment), `Strategy ${TRANSITION_COPY[action].confirmLabel.toLowerCase()}d.`);
          }}
          onCancel={() => { setTransitionAction(null); setTransitionComment(""); }}
        />
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={strategy.is_archived ? "Unarchive this Strategy?" : "Archive this Strategy?"}
          message={
            strategy.is_archived
              ? "This Strategy will count as active again."
              : "This Strategy will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes."
          }
          confirmLabel={strategy.is_archived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await runTransition(
              () => (strategy.is_archived ? scopedApi.unarchive(scopeId, strategy.id) : scopedApi.archive(scopeId, strategy.id)),
              strategy.is_archived ? "Strategy unarchived." : "Strategy archived."
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
