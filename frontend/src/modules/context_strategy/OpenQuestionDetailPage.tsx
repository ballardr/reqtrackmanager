/**
 * Module: modules/context_strategy/OpenQuestionDetailPage
 *
 * A single Open Question's full detail: fields, branching lifecycle actions, attachments, comments, relationships and
 * owner assignment through a dedicated `RecordPrincipalField`. It mirrors `PainPointDetailPage.tsx`, since both are
 * project-scoped only, with a branching lifecycle and no version table, with two differences:
 *
 * 1. Two branch points: `Open -> Investigating -> {Withdrawn | Ready for Decision -> {Resolved | Withdrawn}}`
 *    (`enums.OpenQuestionStatus`); `WITHDRAWN` is reachable from both `INVESTIGATING` and `READY_FOR_DECISION`.
 *    Confirmation tiers follow `docs/ux-style-guide.md`: `investigate` is a plain click; `mark-ready-for-decision` and
 *    `resolve` use a `ConfirmDialog` with an optional comment; `withdraw` uses one with a mandatory comment, matching
 *    the backend (`project_router.withdraw_project_open_question` returns 400 without one).
 * 2. Two roles gate the lifecycle: `open_question_owner` gates `investigate`, `mark-ready-for-decision`, `withdraw`,
 *    edit and archive, and a separate `open_question_resolver` gates `resolve` alone. Every action button renders
 *    whatever the caller's role (see `StrategyDetailPage.tsx`) and a 403 surfaces as a toast.
 *
 * Evidence upload is open to any project member and only removal is owner-gated:
 * `upload_project_open_question_file` requires `_require_open_question_view` (module enabled plus project membership),
 * not the manage role, and `is_locked` covers only the terminal states (`RESOLVED`, `WITHDRAWN`), so
 * `FileAttachmentList`'s `disabled={openQuestion.is_locked}` is as open as the backend allows.
 *
 * `owner` (a user, an organisation group or a project group) is assigned through `RecordPrincipalField`, not an
 * `OpenQuestionFormModal` field (see `types.ts` `OpenQuestionFieldValues`). The page loads the project's organisation
 * user list once and calls `projectOpenQuestionApi.update` with the current content fields plus the chosen `owner`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset, OrgUser, PrincipalRef, Project } from "../../api/types";
import { api } from "../../api/client";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { RecordField, RecordPrincipalField } from "../../components/RecordDetailParts";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
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
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { markdownPlainText } from "../../utils/markdownPlain";

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
  const [withdrawConfirm, setWithdrawConfirm] = useState(false);

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
      setLoadError(toErrorMessage(err, "This Open Question could not be found, or you do not have access to it."));
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

  /** Attaches a file to this record: the Attachments card and the Markdown fields' Picture button share it. */
  const uploadAttachment = async (file: File): Promise<FileAsset> => {
    const asset = await projectOpenQuestionApi.uploadFile(projectId, openQuestion.id, file);
    setFiles((prev) => [...prev, asset]);
    return asset;
  };

  return (
    <DetailLayout
      pictures={{ files, upload: openQuestion.is_locked ? undefined : uploadAttachment }}
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
        title={markdownPlainText(openQuestion.question)}
        code={openQuestion.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="open_question" artefactId={openQuestion.id} /> : undefined}
        back={{ to: `/projects/${projectId}/modules/context_strategy/open-questions`, label: "Open Questions" }}
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


        <DetailCard>
          {openQuestion.context && <RecordField markdown math label="Context" value={openQuestion.context} />}
          {openQuestion.evidence && <RecordField markdown math label="Evidence" value={openQuestion.evidence} />}

          <RecordPrincipalField
            label="Owner" ariaLabel="Open Question owner" principal={openQuestion.owner} orgUsers={orgUsers}
            organizationId={project?.organization_id} projectId={projectId} readOnly={false} onChange={assignOwner}
          />
        </DetailCard>


        <DetailCard heading="Evidence" rank="supporting">
          <FileAttachmentList
            files={files}
            disabled={openQuestion.is_locked}
            emptyHint={openQuestion.is_locked ? "This Open Question has reached a terminal outcome; new evidence can no longer be added." : undefined}
            onUpload={async (file) => { await uploadAttachment(file); }}
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

      {editing && (
        <OpenQuestionFormModal
          initial={openQuestion}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {optionalAction && (
        <CommentConfirmDialog
          title={OPTIONAL_COMMENT_COPY[optionalAction].title}
          intro={OPTIONAL_COMMENT_COPY[optionalAction].body}
          ariaLabel="Transition comment"
          confirmLabel={OPTIONAL_COMMENT_COPY[optionalAction].confirmLabel}
          onConfirm={async (comment) => {
            const action = optionalAction;
            setOptionalAction(null);
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
          onCancel={() => setOptionalAction(null)}
        />
      )}

      {withdrawConfirm && (
        <CommentConfirmDialog
          title="Withdraw this Open Question?"
          intro="A comment explaining why is required."
          commentLabel="Withdrawal comment"
          commentRequired
          confirmLabel="Withdraw"
          onConfirm={async (comment) => {
            setWithdrawConfirm(false);
            await runTransition(() => projectOpenQuestionApi.withdraw(projectId, openQuestion.id, comment), "Open Question withdrawn.");
          }}
          onCancel={() => setWithdrawConfirm(false)}
        />
      )}

    </DetailLayout>
  );
}
