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
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { artefactLinksApi, type CollectedLink } from "../../api/artefactLinks";
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
import { Modal } from "../../components/Modal";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordPrincipalField, VersionHistoryTable } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { SectionOrderEditor } from "../../components/SectionOrderEditor";
import { Spinner } from "../../components/Spinner";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUiPreference } from "../../hooks/useUiPreference";
import { useRecordOwnerCode } from "../../hooks/useOrganizationCode";
import { resolveSectionOrder } from "../../utils/sectionOrder";
import { orgRequestApi, projectRequestApi } from "./api";
import { AddRequestersModal } from "./AddRequestersModal";
import { mergeCandidates } from "./mergeCandidates";
import { MergeRequestDialog } from "./MergeRequestDialog";
import { MoveToProjectDialog } from "./MoveToProjectDialog";
import { referenceInput, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFormModal } from "./ReferenceFormModal";
import { RequestDemandPanel } from "./RequestDemandPanel";
import { RequestFormModal, type RequestFormValues } from "./RequestFormModal";
import { RequestLoopPanel } from "./RequestLoopPanel";
import { RequestReferencesCard } from "./RequestReferencesCard";
import { REQUEST_PAGE_SECTIONS, REQUEST_SECTION_KEYS, REQUEST_SECTIONS_PREFERENCE } from "./requestSections";
import { RequestScoresPanel } from "./RequestScoresPanel";
import { REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE } from "./types";
import type {
  CloseTheLoop, Demand, EnhancementRequest, ExternalRef, FeedbackAccess, RequestComment, RequestMerge, RequestStatus,
  Requester, RequestVersion,
} from "./types";
import { useExternalReferencesEnabled } from "./useExternalReferences";
import { useExternalSystemChoices, useRequestChannelChoices } from "./useFeedbackLists";

const SCHEME_KEY = "enhancement_request";

/** How many requesters the Demand card loads at first and with each Show more. */
const REQUESTER_PAGE = 25;

/** What a lifecycle button is called, by where the request is and where it goes. */
function transitionLabel(from: RequestStatus, to: RequestStatus): string {
  if (to === "declined") return "Decline";
  if (to === "delivered") return "Mark delivered";
  if (to === "under_review") return from === "new" ? "Mark under review" : "Return to review";
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
  const [loadingMore, setLoadingMore] = useState(false);
  const [addingRequesters, setAddingRequesters] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [removingRequester, setRemovingRequester] = useState<{ linkId: string; name: string; kind: "requester" | "engagement" } | null>(null);
  const [projectOrder, setProjectOrder] = useState<string[] | null>(null);
  // A person's own order for the sections (empty: the project's, else the built-in one).
  const [personalOrder, setPersonalOrder] = useUiPreference<string[]>(REQUEST_SECTIONS_PREFERENCE, []);

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
  const commitRequesters = useCommitQuickLinks(projectId ?? "", "enhancement_request");
  const referencesOn = useExternalReferencesEnabled(projectId, organization);

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
    if (projectId) void projectRequestApi.getSettings(projectId).then((x) => setProjectOrder(x.request_page_sections)).catch(() => setProjectOrder(null));
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
      void reloadDemand();
      void projectRequestApi.getCloseTheLoop(projectId, requestId).then(setLoop).catch(() => setLoop(null));
    }
  }

  useLoadOnChange(refresh, [scopeId, projectId, requestId]);

  /** Reads the requesters again, as many as are on screen (at least one page), so a change never collapses a long list. */
  async function reloadDemand() {
    if (!projectId || !requestId) return;
    const loaded = demand?.requesters.length ?? 0;
    try {
      setDemand(await projectRequestApi.getDemand(projectId, requestId, { limit: Math.min(500, Math.max(loaded, REQUESTER_PAGE)) }));
    } catch {
      setDemand(null);
    }
  }

  /** Appends the next page of requesters. */
  async function showMoreRequesters() {
    if (!projectId || !requestId || !demand) return;
    setLoadingMore(true);
    try {
      const next = await projectRequestApi.getDemand(projectId, requestId, { limit: REQUESTER_PAGE, offset: demand.requesters.length });
      setDemand((prev) => (prev ? { ...next, requesters: [...prev.requesters, ...next.requesters] } : next));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load more requesters."), "error");
    } finally {
      setLoadingMore(false);
    }
  }

  /** Removes the request's own "Requested by" link (a requester, or an Engagement it was raised in), then shows the result. */
  async function removeRequester(target: { linkId: string; name: string; kind: "requester" | "engagement" }) {
    if (!projectId || !request) return;
    try {
      await artefactLinksApi.remove(projectId, "enhancement_request", request.id, target.linkId);
      showToast(target.kind === "engagement" ? "Engagement removed." : "Requester removed.");
      setRemovingRequester(null);
      await refresh();
      setLinksVersion((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not remove it."), "error");
      setRemovingRequester(null);
    }
  }

  /** Records the chosen requesters as "Requested by" links, then shows them. */
  async function addRequesters(links: CollectedLink[]) {
    if (!request) return;
    const added = await commitRequesters(request.id, links);
    if (added) setAddingRequesters(false);
    await refresh();
    setLinksVersion((n) => n + 1);
  }

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

  async function saveEdit(values: RequestFormValues, requesters: CollectedLink[]) {
    if (!scopeId || !request) return;
    setFormError(null);
    try {
      setRequest(await scopedApi.update(scopeId, request.id, values));
      showToast("Request updated.");
      setEditing(false);
      await commitRequesters(request.id, requesters);
      await refresh();
      if (requesters.length > 0) setLinksVersion((n) => n + 1);
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
      await projectRequestApi.setRequesterChannel(projectId, request.id, {
        parties: [{ artefact_type: requester.artefact_type, id: requester.id }], channel_id: channelId,
      });
      await reloadDemand();
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

  /** Each arrangeable section's content, keyed as `REQUEST_PAGE_SECTIONS`; an empty one (nothing to show here) is skipped. */
  const sectionNodes: Record<string, ReactNode> = {
    details: (
      <>
          <DetailCard>
            {request.description ? <Field label="Description" value={request.description} /> : <p className="text-muted">No description.</p>}
            {request.status === "declined" && request.decline_reason && <Field label="Decline reason" value={request.decline_reason} />}
            <RecordPrincipalField
              label="Owner" ariaLabel="Request owner" principal={request.owner} orgUsers={orgUsers}
              organizationId={organization} projectId={projectId} readOnly={!canTriage} onChange={(o) => void setOwner(o)}
            />
          </DetailCard>
      </>
    ),
    references: (
      <>
          {referencesOn && (
            <RequestReferencesCard
              references={request.external_refs} canEdit={canTriage && !request.is_archived}
              onAdd={() => { setReferenceError(null); setEditingReference("new"); }}
              onEdit={(ref) => { setReferenceError(null); setEditingReference(ref); }}
              onRemove={setRemovingReference}
            />
          )}
      </>
    ),
    scoring: (
      <>
          <RequestScoresPanel request={request} scheme={scheme} showDemand={Boolean(projectId)} />
      </>
    ),
    demand: (
      <>
          {projectId && (
            <RequestDemandPanel
              projectId={projectId} demand={demand} merges={merges} channels={channels}
              canSetChannel={canTriage && !request.is_archived} onSetChannel={setChannel}
              onAddRequesters={canTriage && !request.is_archived ? () => setAddingRequesters(true) : undefined}
            onRemoveRequester={canTriage && !request.is_archived ? (linkId, name, kind) => setRemovingRequester({ linkId, name, kind }) : undefined}
              onShowMore={() => void showMoreRequesters()} loadingMore={loadingMore}
            />
          )}
      </>
    ),
    loop: (
      <>
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
      </>
    ),
    versions: (
      <>
          <VersionHistoryTable
            versions={versions}
            columns={[
              { header: "Status", render: (v: RequestVersion) => REQUEST_STATUS_LABEL[v.status] },
            ]}
          />
      </>
    ),
    evidence: (
      <>
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
      </>
    ),
    comments: (
      <>
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
      </>
    ),
  };
  const availableSections = REQUEST_SECTION_KEYS.filter((key) => (key !== "references" || referencesOn) && (key !== "demand" || Boolean(projectId)) && (key !== "loop" || showLoop));
  const sectionOrder = resolveSectionOrder(availableSections, personalOrder, projectOrder);

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
          { label: "Arrange sections…", onSelect: () => setArranging(true) },
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

        {sectionOrder.map((key) => <Fragment key={key}>{sectionNodes[key]}</Fragment>)}
      </div>

      {editing && (
        <RequestFormModal
          initial={request} scopeLabel={projectId ? "project" : "organisation inbox"} scheme={scheme} orgUsers={orgUsers}
          organizationId={organization} projectId={projectId} error={formError}
          currentRequesters={demand ? { requesters: demand.requesters, total: demand.requester_count } : undefined}
          onCancel={() => { setEditing(false); setFormError(null); }} onSave={saveEdit}
        />
      )}

      {arranging && (
        <Modal title="Arrange sections" onClose={() => setArranging(false)}>
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>
              Choose the order of the sections on request pages. This is your own order, for every request{projectId ? "; until you set one the project's order applies" : ""}.
            </p>
            <SectionOrderEditor
              sections={REQUEST_PAGE_SECTIONS} order={sectionOrder} ariaLabel="Section order"
              onChange={setPersonalOrder}
              onReset={() => setPersonalOrder([])} resetLabel={projectOrder ? "Use the project's order" : "Use the built-in order"}
              resetDisabled={personalOrder.length === 0}
            />
            <div><button type="button" className="btn btn-primary" onClick={() => setArranging(false)}>Done</button></div>
          </div>
        </Modal>
      )}

      {removingRequester && (
        <ConfirmDialog
          title={removingRequester.kind === "engagement" ? "Remove this Engagement?" : "Remove this requester?"}
          message={removingRequester.kind === "engagement"
            ? `${removingRequester.name} is no longer recorded as somewhere this request was raised. People it reached who are not requesters in their own right stop counting toward the demand. The Engagement itself is not touched.`
            : `${removingRequester.name} is no longer recorded as having asked for this request, and stops counting toward its demand. The record itself is not touched.`}
          confirmLabel="Remove"
          onCancel={() => setRemovingRequester(null)}
          onConfirm={() => void removeRequester(removingRequester)}
        />
      )}

      {addingRequesters && projectId && (
        <AddRequestersModal projectId={projectId} onCancel={() => setAddingRequesters(false)} onSave={addRequesters} />
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
