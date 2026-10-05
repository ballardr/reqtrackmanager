/**
 * Module: modules/context_strategy/PainPointDetailPage
 *
 * A single Pain Point's full detail (docs/plans/module-01-context-and-
 * strategy-plan.md Phase 7.3) — mirrors `StrategyDetailPage.tsx`'s overall
 * shape (full field display, lifecycle actions, attachments, comments,
 * relationships), with three structural differences driven directly by Pain
 * Point's own backend design:
 *
 * 1. **Project-scoped only** — no `organizationId` route param, no
 *    scope-dispatch between two API objects; always `projectPainPointApi`.
 * 2. **Branching lifecycle UI, not a single "next" button.** From `TRIAGED`,
 *    this page offers three distinct actions — Accept / Reject / Mark
 *    Duplicate — matching `PainPointStatus`'s own three-way branch
 *    (`service._PP_ALLOWED_TRANSITIONS[TRIAGED]`). Confirmation tiers follow
 *    `docs/ux-style-guide.md`'s confirmation-tier principle the same way
 *    Phase 7.1's notes describe: `triage` is a plain click (low-risk,
 *    single early-lifecycle step, mirrors Strategy's `propose`/`submit-for-
 *    review`); `reject`/`mark-duplicate` require a `ConfirmDialog` with a
 *    **mandatory** comment (matching backend enforcement —
 *    `project_router.reject_project_pain_point`/`mark_project_pain_point_
 *    duplicate` both 400 without one); `accept`/`address`/`close` get a
 *    `ConfirmDialog` with an optional comment (positive/neutral progression,
 *    same tier as Strategy's `approve`/`activate`/`retire`).
 * 3. **Evidence upload is open to any project member; only removal is
 *    manager-gated (Decided by: Agent).** Checked `upload_project_pain_
 *    point_file`'s own docstring first: unlike Strategy/Future State's
 *    owner-gated file upload, source overview §6.5 explicitly lists "Add
 *    evidence" among the broad-creation-model capabilities every project
 *    member gets. In practice this needs **no different frontend wiring**
 *    from Strategy's own `FileAttachmentList` usage — this codebase's
 *    established convention (`StrategyDetailPage.tsx`'s own docstring) is
 *    that every mutating control always renders regardless of the caller's
 *    actual role, gated only by content-lock state, with the backend's own
 *    RBAC surfacing as a toast on a 403; `is_locked` here already excludes
 *    only the three true terminal states (`REJECTED`/`DUPLICATE`/`CLOSED`,
 *    not `ACCEPTED`/`ADDRESSED` too — `service.PAIN_POINT_LOCKED_STATUSES`),
 *    so the upload control is already exactly as open as the backend allows
 *    without any manager-only conditional added around it. Only the
 *    difference in *who the backend accepts* (any member for upload, manager
 *    only for removal) is real — nothing on this page needs to encode it.
 *
 * Phase 11 adds `PainPointScoringPanel` (per-persona Severity/Frequency/
 * Confidence scoring and the chosen-when-viewing roll-up) and an
 * "Intentional" badge for deliberate limitations.
 *
 * **Owner assignment via a dedicated `AssigneePicker`, not a
 * `PainPointFormModal` field (Decided by: Agent)** — see `types.ts`'s own
 * docstring on `PainPointFieldValues` for why. This page loads this
 * project's organisation's user list once (for `AssigneePicker`'s own
 * search/display needs) and calls `projectPainPointApi.update` directly with
 * the current content fields plus the newly chosen `owner_id`.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";

import type { FileAsset, OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { AssigneePicker } from "../../components/AssigneePicker";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import { PainPointRelationshipsSection } from "./PainPointRelationshipsSection";
import { PainPointScoringPanel } from "./PainPointScoringPanel";
import { PAIN_POINT_PRIORITY_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE } from "./types";
import type { EffectivePainPointType, PainPoint, PainPointComment, PainPointFieldValues } from "./types";

/** The three optional-comment, positive/neutral-progression actions —
 * mirrors `StrategyDetailPage.tsx`'s `TransitionAction`/`TRANSITION_COPY`
 * shape for its own `approve`/`activate`/`supersede`/`retire` tier. */
type OptionalCommentAction = "accept" | "address" | "close";

const OPTIONAL_COMMENT_COPY: Record<OptionalCommentAction, { title: string; body: string; confirmLabel: string }> = {
  accept: {
    title: "Accept this Pain Point?",
    body: "This moves it into active work. A comment is optional.",
    confirmLabel: "Accept",
  },
  address: {
    title: "Mark this Pain Point addressed?",
    body: "This records that the underlying problem has been dealt with. A comment is optional.",
    confirmLabel: "Address",
  },
  close: {
    title: "Close this Pain Point?",
    body: "This ends its lifecycle. A comment is optional.",
    confirmLabel: "Close",
  },
};

/** The two mandatory-comment, negative/terminal-branch actions — mirrors
 * this codebase's standing "comment required on a negative/terminal-branch
 * outcome" convention (`StrategyDetailPage.tsx`'s `send-back`). */
type MandatoryCommentAction = "reject" | "mark_duplicate";

const MANDATORY_COMMENT_COPY: Record<MandatoryCommentAction, { title: string; hint: string; confirmLabel: string }> = {
  reject: {
    title: "Reject this Pain Point?",
    hint: "A comment explaining why is required.",
    confirmLabel: "Reject",
  },
  mark_duplicate: {
    title: "Mark this Pain Point a duplicate?",
    hint: "A comment naming the canonical Pain Point is required. To record a real link to it, use the Relationships section's \"Duplicate of another Pain Point\" option too.",
    confirmLabel: "Mark duplicate",
  },
};

export function PainPointDetailPage() {
  const { projectId, painPointId } = useParams<{ projectId: string; painPointId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [painPoint, setPainPoint] = useState<PainPoint | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [types, setTypes] = useState<EffectivePainPointType[]>([]);
  const [comments, setComments] = useState<PainPointComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [optionalAction, setOptionalAction] = useState<OptionalCommentAction | null>(null);
  const [optionalComment, setOptionalComment] = useState("");
  const [mandatoryAction, setMandatoryAction] = useState<MandatoryCommentAction | null>(null);
  const [mandatoryComment, setMandatoryComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => {
      setProject(p);
      void api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    });
    void projectPainPointApi.listTypes(projectId).then(setTypes).catch(() => setTypes([]));
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !painPointId) return;
    projectPainPointApi.get(projectId, painPointId).then(setPainPoint).catch((err) => {
      setLoadError(toErrorMessage(err, "This Pain Point could not be found, or you don't have access to it."));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, painPointId]);

  async function reloadCommentsAndFiles() {
    if (!projectId || !painPointId) return;
    try {
      const [c, f] = await Promise.all([
        projectPainPointApi.listComments(projectId, painPointId),
        projectPainPointApi.listFiles(projectId, painPointId),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Pain Point's comments/files."), "error");
    }
  }

  useEffect(() => {
    void reloadCommentsAndFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, painPointId]);

  async function runTransition(action: () => Promise<PainPoint>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setPainPoint(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Pain Point."), "error");
    }
  }

  async function saveEdit(values: PainPointFieldValues) {
    if (!projectId || !painPoint) return;
    setFormError(null);
    try {
      const updated = await projectPainPointApi.update(projectId, painPoint.id, { ...values, owner_id: painPoint.owner_id });
      showToast("Pain Point updated.");
      setEditing(false);
      setPainPoint(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Pain Point."));
    }
  }

  async function assignOwner(ownerId: string) {
    if (!projectId || !painPoint) return;
    try {
      const updated = await projectPainPointApi.update(projectId, painPoint.id, {
        pain_point_type_id: painPoint.pain_point_type_id, title: painPoint.title, description: painPoint.description,
        source: painPoint.source, impact: painPoint.impact, evidence: painPoint.evidence, priority: painPoint.priority,
        date_identified: painPoint.date_identified, owner_id: ownerId || null,
      });
      showToast("Owner updated.");
      setPainPoint(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Pain Point's owner."), "error");
    }
  }

  if (!projectId || !painPointId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (painPoint === null) return <Spinner />;

  return (
    <div className="container stack">
      <Link to={`/projects/${projectId}/modules/context_strategy/pain-points`}>← Pain Point</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{painPoint.title}</h1>
        <span className="row" style={{ gap: "0.5rem" }}>
          {painPoint.is_intentional && <span className="badge badge--info">Intentional</span>}
          <span className={`badge badge--${PAIN_POINT_STATUS_TONE[painPoint.status]}`}>
            {PAIN_POINT_STATUS_LABEL[painPoint.status]}
          </span>
        </span>
      </div>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <p className="text-muted" style={{ margin: 0 }}>
            {painPoint.pain_point_type_name} · {PAIN_POINT_PRIORITY_LABEL[painPoint.priority]} priority · identified {painPoint.date_identified}
          </p>
          {!painPoint.is_locked && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>

        {painPoint.description && <Field label="Description" value={painPoint.description} />}
        {painPoint.source && <Field label="Source" value={painPoint.source} />}
        {painPoint.impact && <Field label="Impact" value={painPoint.impact} />}
        {painPoint.evidence && <Field label="Evidence" value={painPoint.evidence} />}

        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Owner</span>
          <AssigneePicker
            orgUsers={orgUsers}
            organizationId={project?.organization_id}
            assigneeId={painPoint.owner_id}
            onChange={assignOwner}
            ariaLabel="Pain Point owner"
          />
        </div>

        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
          {painPoint.status === "submitted" && (
            <button
              className="btn btn-primary"
              onClick={() => runTransition(() => projectPainPointApi.triage(projectId, painPoint.id), "Pain Point triaged.")}
            >
              Triage
            </button>
          )}
          {painPoint.status === "triaged" && (
            <>
              <button className="btn btn-primary" onClick={() => setOptionalAction("accept")}>Accept</button>
              <button className="btn btn-danger" onClick={() => setMandatoryAction("reject")}>Reject</button>
              <button className="btn" onClick={() => setMandatoryAction("mark_duplicate")}>Mark duplicate</button>
            </>
          )}
          {painPoint.status === "accepted" && (
            <button className="btn btn-primary" onClick={() => setOptionalAction("address")}>Address</button>
          )}
          {painPoint.status === "addressed" && (
            <button className="btn btn-primary" onClick={() => setOptionalAction("close")}>Close</button>
          )}
          <button className="btn" onClick={() => setArchiveConfirm(true)}>
            {painPoint.is_archived ? "Unarchive" : "Archive"}
          </button>
        </div>

        <PainPointScoringPanel projectId={projectId} painPointId={painPoint.id} locked={painPoint.is_locked} />

        <PainPointRelationshipsSection projectId={projectId} painPoint={painPoint} />

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Evidence</h3>
          <FileAttachmentList
            files={files}
            disabled={painPoint.is_locked}
            emptyHint={painPoint.is_locked ? "This Pain Point has reached a terminal outcome; new evidence can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await projectPainPointApi.uploadFile(projectId, painPoint.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await projectPainPointApi.unlinkFile(projectId, painPoint.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </div>

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <ArtefactCommentsSection
            comments={comments ?? []}
            currentUserId={user?.id}
            onPost={async (body) => {
              const comment = await projectPainPointApi.addComment(projectId, painPoint.id, body);
              setComments((prev) => [...(prev ?? []), comment]);
              return comment;
            }}
            onEdit={async (commentId, body) => {
              const updated = await projectPainPointApi.editComment(projectId, painPoint.id, commentId, body);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
            }}
            onUploadAttachment={async (commentId, file) => {
              const asset = await projectPainPointApi.uploadCommentAttachment(projectId, painPoint.id, commentId, file);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
            }}
            onRemoveAttachment={async (commentId, fileId) => {
              await projectPainPointApi.removeCommentAttachment(projectId, painPoint.id, commentId, fileId);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
            }}
          />
        </div>
      </div>

      {editing && (
        <PainPointFormModal
          initial={painPoint}
          types={types}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {optionalAction && (
        <ConfirmDialog
          title={OPTIONAL_COMMENT_COPY[optionalAction].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{OPTIONAL_COMMENT_COPY[optionalAction].body}</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Comment
                <textarea
                  className="input" rows={2} aria-label="Transition comment"
                  value={optionalComment} onChange={(e) => setOptionalComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel={OPTIONAL_COMMENT_COPY[optionalAction].confirmLabel}
          onConfirm={async () => {
            const action = optionalAction;
            const comment = optionalComment;
            setOptionalAction(null);
            setOptionalComment("");
            await runTransition(
              () => projectPainPointApi[action](projectId, painPoint.id, comment),
              `Pain Point ${OPTIONAL_COMMENT_COPY[action].confirmLabel.toLowerCase()}ed.`,
            );
          }}
          onCancel={() => { setOptionalAction(null); setOptionalComment(""); }}
        />
      )}

      {mandatoryAction && (
        <ConfirmDialog
          title={MANDATORY_COMMENT_COPY[mandatoryAction].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{MANDATORY_COMMENT_COPY[mandatoryAction].hint}</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                {mandatoryAction === "reject" ? "Rejection comment" : "Duplicate comment"}
                <textarea
                  className="input" rows={2}
                  aria-label={mandatoryAction === "reject" ? "Rejection comment" : "Duplicate comment"}
                  value={mandatoryComment} onChange={(e) => setMandatoryComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel={MANDATORY_COMMENT_COPY[mandatoryAction].confirmLabel}
          confirmDisabled={!mandatoryComment.trim()}
          onConfirm={async () => {
            const action = mandatoryAction;
            const comment = mandatoryComment;
            setMandatoryAction(null);
            setMandatoryComment("");
            if (action === "reject") {
              await runTransition(() => projectPainPointApi.reject(projectId, painPoint.id, comment), "Pain Point rejected.");
            } else {
              await runTransition(() => projectPainPointApi.markDuplicate(projectId, painPoint.id, comment), "Pain Point marked a duplicate.");
            }
          }}
          onCancel={() => { setMandatoryAction(null); setMandatoryComment(""); }}
        />
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={painPoint.is_archived ? "Unarchive this Pain Point?" : "Archive this Pain Point?"}
          message={
            painPoint.is_archived
              ? "This Pain Point will count as active again."
              : "This Pain Point will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes."
          }
          confirmLabel={painPoint.is_archived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await runTransition(
              () => (painPoint.is_archived ? projectPainPointApi.unarchive(projectId, painPoint.id) : projectPainPointApi.archive(projectId, painPoint.id)),
              painPoint.is_archived ? "Pain Point unarchived." : "Pain Point archived.",
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
