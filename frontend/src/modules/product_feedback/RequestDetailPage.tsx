/**
 * Module: modules/product_feedback/RequestDetailPage
 *
 * One enhancement request: its fields and scoring, who asked for it (project requests), the lifecycle, merge, the
 * triage move into a project (inbox requests), closing the loop, evidence files, comments and version history.
 * One scope-aware component serves both routes, like the Strategy page: exactly one of `projectId` /
 * `organizationId` is in the URL (`/projects/:projectId/modules/product_feedback/requests/:requestId`,
 * `/orgs/:organizationId/modules/product_feedback/requests/:requestId`, the latter an always-mounted global route).
 *
 * - **Lifecycle** buttons come from the server's `allowed_next_statuses`; declining needs a reason (a required
 *   comment). Delivered is set by hand: when every Requirement realising an accepted request is complete the page
 *   prompts "Ready to deliver?" and never moves the status itself.
 * - **Controls follow `GET .../access`**: someone who may not triage sees no edit, transition, merge or archive
 *   controls (the server refuses them regardless).
 * - **External references** (Jira, ServiceNow, ...) and each requester's **channel** are edited here by a triager;
 *   neither is a version of the request.
 * - **Problem and requesters** are linked with the generic Links panel ("Addresses" a Pain Point, "Realised by" a
 *   Requirement, "Requested by" a Stakeholder, Persona or Engagement). A solution with no Pain Point carries a warning
 *   badge, never a block. An inbox request has no links (links are a project's), so triage it into a project first.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../../api/client";
import { orgScoringApi, projectScoringApi, type ScoringScheme } from "../../api/scoring";
import type { FileAsset, OrgUser, Project } from "../../api/types";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { CommentConfirmDialog } from "../../components/CommentConfirmDialog";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordPrincipalField, VersionHistoryTable } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { orgRequestApi, projectRequestApi } from "./api";
import { mergeCandidates } from "./mergeCandidates";
import { MergeRequestDialog } from "./MergeRequestDialog";
import { MoveToProjectDialog } from "./MoveToProjectDialog";
import { referenceInput, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFormModal } from "./ReferenceFormModal";
import { RequestDemandPanel } from "./RequestDemandPanel";
import { RequestFormModal, type RequestFormValues } from "./RequestFormModal";
import { RequestLoopPanel } from "./RequestLoopPanel";
import { RequestReferencesCard } from "./RequestReferencesCard";
import { RequestScoresPanel } from "./RequestScoresPanel";
import { REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE } from "./types";
import type {
  CloseTheLoop, Demand, EnhancementRequest, ExternalRef, FeedbackAccess, RequestComment, RequestMerge, RequestStatus,
  Requester, RequestVersion,
} from "./types";
import { useExternalSystemChoices, useRequestChannelChoices } from "./useFeedbackLists";

const SCHEME_KEY = "enhancement_request";

/** What a lifecycle button is called, by where the request is and where it goes. */
function transitionLabel(from: RequestStatus, to: RequestStatus): string {
  if (to === "declined") return "Decline";
  if (to === "delivered") return "Mark delivered";
  if (to === "under_review") return from === "new" ? "Start review" : "Back to review";
  if (to === "accepted") return from === "delivered" ? "Reopen" : "Accept";
  return from === "declined" ? "Reopen" : "Back to new";
}

const FORWARD: readonly RequestStatus[] = ["under_review", "accepted", "delivered"];

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}

export function RequestDetailPage() {
  const { projectId, organizationId, requestId } = useParams<{
    projectId?: string; organizationId?: string; requestId: string;
  }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectRequestApi : orgRequestApi;
  const scopeId = projectId ?? organizationId;

  const [request, setRequest] = useState<EnhancementRequest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [access, setAccess] = useState<FeedbackAccess | null>(null);
  const [versions, setVersions] = useState<RequestVersion[] | null>(null);
  const [comments, setComments] = useState<RequestComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [demand, setDemand] = useState<Demand | null>(null);
  const [merges, setMerges] = useState<RequestMerge[] | null>(null);
  const [loop, setLoop] = useState<CloseTheLoop | null>(null);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [mergeCandidateRows, setMergeCandidateRows] = useState<EnhancementRequest[] | null>(null);
  const [unmerging, setUnmerging] = useState(false);
  const [orgProjects, setOrgProjects] = useState<{ id: string; name: string }[]>([]);
  const [pending, setPending] = useState<{ to: RequestStatus } | null>(null);
  const [linksVersion, setLinksVersion] = useState(0);
  const [editingReference, setEditingReference] = useState<ExternalRef | "new" | null>(null);
  const [removingReference, setRemovingReference] = useState<ExternalRef | null>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);

  const organization = projectId ? project?.organization_id : organizationId;
  const systems = useExternalSystemChoices(projectId, organization);
  const channels = useRequestChannelChoices(projectId ?? "");

  useEffect(() => {
    if (!scopeId) return;
    const loadUsers = (orgId: string) => api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    if (projectId) {
      void api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => { setProject(p); void loadUsers(p.organization_id); });
      void projectScoringApi.get(projectId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
    } else {
      void loadUsers(scopeId);
      void orgScoringApi.get(scopeId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
    }
    void scopedApi.getAccess(scopeId).then(setAccess).catch(() => setAccess(null));
  }, [scopeId, projectId, scopedApi]);

  /** Reads the request and everything derived from its requesters and links again. */
  async function refresh() {
    if (!scopeId || !requestId) return;
    try {
      setRequest(await scopedApi.get(scopeId, requestId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "This request could not be found, or you don't have access to it."));
      return;
    }
    void scopedApi.listVersions(scopeId, requestId).then(setVersions).catch(() => setVersions([]));
    void scopedApi.listMerges(scopeId, requestId).then(setMerges).catch(() => setMerges([]));
    if (projectId) {
      void projectRequestApi.getDemand(projectId, requestId).then(setDemand).catch(() => setDemand(null));
      void projectRequestApi.getCloseTheLoop(projectId, requestId).then(setLoop).catch(() => setLoop(null));
    }
  }

  useLoadOnChange(refresh, [scopeId, projectId, requestId]);

  async function reloadCommentsAndFiles() {
    if (!scopeId || !requestId) return;
    try {
      const [c, f] = await Promise.all([scopedApi.listComments(scopeId, requestId), scopedApi.listFiles(scopeId, requestId)]);
      setComments(c);
      setFiles(f);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this request's comments and files."), "error");
    }
  }

  useLoadOnChange(reloadCommentsAndFiles, [scopeId, requestId]);

  /** Runs a change, toasts the outcome and re-reads the page; a refusal is shown, not thrown. */
  async function run(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      await refresh();
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  async function saveEdit(values: RequestFormValues) {
    if (!scopeId || !request) return;
    setFormError(null);
    try {
      setRequest(await scopedApi.update(scopeId, request.id, values));
      showToast("Request updated.");
      setEditing(false);
      await refresh();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update the request."));
    }
  }

  async function setOwner(owner: RequestFormValues["owner"]) {
    if (!scopeId || !request) return;
    await run(() => scopedApi.update(scopeId, request.id, { owner }), "Owner updated.", "Could not update the owner.");
  }

  async function openMerge() {
    if (!scopeId || !request) return;
    try {
      setMergeCandidateRows(mergeCandidates(request, await scopedApi.list(scopeId, { open_only: true })));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load the requests to merge into."), "error");
    }
  }

  async function openMove() {
    if (!organizationId) return;
    setMoveError(null);
    try {
      const projects = await api.get<{ id: string; name: string }[]>(`/api/v1/projects?organization_id=${organizationId}&archived=false`);
      setOrgProjects(projects);
      setMoving(true);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load the organisation's projects."), "error");
    }
  }

  async function saveReference(draft: ReferenceDraft) {
    if (!scopeId || !request) return;
    setReferenceError(null);
    try {
      if (editingReference && editingReference !== "new") {
        await scopedApi.updateReference(scopeId, request.id, editingReference.id, referenceInput(draft));
      } else {
        await scopedApi.addReference(scopeId, request.id, referenceInput(draft));
      }
      showToast(editingReference === "new" ? "Reference added." : "Reference updated.");
      setEditingReference(null);
      await refresh();
    } catch (err) {
      setReferenceError(toErrorMessage(err, "Could not save the reference."));
    }
  }

  async function setChannel(requester: Requester, channelId: string | null) {
    if (!projectId || !request) return;
    try {
      setDemand(await projectRequestApi.setRequesterChannel(projectId, request.id, {
        parties: [{ artefact_type: requester.artefact_type, id: requester.id }], channel_id: channelId,
      }));
      showToast(channelId ? "Channel recorded." : "Channel cleared.");
      void projectRequestApi.getCloseTheLoop(projectId, request.id).then(setLoop).catch(() => undefined);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not record the channel."), "error");
      throw err;
    }
  }

  const archive = useArchiveAction({
    noun: "request",
    isArchived: request?.is_archived ?? false,
    hidden: !request || !access?.can_triage,
    archiveBody: "This request will no longer appear in the active list. Nothing is deleted, and it stays available for the record.",
    onToggle: async () => {
      if (!scopeId || !request) return;
      await run(
        () => (request.is_archived ? scopedApi.unarchive(scopeId, request.id) : scopedApi.archive(scopeId, request.id)),
        request.is_archived ? "Request restored." : "Request archived.", "Could not update the request.",
      );
    },
  });

  const codeOwner = useRecordOwnerCode(request ?? {});
  if (!scopeId || !requestId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (request === null) return <Spinner />;

  const canTriage = access?.can_triage === true;
  const isDuplicate = request.status === "duplicate";
  const listPath = projectId ? `/projects/${projectId}/modules/product_feedback/requests` : "/org-overview";
  const moves = request.allowed_next_statuses.filter((to) => !request.is_archived && canTriage && to !== "duplicate");
  const delivering = pending?.to === "delivered";
  const showLoop = Boolean(projectId) && loop !== null && (request.status === "delivered" || request.status === "declined");
  const readyToDeliver = Boolean(loop?.suggest_delivered) && request.status === "accepted" && canTriage;

  return (
    <DetailLayout
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="enhancement_request" artefactId={request.id} refreshToken={recordActivityKey(request)} /> : undefined}
      aside={
        <ArtefactLinksPanel
          projectId={projectId} artefactType="enhancement_request" artefactId={request.id}
          refreshToken={linksVersion} onChanged={() => { setLinksVersion((n) => n + 1); void refresh(); }}
        />
      }
    >
      <RecordHeader
        recordLabel="Request"
        title={request.title}
        code={request.unique_code}
        codeOwner={codeOwner}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="enhancement_request" artefactId={request.id} /> : undefined}
        back={{ to: listPath, label: projectId ? "← Enhancement requests" : "← Organisation overview" }}
        version={request.version_number}
        badges={
          <>
            <Badge tone={REQUEST_STATUS_TONE[request.status]}>{REQUEST_STATUS_LABEL[request.status]}</Badge>
            {request.is_archived && <Badge tone="muted">Archived</Badge>}
            {projectId && request.pain_point_count === 0 && !isDuplicate && request.status !== "declined" && (
              <Badge tone="warning" title="This is a solution with no stated problem. Link the Pain Point it addresses with “Addresses” in the Links panel.">
                No Pain Point linked
              </Badge>
            )}
          </>
        }
        subtitle={isDuplicate && request.merged_into ? (
          <>Duplicate of <Link to={`${projectId ? `/projects/${projectId}` : `/orgs/${organizationId}`}/modules/product_feedback/requests/${request.merged_into.id}`}>
            {request.merged_into.unique_code} {request.merged_into.title}
          </Link></>
        ) : undefined}
        onEdit={canTriage ? () => setEditing(true) : undefined}
        actions={[
          canTriage && !isDuplicate && !request.is_archived && { label: "Merge into another request…", onSelect: () => void openMerge() },
          canTriage && !projectId && !request.is_archived && !isDuplicate && { label: "Move to a project…", onSelect: () => void openMove() },
          archive.item,
        ]}
        transitions={
          <>
            {isDuplicate && canTriage && <button className="btn btn-primary" onClick={() => setUnmerging(true)}>Undo merge</button>}
            {moves.map((to) => (
              <button
                key={to} className={`btn${FORWARD.includes(to) ? " btn-primary" : to === "declined" ? " btn-danger" : ""}`}
                onClick={() => setPending({ to })}
              >
                {transitionLabel(request.status, to)}
              </button>
            ))}
          </>
        }
      />
      {archive.dialog}

      <div className="stack">
        {readyToDeliver && (
          <DetailCard heading="Ready to deliver?">
            <p style={{ margin: 0 }}>
              Every requirement that realises this request is complete. Mark the request delivered when it has shipped.
            </p>
            <div><button className="btn btn-primary" onClick={() => setPending({ to: "delivered" })}>Mark delivered</button></div>
          </DetailCard>
        )}

        <DetailCard>
          {request.description ? <Field label="Description" value={request.description} /> : <p className="text-muted">No description.</p>}
          {request.status === "declined" && request.decline_reason && <Field label="Decline reason" value={request.decline_reason} />}
          <RecordPrincipalField
            label="Owner" ariaLabel="Request owner" principal={request.owner} orgUsers={orgUsers}
            organizationId={organization} projectId={projectId} readOnly={!canTriage} onChange={(o) => void setOwner(o)}
          />
        </DetailCard>

        <RequestReferencesCard
          references={request.external_refs} canEdit={canTriage && !request.is_archived}
          onAdd={() => { setReferenceError(null); setEditingReference("new"); }}
          onEdit={(ref) => { setReferenceError(null); setEditingReference(ref); }}
          onRemove={setRemovingReference}
        />

        <RequestScoresPanel request={request} scheme={scheme} showDemand={Boolean(projectId)} />

        {projectId && (
          <RequestDemandPanel
            projectId={projectId} demand={demand} merges={merges} channels={channels}
            canSetChannel={canTriage && !request.is_archived} onSetChannel={setChannel}
          />
        )}

        {showLoop && loop && (
          <RequestLoopPanel
            loop={loop}
            onInformed={async (parties, informed, note) => {
              try {
                setLoop(await projectRequestApi.setInformed(projectId!, request.id, { parties, informed, note }));
                showToast(informed ? "Recorded as told." : "Told status withdrawn.");
                void refresh();
              } catch (err) {
                showToast(toErrorMessage(err, "Could not record that."), "error");
              }
            }}
          />
        )}

        <VersionHistoryTable
          versions={versions}
          columns={[
            { header: "Status", render: (v: RequestVersion) => REQUEST_STATUS_LABEL[v.status] },
          ]}
        />

        <DetailCard heading="Evidence">
          <FileAttachmentList
            files={files}
            disabled={!canTriage || request.is_archived}
            emptyHint={canTriage ? undefined : "Only a triager can attach evidence to a request."}
            onUpload={async (file) => {
              const asset = await scopedApi.uploadFile(scopeId, request.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, request.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>

        <ArtefactCommentsSection
          comments={comments ?? []}
          currentUserId={user?.id}
          onPost={async (body) => {
            const comment = await scopedApi.addComment(scopeId, request.id, body);
            setComments((prev) => [...(prev ?? []), comment]);
            return comment;
          }}
          onEdit={async (commentId, body) => {
            const updated = await scopedApi.editComment(scopeId, request.id, commentId, body);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
          }}
          onUploadAttachment={async (commentId, file) => {
            const asset = await scopedApi.uploadCommentAttachment(scopeId, request.id, commentId, file);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
          }}
          onRemoveAttachment={async (commentId, fileId) => {
            await scopedApi.removeCommentAttachment(scopeId, request.id, commentId, fileId);
            setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
          }}
        />
      </div>

      {editing && (
        <RequestFormModal
          initial={request} scopeLabel={projectId ? "project" : "organisation inbox"} scheme={scheme} orgUsers={orgUsers}
          organizationId={organization} projectId={projectId} error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }} onSave={saveEdit}
        />
      )}

      {editingReference && (
        <ReferenceFormModal
          initial={editingReference === "new" ? undefined : editingReference} systems={systems} error={referenceError}
          onCancel={() => { setEditingReference(null); setReferenceError(null); }} onSave={(draft) => void saveReference(draft)}
        />
      )}

      {removingReference && (
        <ConfirmDialog
          title="Remove this reference?"
          message={`The link to ${removingReference.system_name} ${removingReference.key || removingReference.url || ""} is removed from this request. The item itself is not touched.`}
          confirmLabel="Remove"
          onCancel={() => setRemovingReference(null)}
          onConfirm={async () => {
            const target = removingReference;
            setRemovingReference(null);
            await run(() => scopedApi.removeReference(scopeId, request.id, target.id), "Reference removed.", "Could not remove the reference.");
          }}
        />
      )}

      {pending && (
        <CommentConfirmDialog
          title={pending.to === "declined" ? "Decline this request?" : `${transitionLabel(request.status, pending.to)}?`}
          intro={
            pending.to === "declined" ? "A reason is required. It is kept with the request and shown to anyone told the outcome."
              : delivering ? "This records that the request has shipped, so the people who asked can be told. A comment is optional."
              : "A comment is optional."
          }
          commentLabel={pending.to === "declined" ? "Decline reason" : "Comment"}
          commentRequired={pending.to === "declined"}
          confirmLabel={transitionLabel(request.status, pending.to)}
          onConfirm={async (comment) => {
            const { to } = pending;
            setPending(null);
            await run(() => scopedApi.transition(scopeId, request.id, to, comment), `Request ${REQUEST_STATUS_LABEL[to].toLowerCase()}.`, "Could not change the request's status.");
          }}
          onCancel={() => setPending(null)}
        />
      )}

      {mergeCandidateRows && (
        <MergeRequestDialog
          request={request} candidates={mergeCandidateRows}
          onCancel={() => setMergeCandidateRows(null)}
          onMerge={async (canonicalId, note) => {
            setMergeCandidateRows(null);
            await run(() => scopedApi.merge(scopeId, request.id, canonicalId, note), "Request merged.", "Could not merge the request.");
          }}
        />
      )}

      {unmerging && (
        <ConfirmDialog
          title="Undo this merge?"
          message="The request returns to the status it had before the merge, and its requesters stop counting toward the other request."
          confirmLabel="Undo merge"
          onCancel={() => setUnmerging(false)}
          onConfirm={async () => {
            setUnmerging(false);
            await run(() => scopedApi.unmerge(scopeId, request.id), "Merge undone.", "Could not undo the merge.");
          }}
        />
      )}

      {moving && organizationId && (
        <MoveToProjectDialog
          code={request.unique_code} projects={orgProjects} error={moveError}
          onCancel={() => { setMoving(false); setMoveError(null); }}
          onMove={async (targetProjectId) => {
            setMoveError(null);
            try {
              const moved = await orgRequestApi.moveToProject(organizationId, request.id, targetProjectId);
              showToast(`Moved to ${moved.unique_code}.`);
              navigate(`/projects/${targetProjectId}/modules/product_feedback/requests/${moved.id}`);
            } catch (err) {
              setMoveError(toErrorMessage(err, "Could not move the request."));
            }
          }}
        />
      )}
    </DetailLayout>
  );
}
