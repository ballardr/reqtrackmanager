/**
 * Module: modules/context_strategy/GuidingPrincipleDetailPage
 *
 * A single Guiding Principle's full detail — mirrors `StrategyDetailPage.tsx`'s exact
 * shape (full field display, current lifecycle status, version history,
 * comments, attachments, relationships, every lifecycle action), adjusted
 * for two genuine differences in Guiding Principle's own backend design:
 *
 * 1. **A shorter, six-state lifecycle with no `under_review` step.**
 *    `Draft -> Proposed -> Approved -> Active -> Superseded/Retired` — from
 *    `Proposed`, this page offers `Approve` (optional comment) and
 *    `Send back` (mandatory comment, this module's "reject"-equivalent)
 *    directly, with no intervening `Submit for review` step
 *    `StrategyDetailPage.tsx` needs for its own seven-state lifecycle.
 * 2. **A dedicated `RecordPrincipalField` for `owner`, not a
 *    `GuidingPrincipleFormModal` field (Decided by: Agent).** The backend
 *    versions `owner` as a plain content field on the same full-replace
 *    `PUT` every other field uses (`schemas.GuidingPrincipleUpdate`,
 *    structurally closer to `FutureStateFieldValues.target_date` than to
 *    Pain Point's genuinely separate "assign owner" surface) — but this
 * frontend still reuses `components/RecordDetailParts`'
 *    `RecordPrincipalField` (a user, an organisation group and, on a project
 *    principle, a project group), mirroring `PainPointDetailPage.tsx`'s
 *    identical choice, for the same reasons: assigning a person or team is a
 *    distinct, higher-frequency action with its own search-first UX, better
 *    served by a dedicated control than buried inside a multi-field
 *    content-edit modal. `assignOwner` below calls
 *    `scopedApi.update` with the Guiding Principle's own current content
 *    fields plus the newly chosen `owner`, the same full-replace pattern
 *    `PainPointDetailPage.tsx`'s own `assignOwner` already establishes —
 *    this exercises the exact "explicit owner-assign-then-clear" behaviour
 * the backend test suite pins.
 *
 * **Scope-aware** (same as `StrategyDetailPage.tsx`): reads
 * whichever of `projectId`/`organizationId` its current route supplies.
 * Unlike `PainPointDetailPage.tsx` (project-scoped only), an org-scoped
 * Guiding Principle has no *project* to fetch for its own organisation id —
 * `organizationId` is used directly for the owner picker's org-user list in
 * that case, and a project fetch (for its `organization_id`) is only needed
 * in the project-scoped case.
 *
 * Every mutating control always renders regardless of the caller's actual
 * role (same posture `StrategyDetailPage.tsx` establishes) — the backend
 * enforces `guiding_principle_owner`/`guiding_principle_approver` (or their
 * org-scoped equivalents) and a 403 surfaces as a toast. Edit/archive/
 * file-attach controls specifically for *content* are hidden once
 * `guidingPrinciple.is_locked` (locked at `APPROVED` and beyond — one state
 * earlier than Strategy/Future State's `UNDER_REVIEW`, per `service.
 * GUIDING_PRINCIPLE_LOCKED_STATUSES`).
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
import { RecordPrincipalField, VersionHistoryTable } from "../../components/RecordDetailParts";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgGuidingPrincipleApi, projectGuidingPrincipleApi } from "./api";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_TONE } from "./types";
import type {
  GuidingPrinciple, GuidingPrincipleComment, GuidingPrincipleFieldValues, GuidingPrincipleVersion,
} from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";

/** Every lifecycle action this page can offer, keyed by the action itself —
 * same generic confirm-dialog-copy pattern as `StrategyDetailPage.tsx`'s own
 * `TransitionAction`/`TRANSITION_COPY`, minus `approve`'s Strategy-only
 * "Under Review" framing (Guiding Principle moves `Proposed -> Approved`
 * directly, no intervening review state). */
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
    : `/org-overview`;
  const backLabel = projectId ? "← Guiding Principle" : "← Organisation overview";

  const [guidingPrinciple, setGuidingPrinciple] = useState<GuidingPrinciple | null>(null);
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
      setLoadError(toErrorMessage(err, "This Guiding Principle could not be found, or you don't have access to it."));
    });
    scopedApi.listVersions(scopeId, guidingPrincipleId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, guidingPrincipleId]);

  // The owner picker needs an organisation's own user list — a project-scoped
  // Guiding Principle has no `organization_id` route param, so its owning
  // project is fetched once to resolve one (mirrors `PainPointDetailPage.tsx`'s
  // identical lookup); an org-scoped Guiding Principle already has it.
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
  if (!scopeId || !guidingPrincipleId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (guidingPrinciple === null) return <Spinner />;

  return (
    <DetailLayout
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
        back={{ to: backLink, label: backLabel }}
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
        actions={[archive.item]}
        transitions={
          <>
          {guidingPrinciple.status === "draft" && (
            <button
              className="btn btn-primary"
              onClick={() => runTransition(() => scopedApi.propose(scopeId, guidingPrinciple.id), "Guiding Principle proposed.")}
            >
              Propose
            </button>
          )}
          {guidingPrinciple.status === "proposed" && (
            <>
              <button className="btn btn-primary" onClick={() => setTransitionAction("approve")}>Approve</button>
              <button className="btn" onClick={() => setSendingBack(true)}>Send back</button>
            </>
              )}
              {guidingPrinciple.status === "approved" && (
                <button className="btn btn-primary" onClick={() => setTransitionAction("activate")}>Activate</button>
              )}
              {guidingPrinciple.status === "active" && (
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

        <DetailCard>
          <Field label="Principle statement" value={guidingPrinciple.principle_statement} />
          {guidingPrinciple.rationale && <Field label="Rationale" value={guidingPrinciple.rationale} />}

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

        <DetailCard heading="Attachments">
          <FileAttachmentList
            files={files}
            disabled={guidingPrinciple.is_locked}
            emptyHint={guidingPrinciple.is_locked ? "This Guiding Principle is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => {
              const asset = await scopedApi.uploadFile(scopeId, guidingPrinciple.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
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
      </div>

      {editing && (
        <GuidingPrincipleFormModal
          initial={guidingPrinciple}
          scopeLabel={projectId ? "project" : "organisation"}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

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

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}
