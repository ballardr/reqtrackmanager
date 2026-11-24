/**
 * Module: modules/context_strategy/GuidingPrincipleDetailPage
 *
 * A single Guiding Principle's full detail: fields, lifecycle status, versions, comments, attachments, relationships
 * and every lifecycle action. It mirrors `StrategyDetailPage.tsx` with two differences:
 *
 * 1. A six-state lifecycle with no `under_review` step: `Draft -> Proposed -> Approved -> Active -> Superseded/Retired`.
 *    From `Proposed` the page offers `Approve` (optional comment) and `Send back` (mandatory comment) directly.
 * 2. `owner` is assigned through `RecordPrincipalField` (a user, an organisation group and, on a project principle, a
 *    project group), not a `GuidingPrincipleFormModal` field, as in `PainPointDetailPage.tsx`: assigning a person or
 *    team is a frequent action that suits a search-first control. The backend versions `owner` as a content field on
 *    the full-replace `PUT`, so `assignOwner` calls `scopedApi.update` with the current content fields plus the new
 *    `owner`.
 *
 * Scope-aware (as `StrategyDetailPage.tsx`): reads whichever of `projectId`/`organizationId` the route supplies. An
 * organisation-scoped principle uses `organizationId` directly for the owner picker; a project-scoped one fetches its
 * project to obtain `organization_id`.
 *
 * Mutating controls always render whatever the caller's role; the backend enforces `guiding_principle_owner` /
 * `guiding_principle_approver` (or the organisation equivalents) and a 403 surfaces as a toast. Content edit, archive
 * and file-attach controls are hidden once `guidingPrinciple.is_locked` (from `APPROVED`, one state earlier than
 * Strategy and Future State; `service.GUIDING_PRINCIPLE_LOCKED_STATUSES`).
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset, OrgUser, PrincipalRef, Project } from "../../api/types";
import { api } from "../../api/client";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { RecordField, RecordPrincipalField, VersionHistoryTable } from "../../components/RecordDetailParts";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgGuidingPrincipleApi, projectGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import {
  GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_DESCRIPTION, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE,
  REVIEWED_LOCKED_REASON,
} from "./types";
import type {
  GuidingPrinciple, GuidingPrincipleComment, GuidingPrincipleFieldValues, GuidingPrincipleVersion,
} from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { lifecycleSteps } from "../../components/lifecycleSteps";
import { useProjectLifecycle } from "../../hooks/useProjectLifecycle";
import { useSkipSteps } from "../../components/useSkipSteps";
import { withLifecycleSkip } from "../../api/client";
import type { LifecyclePromote } from "../../components/LifecycleTrack";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { orgResourcesPath } from "../orgResources";
import { ORG_GUIDING_PRINCIPLES_SECTION_KEY } from "./orgResourceKeys";

/** Every lifecycle action this page offers; keys the confirm-dialog copy as in `StrategyDetailPage.tsx`, with `approve` going straight from Proposed to Approved. */
type TransitionAction = "approve" | "activate" | "supersede" | "retire";

const TRANSITION_COPY: Record<TransitionAction, { title: string; body: string; confirmLabel: string }> = {
  approve: {
    title: "Approve this Guiding Principle?",
    body: "This records a formal approval in the audit trail. A comment is optional.",
    confirmLabel: "Approve",
  },
  activate: {
    title: "Activate this Guiding Principle?",
    body: "This marks the Guiding Principle as currently in force. A comment is optional.",
    confirmLabel: "Activate",
  },
  supersede: {
    title: "Supersede this Guiding Principle?",
    body: "This Guiding Principle will be marked Superseded. A comment is optional. To record which Guiding Principle replaces it, use the Relationships section's \"Supersedes another Guiding Principle\" option instead.",
    confirmLabel: "Supersede",
  },
  retire: {
    title: "Retire this Guiding Principle?",
    body: "This marks the Guiding Principle's lifecycle as ended. A comment is optional.",
    confirmLabel: "Retire",
  },
};

const MAIN_PATH = ["draft", "proposed", "approved", "active"] as const;

export function GuidingPrincipleDetailPage() {
  const { projectId, organizationId, guidingPrincipleId } = useParams<{
    projectId?: string;
    organizationId?: string;
    guidingPrincipleId: string;
  }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectGuidingPrincipleApi : orgGuidingPrincipleApi;
  const scopeId = projectId ?? organizationId;
  const backLink = projectId
    ? `/projects/${projectId}/modules/context_strategy/guiding-principles`
    : organizationId ? orgResourcesPath(organizationId, ORG_GUIDING_PRINCIPLES_SECTION_KEY) : "/org-resources";

  const [guidingPrinciple, setGuidingPrinciple] = useState<GuidingPrinciple | null>(null);
  const lifecycle = useProjectLifecycle(projectId, "guiding_principle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<GuidingPrincipleVersion[] | null>(null);
  const [comments, setComments] = useState<GuidingPrincipleComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [fetchedOwnerOrgId, setOwnerOrgId] = useState<string | undefined>(undefined);
  const ownerOrgId = organizationId ?? fetchedOwnerOrgId;

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [sendingBack, setSendingBack] = useState(false);
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);

  useEffect(() => {
    if (!scopeId || !guidingPrincipleId) return;
    scopedApi.get(scopeId, guidingPrincipleId).then(setGuidingPrinciple).catch((err) => {
      setLoadError(toErrorMessage(err, "This Guiding Principle could not be found, or you do not have access to it."));
    });
    scopedApi.listVersions(scopeId, guidingPrincipleId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, guidingPrincipleId]);

  // The owner picker needs the organisation's user list; a project-scoped principle fetches its project once to
  // resolve `organization_id`, as `PainPointDetailPage.tsx` does.
  useEffect(() => {
    if (organizationId || !projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => setOwnerOrgId(p.organization_id));
  }, [projectId, organizationId]);

  useEffect(() => {
    if (!ownerOrgId) return;
    void api.get<OrgUser[]>(`/api/v1/orgs/${ownerOrgId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [ownerOrgId]);

  async function reloadCommentsAndFiles() {
    if (!scopeId || !guidingPrincipleId) return;
    try {
      const [c, f] = await Promise.all([
        scopedApi.listComments(scopeId, guidingPrincipleId),
        scopedApi.listFiles(scopeId, guidingPrincipleId),
      ]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this Guiding Principle's comments/files."), "error");
    }
  }

  useLoadOnChange(reloadCommentsAndFiles, [scopeId, guidingPrincipleId]);

  async function runTransition(action: () => Promise<GuidingPrinciple>, successMessage: string) {
    try {
      const updated = await action();
      showToast(successMessage);
      setGuidingPrinciple(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Guiding Principle."), "error");
    }
  }

  async function saveEdit(values: GuidingPrincipleFieldValues) {
    if (!scopeId || !guidingPrinciple) return;
    setFormError(null);
    try {
      const updated = await scopedApi.update(scopeId, guidingPrinciple.id, { ...values, owner: guidingPrinciple.owner });
      showToast("Guiding Principle updated.");
      setEditing(false);
      setGuidingPrinciple(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Guiding Principle."));
    }
  }

  async function assignOwner(owner: PrincipalRef | null) {
    if (!scopeId || !guidingPrinciple) return;
    try {
      const updated = await scopedApi.update(scopeId, guidingPrinciple.id, {
        name: guidingPrinciple.name, principle_statement: guidingPrinciple.principle_statement,
        rationale: guidingPrinciple.rationale, priority: guidingPrinciple.priority,
        change_note: "", owner,
      });
      showToast("Owner updated.");
      setGuidingPrinciple(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Guiding Principle's owner."), "error");
    }
  }

  const archive = useArchiveAction({
    noun: "Guiding Principle",
    isArchived: guidingPrinciple?.is_archived ?? false,
    hidden: !guidingPrinciple,
    archiveBody: "This Guiding Principle will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!scopeId || !guidingPrinciple) return;
      await runTransition(
        () => (guidingPrinciple.is_archived ? scopedApi.unarchive(scopeId, guidingPrinciple.id) : scopedApi.archive(scopeId, guidingPrinciple.id)),
        guidingPrinciple.is_archived ? "Guiding Principle unarchived." : "Guiding Principle archived.",
      );
    },
  });

  const codeOwner = useRecordOwnerCode(guidingPrinciple ?? {});
  const skipSteps = useSkipSteps<GuidingPrinciple>({
    lifecycle, current: guidingPrinciple?.status ?? "", labels: GUIDING_PRINCIPLE_STATUS_LABEL, noun: "Guiding Principle",
    move: (target, reason) => {
      if (!scopeId || !guidingPrinciple) return Promise.reject(new Error("This move is not available."));
      if (target === "approved") return withLifecycleSkip(reason, () => scopedApi.approve(scopeId, guidingPrinciple.id));
      return Promise.reject(new Error("This move is not available."));
    },
    onMoved: setGuidingPrinciple,
  });

  if (!scopeId || !guidingPrincipleId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciple === null) return <Spinner />;

  /** Attaches a file to this record: the Attachments card and the Markdown fields' Picture button share it. */
  const uploadAttachment = async (file: File): Promise<FileAsset> => {
    const asset = await scopedApi.uploadFile(scopeId, guidingPrinciple.id, file);
    setFiles((prev) => [...prev, asset]);
    return asset;
  };

  // The next forward move: a plain call, or the comment dialog of the approval and activation steps.
  // It goes to the next step the project uses (a project may turn Proposed off).
  const next = lifecycle.nextOnPath(MAIN_PATH, guidingPrinciple.status);
  let promote: LifecyclePromote | undefined;
  if (next === "proposed") {
    promote = { to: "proposed", onPromote: () => runTransition(() => scopedApi.propose(scopeId, guidingPrinciple.id), "Guiding Principle proposed.") };
  } else if (next === "approved") {
    promote = { to: "approved", onPromote: () => setTransitionAction("approve") };
  } else if (next === "active") {
    promote = { to: "active", onPromote: () => setTransitionAction("activate") };
  }

  // An ended Guiding Principle sits after the last main step it reached: any retired one was approved, and was active if a version says so.
  const offPath = guidingPrinciple.status === "superseded" || guidingPrinciple.status === "retired"
    ? {
        key: guidingPrinciple.status,
        label: GUIDING_PRINCIPLE_STATUS_LABEL[guidingPrinciple.status],
        description: GUIDING_PRINCIPLE_STATUS_DESCRIPTION[guidingPrinciple.status],
        locked: true,
        lockedReason: REVIEWED_LOCKED_REASON,
        after: guidingPrinciple.status === "superseded" || versions?.some((v) => v.status === "active") ? "active" : "approved",
      }
    : undefined;

  return (
    <DetailLayout
      pictures={{ files, upload: guidingPrinciple.is_locked ? undefined : uploadAttachment }}
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="guiding_principle" artefactId={guidingPrinciple.id} refreshToken={recordActivityKey(guidingPrinciple)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="guiding_principle"
          artefactId={guidingPrinciple.id}
          actions={({ reload }) => (
            <SupersedeAction
              artefactLabel="Guiding Principle"
              onDone={reload}
              loadCandidates={async () =>
                (await scopedApi.list(scopeId))
                  .filter((other) => other.id !== guidingPrinciple.id)
                  .map((other) => ({ id: other.id, label: other.name }))
              }
              onSupersede={async (oldId) => {
                await scopedApi.createSupersessionLink(scopeId, guidingPrinciple.id, oldId);
              }}
            />
          )}
        />
      }
    >
      <RecordHeader
        recordLabel="Guiding Principle"
        title={guidingPrinciple.name}
        code={guidingPrinciple.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="guiding_principle" artefactId={guidingPrinciple.id} /> : undefined}
        codeOwner={codeOwner}
        back={{ to: backLink, label: "Guiding Principles" }}
        badges={
          <>
          <Badge tone={GUIDING_PRINCIPLE_STATUS_TONE[guidingPrinciple.status]}>
            {GUIDING_PRINCIPLE_STATUS_LABEL[guidingPrinciple.status]}
          </Badge>
          </>
        }
        version={guidingPrinciple.version_number}
        subtitle={`${GUIDING_PRINCIPLE_PRIORITY_LABEL[guidingPrinciple.priority]} priority`}
        onEdit={guidingPrinciple.is_locked ? undefined : () => setEditing(true)}
        actions={[
          skipSteps.menuRow,
          lifecycle.canMove(guidingPrinciple.status, "draft", guidingPrinciple.status === "proposed") && { label: "Send back", onSelect: () => setSendingBack(true) },
          guidingPrinciple.status === "active" && { label: "Supersede", onSelect: () => setTransitionAction("supersede") },
          guidingPrinciple.status === "active" && { label: "Retire", danger: true, onSelect: () => setTransitionAction("retire") },
          archive.item,
        ]}
        lifecycle={{
          steps: lifecycle.visibleSteps(
            lifecycleSteps(MAIN_PATH, GUIDING_PRINCIPLE_STATUS_LABEL, {
              descriptions: GUIDING_PRINCIPLE_STATUS_DESCRIPTION,
              locked: { approved: REVIEWED_LOCKED_REASON, active: REVIEWED_LOCKED_REASON },
            }),
            guidingPrinciple.status,
          ),
          current: guidingPrinciple.status,
          offPath,
          promote,
          skip: skipSteps.track,
        }}
      />
      {archive.dialog}


        <DetailCard>
          <RecordField markdown label="Principle statement" value={guidingPrinciple.principle_statement} />
          {guidingPrinciple.rationale && <RecordField markdown label="Rationale" value={guidingPrinciple.rationale} />}

          <RecordPrincipalField
            label="Owner" ariaLabel="Guiding Principle owner" principal={guidingPrinciple.owner} orgUsers={orgUsers}
            organizationId={ownerOrgId} projectId={projectId} readOnly={false} onChange={assignOwner}
          />
        </DetailCard>


        <VersionHistoryTable
          versions={versions}
          columns={[
            { header: "Status", render: (v) => GUIDING_PRINCIPLE_STATUS_LABEL[v.status] },
            { header: "Owner", render: (v) => <PrincipalBadge principal={v.owner} placeholder="—" /> },
          ]}
        />

        <DetailCard heading="Attachments" rank="supporting">
          <FileAttachmentList
            files={files}
            disabled={guidingPrinciple.is_locked}
            emptyHint={guidingPrinciple.is_locked ? "This Guiding Principle is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => { await uploadAttachment(file); }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, guidingPrinciple.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

        <ArtefactCommentsSection
          comments={comments ?? []}
          currentUserId={user?.id}
          onPost={async (body) => {
            const comment = await scopedApi.addComment(scopeId, guidingPrinciple.id, body);
            setComments((prev) => [...(prev ?? []), comment]);
            return comment;
          }}
          onEdit={async (commentId, body) => {
            const updated = await scopedApi.editComment(scopeId, guidingPrinciple.id, commentId, body);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
          }}
          onUploadAttachment={async (commentId, file) => {
            const asset = await scopedApi.uploadCommentAttachment(scopeId, guidingPrinciple.id, commentId, file);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
          }}
          onRemoveAttachment={async (commentId, fileId) => {
            await scopedApi.removeCommentAttachment(scopeId, guidingPrinciple.id, commentId, fileId);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
          }}
        />

      {editing && (
        <GuidingPrincipleFormModal
          initial={guidingPrinciple}
          scopeLabel={projectId ? "project" : "organisation"}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {skipSteps.dialog}

      {sendingBack && (
        <CommentConfirmDialog
          title="Send this Guiding Principle back to Draft?"
          intro="A comment explaining what needs rework is required."
          commentLabel="Send-back comment"
          commentRequired
          confirmLabel="Send back"
          onConfirm={async (comment) => {
            setSendingBack(false);
            await runTransition(() => scopedApi.sendBack(scopeId, guidingPrinciple.id, comment), "Guiding Principle sent back to draft.");
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
            await runTransition(
              () => scopedApi[action](scopeId, guidingPrinciple.id, comment),
              `Guiding Principle ${TRANSITION_COPY[action].confirmLabel.toLowerCase()}d.`,
            );
          }}
          onCancel={() => setTransitionAction(null)}
        />
      )}

    </DetailLayout>
  );
}
