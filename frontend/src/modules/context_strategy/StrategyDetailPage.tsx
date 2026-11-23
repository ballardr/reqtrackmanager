/**
 * Module: modules/context_strategy/StrategyDetailPage
 *
 * A single Strategy's full detail: fields, lifecycle status, versions, comments, attachments, relationships and every
 * lifecycle action. It has `modules/decisions/DecisionDetailPage.tsx`'s structure and its reason for being a routed
 * page rather than a `SidePanel` (`docs/ux-style-guide.md` "Pattern: entity detail panel"): a comment thread, file
 * attachments, relationships and several lifecycle actions each with a `ConfirmDialog`.
 *
 * Scope-aware: a Strategy is organisation- or project-scoped, so one component serves `ProjectStrategiesPage.tsx`
 * (`/projects/:projectId/modules/context_strategy/strategies/:strategyId`, `module.ts` `routes`) and
 * `OrgStrategiesPanel.tsx` (`/orgs/:organizationId/modules/context_strategy/strategies/:strategyId`, `globalRoutes`,
 * not gated by a project's enabled modules). Exactly one of the `projectId`/`organizationId` route parameters is
 * present, mirroring the backend's scope discriminator.
 *
 * Mutating controls always render whatever the caller's role (as `DecisionDetailPage.tsx`); the backend enforces
 * `strategy_owner` / `strategy_approver` (or the organisation equivalents) and a 403 surfaces as a toast. Content edit,
 * archive and file-attach controls are hidden once `strategy.is_locked`.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { FileAsset } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordTags } from "../../components/RecordTags";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { Spinner } from "../../components/Spinner";
import { SupersedeAction } from "../../components/SupersedeAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStrategyApi, projectStrategyApi } from "./api";
import { StrategyFormModal } from "./StrategyFormModal";
import { STRATEGY_PRIORITY_LABEL, STRATEGY_STATUS_LABEL, STRATEGY_STATUS_TONE, STRATEGY_TIME_HORIZON_LABEL } from "./types";
import type { Strategy, StrategyComment, StrategyFieldValues, StrategyVersion } from "./types";
import { RecordHeader } from "../../components/RecordHeader";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { Badge } from "../../components/Badge";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { RecordField } from "../../components/RecordDetailParts";
import { orgResourcesPath } from "../orgResources";
import { ORG_STRATEGIES_SECTION_KEY } from "./orgResourceKeys";

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
    : organizationId ? orgResourcesPath(organizationId, ORG_STRATEGIES_SECTION_KEY) : "/org-resources";

  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null);
  const [comments, setComments] = useState<StrategyComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [sendingBack, setSendingBack] = useState(false);
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);

  useEffect(() => {
    if (!scopeId || !strategyId) return;
    scopedApi.get(scopeId, strategyId).then(setStrategy).catch((err) => {
      setLoadError(toErrorMessage(err, "This Strategy could not be found, or you do not have access to it."));
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

  useLoadOnChange(reloadCommentsAndFiles, [scopeId, strategyId]);

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

  const archive = useArchiveAction({
    noun: "Strategy",
    isArchived: strategy?.is_archived ?? false,
    hidden: !strategy,
    archiveBody: "This Strategy will no longer appear in the active list. Nothing is deleted, and it remains available for historical purposes.",
    onToggle: async () => {
      if (!scopeId || !strategy) return;
      await runTransition(
        () => (strategy.is_archived ? scopedApi.unarchive(scopeId, strategy.id) : scopedApi.archive(scopeId, strategy.id)),
        strategy.is_archived ? "Strategy unarchived." : "Strategy archived.",
      );
    },
  });

  const codeOwner = useRecordOwnerCode(strategy ?? {});
  if (!scopeId || !strategyId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (strategy === null) return <Spinner />;

  /** Attaches a file to this record: the Attachments card and the Markdown fields' Picture button share it. */
  const uploadAttachment = async (file: File): Promise<FileAsset> => {
    const asset = await scopedApi.uploadFile(scopeId, strategy.id, file);
    setFiles((prev) => [...prev, asset]);
    return asset;
  };

  return (
    <DetailLayout
      pictures={{ files, upload: strategy.is_locked ? undefined : uploadAttachment }}
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="strategy" artefactId={strategy.id} refreshToken={recordActivityKey(strategy)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="strategy"
          artefactId={strategy.id}
          actions={({ reload }) => (
            <SupersedeAction
              artefactLabel="Strategy"
              onDone={reload}
              loadCandidates={async () =>
                (await scopedApi.list(scopeId))
                  .filter((other) => other.id !== strategy.id)
                  .map((other) => ({ id: other.id, label: other.title }))
              }
              onSupersede={async (oldId) => {
                await scopedApi.createSupersessionLink(scopeId, strategy.id, oldId);
              }}
            />
          )}
        />
      }
    >
      <RecordHeader
        recordLabel="Strategy"
        title={strategy.title}
        code={strategy.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="strategy" artefactId={strategy.id} /> : undefined}
        codeOwner={codeOwner}
        back={{ to: backLink, label: "Strategies" }}
        badges={
          <>
          <Badge tone={STRATEGY_STATUS_TONE[strategy.status]}>
            {STRATEGY_STATUS_LABEL[strategy.status]}
          </Badge>
          </>
        }
        version={strategy.version_number}
        subtitle={`${STRATEGY_PRIORITY_LABEL[strategy.priority]} priority · ${STRATEGY_TIME_HORIZON_LABEL[strategy.time_horizon]}`}
        onEdit={strategy.is_locked ? undefined : () => setEditing(true)}
        actions={[archive.item]}
        transitions={
          <>
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
          </>
        }
      />
      {archive.dialog}


        <DetailCard>
          <RecordField markdown label="Objective / strategic theme" value={strategy.objective} />
          {strategy.current_state && <RecordField markdown label="Current state" value={strategy.current_state} />}
          {strategy.desired_future_state && <RecordField markdown label="Desired future state" value={strategy.desired_future_state} />}
          {strategy.rationale && <RecordField markdown label="Rationale" value={strategy.rationale} />}
          {strategy.expected_outcomes && <RecordField markdown label="Expected outcomes" value={strategy.expected_outcomes} />}
          {strategy.constraints && <RecordField markdown label="Constraints" value={strategy.constraints} />}
          {strategy.measures_of_success && <RecordField markdown label="Measures of success" value={strategy.measures_of_success} />}
        </DetailCard>


        {versions && versions.length > 1 && (
          <DetailCard heading="Versions" rank="supporting">
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
          </DetailCard>
        )}

        <DetailCard heading="Attachments" rank="supporting">
          <FileAttachmentList
            files={files}
            disabled={strategy.is_locked}
            emptyHint={strategy.is_locked ? "This Strategy is past review; new attachments can no longer be added." : undefined}
            onUpload={async (file) => { await uploadAttachment(file); }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, strategy.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

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
        <CommentConfirmDialog
          title="Send this Strategy back to Draft?"
          intro="A comment explaining what needs rework is required."
          commentLabel="Send-back comment"
          commentRequired
          confirmLabel="Send back"
          onConfirm={async (comment) => {
            setSendingBack(false);
            await runTransition(() => scopedApi.sendBack(scopeId, strategy.id, comment), "Strategy sent back to draft.");
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
            await runTransition(() => scopedApi[action](scopeId, strategy.id, comment), `Strategy ${TRANSITION_COPY[action].confirmLabel.toLowerCase()}d.`);
          }}
          onCancel={() => setTransitionAction(null)}
        />
      )}

    </DetailLayout>
  );
}
