/**
 * Module: modules/decisions/DecisionDetailPage
 *
 * A single Decision's full detail (management and full context) as a routed page
 * (`/projects/:projectId/modules/decisions/:decisionId`, `module.ts`). `docs/ux-style-guide.md` "Pattern: entity
 * detail panel" calls for a page here: the detail carries a comment thread, file attachments, a Links panel and three
 * or more lifecycle actions each with a `ConfirmDialog`. `ProjectDecisionsPage.tsx`'s list opens
 * `DecisionQuickViewPanel` (a read-only peek) on row click, and its "View full details" link leads here.
 *
 * Fetches its own data on mount (`project`, `orgUsers`, `decisionTypes` and the `Decision` through
 * `decisionsApi.getDecision`), as `RequirementDetailPage.tsx` does, so the route is deep-linkable.
 *
 * Mutating controls always render whatever the caller's role (see `ProjectCompliancePage.tsx`); the backend enforces
 * `decision_owner` / `decision_approver` and a 403 surfaces as a toast. Content edit, archive and file-attach controls
 * are hidden once `decision.is_locked`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
import { lifecycleSteps } from "../../components/lifecycleSteps";
import { useProjectLifecycle } from "../../hooks/useProjectLifecycle";
import { useSkipSteps } from "../../components/useSkipSteps";
import { withLifecycleSkip } from "../../api/client";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import type { LifecyclePromote } from "../../components/LifecycleTrack";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import { DECISION_STATUS_DESCRIPTION, DECISION_STATUS_LABEL } from "./types";
import type { Decision, DecisionComment, DecisionFieldValues, DecisionTypeDefinition } from "./types";
import type { FileAsset } from "../../api/types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { MarkdownView } from "../../components/MarkdownView";
import { DECISIONS_HELP } from "./help";

/** The main path; a project may turn Proposed and Under review off. */
const PATH = ["draft", "proposed", "under_review", "approved"] as const;

/** Why an approved or superseded Decision cannot be edited directly. */
const LOCKED_REASON = "Locked: approved and superseded Decisions cannot be edited.";

export function DecisionDetailPage() {
  const { projectId, decisionId } = useParams<{ projectId: string; decisionId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [decisionTypes, setDecisionTypes] = useState<DecisionTypeDefinition[]>([]);
  const [decision, setDecision] = useState<Decision | null>(null);
  const lifecycle = useProjectLifecycle(projectId, "decision");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
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
      setLoadError(toErrorMessage(err, "This Decision could not be found, or you do not have access to it."));
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

  useLoadOnChange(reloadCommentsAndFiles, [projectId, decisionId]);

  async function runTransition(action: () => Promise<Decision>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setDecision(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Decision."), "error");
    }
  }

  const skipSteps = useSkipSteps<Decision>({
    lifecycle, current: decision?.status ?? "", labels: DECISION_STATUS_LABEL, noun: "Decision",
    move: (target, reason) => {
      if (!projectId || !decision) return Promise.reject(new Error("This move is not available."));
      if (target === "under_review") return withLifecycleSkip(reason, () => decisionsApi.submitDecisionForReview(projectId, decision.id));
      if (target === "approved") return withLifecycleSkip(reason, () => decisionsApi.approveDecision(projectId, decision.id));
      return Promise.reject(new Error("This move is not available."));
    },
    onMoved: setDecision,
  });

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

  const archive = useArchiveAction({
    noun: "Decision",
    isArchived: decision?.is_archived ?? false,
    hidden: !decision,
    archiveBody: "This Decision will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!projectId || !decision) return;
      await runTransition(
        () => (decision.is_archived ? decisionsApi.unarchiveDecision(projectId, decision.id) : decisionsApi.archiveDecision(projectId, decision.id)),
        decision.is_archived ? "Decision unarchived." : "Decision archived.",
      );
    },
  });

  if (!projectId || !decisionId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (decision === null || project === null) return <Spinner />;

  // The next forward move; Reject is a row of the actions menu.
  // It goes to the next step the project uses: with Proposed and Under review turned off, Draft goes to Approved
  // through the approval dialog and the approver's permission.
  const next = lifecycle.nextOnPath(PATH, decision.status);
  const promote: LifecyclePromote | undefined =
    next === "proposed" ? { to: "proposed", onPromote: () => void runTransition(() => decisionsApi.proposeDecision(projectId, decision.id), "Decision proposed.") }
    : next === "under_review" ? { to: "under_review", onPromote: () => void runTransition(() => decisionsApi.submitDecisionForReview(projectId, decision.id), "Decision submitted for review.") }
    : next === "approved" ? { to: "approved", onPromote: () => setApproving(true) }
    : undefined;
  const offPathStep = decision.status === "rejected" || decision.status === "superseded" ? {
    key: decision.status,
    label: DECISION_STATUS_LABEL[decision.status],
    description: DECISION_STATUS_DESCRIPTION[decision.status],
    after: lifecycle.lastOnPath(PATH, decision.status === "rejected" ? "under_review" : "approved"),
    ...(decision.status === "superseded" ? { locked: true, lockedReason: LOCKED_REASON } : {}),
  } : undefined;

  const decisionType = decisionTypes.find((t) => t.id === decision.decision_type_id);

  /** Attaches a file to this record: the Attachments card and the Markdown fields' Picture button share it. */
  const uploadAttachment = async (file: File): Promise<FileAsset> => {
    const asset = await decisionsApi.uploadDecisionFile(projectId, decision.id, file);
    setFiles((prev) => [...prev, asset]);
    return asset;
  };

  return (
    <DetailLayout
      pictures={{ files, upload: decision.is_locked ? undefined : uploadAttachment }}
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="decision" artefactId={decision.id} refreshToken={recordActivityKey(decision)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="decision"
          artefactId={decision.id}
          actions={({ reload }) => (
            <SupersedeAction
              artefactLabel="Decision"
              onDone={reload}
              loadCandidates={async () =>
                (await decisionsApi.listDecisions(projectId))
                  .filter((d) => d.id !== decision.id)
                  .map((d) => ({ id: d.id, label: `${d.unique_code} — ${d.title}` }))
              }
              onSupersede={async (oldId) => {
                await decisionsApi.createSupersession(projectId, decision.id, oldId);
              }}
            />
          )}
        />
      }
    >
      <RecordHeader
        recordLabel="Decision"
        title={decision.title}
        code={decision.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="decision" artefactId={decision.id} /> : undefined}
        back={{ to: `/projects/${projectId}/modules/decisions`, label: "Decisions" }}
        subtitle={decisionType?.name ?? "—"}
        onEdit={decision.is_locked ? undefined : () => setEditing(true)}
        actions={[
          skipSteps.menuRow,
          lifecycle.canMove(decision.status, "rejected", decision.status === "under_review") && { label: "Reject", danger: true, onSelect: () => setRejecting(true) },
          archive.item,
        ]}
        lifecycle={{
          steps: lifecycle.visibleSteps(
            lifecycleSteps(PATH, DECISION_STATUS_LABEL, {
              descriptions: DECISION_STATUS_DESCRIPTION,
              locked: { approved: LOCKED_REASON },
            }),
            decision.status,
          ),
          current: decision.status,
          offPath: offPathStep,
          promote,
          skip: skipSteps.track,
        }}
      />
      {archive.dialog}
        <DetailCard>
          <MarkdownView math text={decision.decision_statement} />
          <div className="row" style={{ gap: "2rem", flexWrap: "wrap" }}>
            <RecordFieldGroup help={DECISIONS_HELP.decisionOwner} label="Owner"><PrincipalBadge principal={decision.owner} /></RecordFieldGroup>
            <RecordFieldGroup help={DECISIONS_HELP.decisionMaker} label="Decision maker"><PrincipalBadge principal={decision.decision_maker} /></RecordFieldGroup>
          </div>

          {decision.context && <RecordField markdown math label="Context" value={decision.context} />}
          {decision.options_considered && <RecordField markdown math label="Options considered" value={decision.options_considered} />}
          {decision.chosen_option && <RecordField markdown math label="Chosen option" value={decision.chosen_option} />}
          {decision.rationale && <RecordField markdown math label="Rationale" value={decision.rationale} />}
          {decision.consequences && <RecordField markdown math label="Consequences" value={decision.consequences} />}
          {decision.assumptions && <RecordField markdown math label="Assumptions" value={decision.assumptions} />}
          {decision.constraints && <RecordField markdown math label="Constraints" value={decision.constraints} />}
        </DetailCard>

        {decision.document && (
          <DetailCard heading="Document">
            <MarkdownView math text={decision.document} />
          </DetailCard>
        )}

        <DetailCard heading="Attachments" rank="supporting">
          <FileAttachmentList
            files={files}
            disabled={decision.is_locked}
            emptyHint={decision.is_locked ? "This Decision is approved or superseded; new attachments can no longer be added." : undefined}
            onUpload={async (file) => { await uploadAttachment(file); }}
            onRemove={async (fileId) => {
              await decisionsApi.unlinkDecisionFile(projectId, decision.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

        <ArtefactCommentsSection
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

      {editing && (
        <DecisionFormModal
          initial={decision}
          decisionTypes={decisionTypes}
          orgUsers={orgUsers}
          organizationId={project.organization_id}
          projectId={projectId}
          currentUserId={user?.id}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {skipSteps.dialog}

      {approving && (
        <CommentConfirmDialog
          title="Approve this Decision?"
          intro="This records a formal approval in the audit trail. A comment is optional."
          commentLabel="Approval comment"
          confirmLabel="Approve"
          onConfirm={async (comment) => {
            setApproving(false);
            await runTransition(() => decisionsApi.approveDecision(projectId, decision.id, comment), "Decision approved.");
          }}
          onCancel={() => setApproving(false)}
        />
      )}

      {rejecting && (
        <CommentConfirmDialog
          title="Reject this Decision?"
          intro="A comment explaining the rejection is required."
          commentLabel="Rejection comment"
          commentRequired
          confirmLabel="Reject"
          onConfirm={async (comment) => {
            setRejecting(false);
            await runTransition(() => decisionsApi.rejectDecision(projectId, decision.id, comment), "Decision rejected.");
          }}
          onCancel={() => setRejecting(false)}
        />
      )}
    </DetailLayout>
  );
}
