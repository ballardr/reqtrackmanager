/**
 * Module: modules/context_strategy/OpenQuestionDetailPage
 *
 * A single Open Question's full detail — mirrors `PainPointDetailPage.tsx`'s overall
 * shape (full field display, branching lifecycle actions, attachments,
 * comments, relationships, owner assignment via a dedicated `PrincipalPicker`)
 * closely, since both artefacts share the same "project-scoped only,
 * branching lifecycle, no version table" backend shape. Two differences
 * driven directly by Open Question's own backend design:
 *
 * 1. **Two branch points, not one.** `Open -> Investigating -> {Withdrawn |
 *    Ready for Decision -> {Resolved | Withdrawn}}` (`enums.OpenQuestionStatus`'s
 *    own docstring) — `WITHDRAWN` is reachable from *both* `INVESTIGATING`
 *    and `READY_FOR_DECISION`, not only from one middle state the way Pain
 *    Point's `TRIAGED` is the sole branch point. Confirmation tiers follow
 *    `docs/ux-style-guide.md`'s confirmation-tier principle the same way
 *    every other artefact in this module applies it: `investigate` is a
 *    plain click (low-risk, single early-lifecycle step, mirrors Pain
 *    Point's `triage`/Strategy's `propose`); `mark-ready-for-decision`/
 *    `resolve` (positive/neutral progression) get a `ConfirmDialog` with an
 *    *optional* comment; `withdraw` (the one negative/terminal-branch
 *    action) gets a `ConfirmDialog` with a **mandatory** comment, matching
 *    backend enforcement exactly (`project_router.withdraw_project_open_
 *    question` 400s without one — the mandatory-comment-on-a-negative-
 *    outcome convention `reject_pain_point`/`mark_pain_point_duplicate`
 *    already established, applied here to the module's second branching
 *    lifecycle).
 * 2. **Two roles, not one, gate the lifecycle actions** (§9.4's
 * three-tier permission split — see `enums.py`'s own docstring):
 *    `open_question_owner` gates `investigate`/`mark-ready-for-decision`/
 *    `withdraw`/edit/archive; a *separate* `open_question_resolver` gates
 *    `resolve` alone. This page renders every action button unconditionally
 *    regardless of the caller's actual role — the same established
 *    convention `StrategyDetailPage.tsx`'s own docstring documents (every
 *    mutating control always renders, gated only by content-lock state, with
 *    a 403 surfacing as a toast) — so this two-role split needs no different
 *    frontend wiring than Pain Point's single-role gate did; only the
 *    backend distinguishes who can actually click "Resolve" successfully.
 *
 * **Evidence upload is open to any project member; only removal is
 * owner-gated (Decided by: Agent) — the same "no special frontend wiring
 * needed" finding `PainPointDetailPage.tsx`'s own docstring point 3 already
 * made.** Checked `upload_project_open_question_file`'s own RBAC first: it
 * depends only on `_require_open_question_view` (module-enabled + project
 * membership), not `require_open_question_manage_role`, matching §9.4's
 * "Add evidence" broad-creation capability; `is_locked` already excludes
 * only the two true terminal states (`RESOLVED`/`WITHDRAWN`), so
 * `FileAttachmentList`'s existing `disabled={openQuestion.is_locked}` wiring
 * is already exactly as open as the backend allows.
 *
 * **Owner assignment via a dedicated `RecordPrincipalField`, not an
 * `OpenQuestionFormModal` field** — see `types.ts`'s own docstring on
 * `OpenQuestionFieldValues` for why. The owner is a user, an organisation
 * group or a project group. This page loads this project's
 * organisation's user list once and calls `projectOpenQuestionApi.update`
 * directly with the current content fields plus the newly chosen `owner`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset, OrgUser, PrincipalRef, Project } from "../../api/types";
import { api } from "../../api/client";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { RecordPrincipalField } from "../../components/RecordDetailParts";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectOpenQuestionApi } from "./api";
import { OpenQuestionFormModal } from "./OpenQuestionFormModal";
import { OPEN_QUESTION_PRIORITY_LABEL, OPEN_QUESTION_STATUS_LABEL, OPEN_QUESTION_STATUS_TONE } from "./types";
import type { OpenQuestion, OpenQuestionComment, OpenQuestionFieldValues } from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { TextAreaField } from "../../components/FormFields";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";

/** The two optional-comment, positive/neutral-progression actions — mirrors
 * `PainPointDetailPage.tsx`'s `OptionalCommentAction`/`OPTIONAL_COMMENT_COPY`
 * shape for its own `accept`/`address`/`close` tier. */
type OptionalCommentAction = "mark_ready_for_decision" | "resolve";

const OPTIONAL_COMMENT_COPY: Record<OptionalCommentAction, { title: string; body: string; confirmLabel: string }> = {
  mark_ready_for_decision: {
    title: "Mark this Open Question ready for decision?",
    body: "This signals investigation is complete and a decision can now be made. A comment is optional.",
    confirmLabel: "Mark ready for decision",
  },
  resolve: {
    title: "Resolve this Open Question?",
    body: "This ends its lifecycle with a decision reached. A comment is optional.",
    confirmLabel: "Resolve",
  },
};

export function OpenQuestionDetailPage() {
  const { projectId, openQuestionId } = useParams<{ projectId: string; openQuestionId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [openQuestion, setOpenQuestion] = useState<OpenQuestion | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [comments, setComments] = useState<OpenQuestionComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [optionalAction, setOptionalAction] = useState<OptionalCommentAction | null>(null);
  const [optionalComment, setOptionalComment] = useState("");
  const [withdrawConfirm, setWithdrawConfirm] = useState(false);
  const [withdrawComment, setWithdrawComment] = useState("");

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => {
      setProject(p);
      void api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    });
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !openQuestionId) return;
    projectOpenQuestionApi.get(projectId, openQuestionId).then(setOpenQuestion).catch((err) => {
      setLoadError(toErrorMessage(err, "This Open Question could not be found, or you don't have access to it."));
    });
  }, [projectId, openQuestionId]);

  async function reloadCommentsAndFiles() {
    if (!projectId || !openQuestionId) return;
    try {
      const [c, f] = await Promise.all([
        projectOpenQuestionApi.listComments(projectId, openQuestionId),
        projectOpenQuestionApi.listFiles(projectId, openQuestionId),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Open Question's comments/files."), "error");
    }
  }

  useLoadOnChange(reloadCommentsAndFiles, [projectId, openQuestionId]);

  async function runTransition(action: () => Promise<OpenQuestion>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setOpenQuestion(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Open Question."), "error");
    }
  }

  async function saveEdit(values: OpenQuestionFieldValues) {
    if (!projectId || !openQuestion) return;
    setFormError(null);
    try {
      const updated = await projectOpenQuestionApi.update(projectId, openQuestion.id, { ...values, owner: openQuestion.owner });
      showToast("Open Question updated.");
      setEditing(false);
      setOpenQuestion(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Open Question."));
    }
  }

  async function assignOwner(owner: PrincipalRef | null) {
    if (!projectId || !openQuestion) return;
    try {
      const updated = await projectOpenQuestionApi.update(projectId, openQuestion.id, {
        question: openQuestion.question, context: openQuestion.context, evidence: openQuestion.evidence,
        priority: openQuestion.priority, due_date: openQuestion.due_date, owner,
      });
      showToast("Owner updated.");
      setOpenQuestion(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Open Question's owner."), "error");
    }
  }

  const archive = useArchiveAction({
    noun: "Open Question",
    isArchived: openQuestion?.is_archived ?? false,
    hidden: !openQuestion,
    archiveBody: "This Open Question will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!projectId || !openQuestion) return;
      await runTransition(
        () => (openQuestion.is_archived ? projectOpenQuestionApi.unarchive(projectId, openQuestion.id) : projectOpenQuestionApi.archive(projectId, openQuestion.id)),
        openQuestion.is_archived ? "Open Question unarchived." : "Open Question archived.",
      );
    },
  });

  if (!projectId || !openQuestionId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (openQuestion === null) return <Spinner />;

  return (
    <DetailLayout
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="open_question" artefactId={openQuestion.id} refreshToken={recordActivityKey(openQuestion)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="open_question"
          artefactId={openQuestion.id}
        />
      }
    >
      <RecordHeader
        recordLabel="Open Question"
        title={openQuestion.question}
        code={openQuestion.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="open_question" artefactId={openQuestion.id} /> : undefined}
        back={{ to: `/projects/${projectId}/modules/context_strategy/open-questions`, label: "← Open Question" }}
        badges={
          <>
          <Badge tone={OPEN_QUESTION_STATUS_TONE[openQuestion.status]}>
            {OPEN_QUESTION_STATUS_LABEL[openQuestion.status]}
          </Badge>
          </>
        }
        subtitle={
          <>
            {OPEN_QUESTION_PRIORITY_LABEL[openQuestion.priority]} priority
            {openQuestion.due_date ? ` · due ${openQuestion.due_date}` : ""}
          </>
        }
        onEdit={openQuestion.is_locked ? undefined : () => setEditing(true)}
        actions={[archive.item]}
        transitions={
          <>
          {openQuestion.status === "open" && (
            <button
              className="btn btn-primary"
              onClick={() => runTransition(() => projectOpenQuestionApi.investigate(projectId, openQuestion.id), "Open Question moved to Investigating.")}
            >
              Investigate
            </button>
          )}
          {openQuestion.status === "investigating" && (
            <>
              <button className="btn btn-primary" onClick={() => setOptionalAction("mark_ready_for_decision")}>Mark ready for decision</button>
              <button className="btn btn-danger" onClick={() => setWithdrawConfirm(true)}>Withdraw</button>
            </>
              )}
              {openQuestion.status === "ready_for_decision" && (
                <>
                  <button className="btn btn-primary" onClick={() => setOptionalAction("resolve")}>Resolve</button>
                  <button className="btn btn-danger" onClick={() => setWithdrawConfirm(true)}>Withdraw</button>
                </>
              )}
          </>
        }
      />
      {archive.dialog}

      <div className="stack">

        <DetailCard>
          {openQuestion.context && <Field label="Context" value={openQuestion.context} />}
          {openQuestion.evidence && <Field label="Evidence" value={openQuestion.evidence} />}

          <RecordPrincipalField
            label="Owner" ariaLabel="Open Question owner" principal={openQuestion.owner} orgUsers={orgUsers}
            organizationId={project?.organization_id} projectId={projectId} readOnly={false} onChange={assignOwner}
          />
        </DetailCard>


        <DetailCard heading="Evidence">
          <FileAttachmentList
            files={files}
            disabled={openQuestion.is_locked}
            emptyHint={openQuestion.is_locked ? "This Open Question has reached a terminal outcome; new evidence can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await projectOpenQuestionApi.uploadFile(projectId, openQuestion.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await projectOpenQuestionApi.unlinkFile(projectId, openQuestion.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

        <ArtefactCommentsSection
          comments={comments ?? []}
          currentUserId={user?.id}
          onPost={async (body) => {
            const comment = await projectOpenQuestionApi.addComment(projectId, openQuestion.id, body);
            setComments((prev) => [...(prev ?? []), comment]);
            return comment;
          }}
          onEdit={async (commentId, body) => {
            const updated = await projectOpenQuestionApi.editComment(projectId, openQuestion.id, commentId, body);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
          }}
          onUploadAttachment={async (commentId, file) => {
            const asset = await projectOpenQuestionApi.uploadCommentAttachment(projectId, openQuestion.id, commentId, file);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
          }}
          onRemoveAttachment={async (commentId, fileId) => {
            await projectOpenQuestionApi.removeCommentAttachment(projectId, openQuestion.id, commentId, fileId);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
          }}
        />
      </div>

      {editing && (
        <OpenQuestionFormModal
          initial={openQuestion}
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
              <TextAreaField helpNotNeeded
                label="Comment"
                ariaLabel="Transition comment"
                value={optionalComment}
                onChange={setOptionalComment}
                rows={2}
              />
            </span>
          }
          confirmLabel={OPTIONAL_COMMENT_COPY[optionalAction].confirmLabel}
          onConfirm={async () => {
            const action = optionalAction;
            const comment = optionalComment;
            setOptionalAction(null);
            setOptionalComment("");
            if (action === "mark_ready_for_decision") {
              await runTransition(
                () => projectOpenQuestionApi.markReadyForDecision(projectId, openQuestion.id, comment),
                "Open Question marked ready for decision.",
              );
            } else {
              await runTransition(
                () => projectOpenQuestionApi.resolve(projectId, openQuestion.id, comment),
                "Open Question resolved.",
              );
            }
          }}
          onCancel={() => { setOptionalAction(null); setOptionalComment(""); }}
        />
      )}

      {withdrawConfirm && (
        <ConfirmDialog
          title="Withdraw this Open Question?"
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>A comment explaining why is required.</span>
              <TextAreaField helpNotNeeded
                label="Withdrawal comment"
                value={withdrawComment}
                onChange={setWithdrawComment}
                rows={2}
              />
            </span>
          }
          confirmLabel="Withdraw"
          confirmDisabled={!withdrawComment.trim()}
          onConfirm={async () => {
            const comment = withdrawComment;
            setWithdrawConfirm(false);
            setWithdrawComment("");
            await runTransition(() => projectOpenQuestionApi.withdraw(projectId, openQuestion.id, comment), "Open Question withdrawn.");
          }}
          onCancel={() => { setWithdrawConfirm(false); setWithdrawComment(""); }}
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
