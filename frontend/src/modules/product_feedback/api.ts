/**
 * Module: modules/product_feedback/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for the endpoints of
 * `backend/app/modules/product_feedback/{project_router,router}.py`.
 *
 * A request is owned by a project or by the organisation (its inbox), and the two routers mirror each other for
 * everything the inbox supports (CRUD, lifecycle, merge, comments, files), so `buildRequestApi` is one factory
 * parameterised by the base URL: `projectRequestApi` takes a `project_id`, `orgRequestApi` an `organization_id`.
 * The pieces only one tier has sit on that tier's object: demand, closing the loop and the settings belong to a
 * project (an inbox request has no links, so no requesters), moving a request into a project to the inbox.
 * Requesters, Pain Points and Requirements are authored with the generic link endpoints (`ArtefactLinksPanel`).
 *
 * The two classified lists (external systems, request channels) have an organisation tier and a project tier, each
 * shaped as the shared `TypeVocabularyPanels` expect (`systemTypes`, `channelTypes`); the same lists feed the pickers
 * (`feedbackListApi`).
 */
import { api } from "../../api/client";
import { appendScopeParam, type ScopeListFilters } from "../../api/projectScope";
import { appendTagParams, type TagListFilters } from "../../api/tags";
import type { FileAsset } from "../../api/types";
import type { EffectiveTypeRow, OrgTypeRow } from "../../components/TypeVocabularyPanels";
import type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import type {
  ChannelUpdate, CloseTheLoop, Demand, EnhancementRequest, EnhancementRequestCreate, EnhancementRequestUpdate,
  ExternalRef, ExternalRefInput, FeedbackSettings, FeedbackAccess, InformedUpdate, OpenLoop, RequestComment, RequestMerge,
  RequestStatus, RequestVersion, SubmissionPolicy,
} from "./types";

/** The filters a request list takes; the server applies them, so a page's export sees the same rows. */
export interface RequestListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  status?: RequestStatus;
  open_only?: boolean;
  search?: string;
  /** Models to score (the first is primary); omitted, the enabled models. */
  scoring_model?: string[];
  /** Keep requests with (`scored`) or without (`unscored`) a level on every manual axis of the first model. */
  scored?: "scored" | "unscored";
  /** Keep requests lacking a level on this axis. */
  missing_axis?: string;
}

function listQuery(filters: RequestListFilters): string {
  const params = new URLSearchParams();
  if (filters.include_archived) params.set("include_archived", "true");
  if (filters.status) params.set("status", filters.status);
  if (filters.open_only) params.set("open_only", "true");
  if (filters.search) params.set("search", filters.search);
  for (const model of filters.scoring_model ?? []) params.append("scoring_model", model);
  if (filters.scored) params.set("scored", filters.scored);
  if (filters.missing_axis) params.set("missing_axis", filters.missing_axis);
  appendTagParams(params, filters);
  appendScopeParam(params, filters);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** The `scoring_model` query for a single read (a detail page). */
function modelQuery(models?: string[]): string {
  if (!models || models.length === 0) return "";
  return `?${models.map((m) => `scoring_model=${encodeURIComponent(m)}`).join("&")}`;
}

function buildRequestApi(base: (id: string) => string) {
  const url = (id: string, requestId: string) => `${base(id)}/requests/${requestId}`;
  return {
    /** What the viewer may do here, so a page offers only controls the server will accept. */
    getAccess: (id: string) => api.get<FeedbackAccess>(`${base(id)}/access`),
    list: (id: string, filters: RequestListFilters = {}) =>
      api.get<EnhancementRequest[]>(`${base(id)}/requests${listQuery(filters)}`),
    create: (id: string, values: EnhancementRequestCreate) => api.post<EnhancementRequest>(`${base(id)}/requests`, values),
    get: (id: string, requestId: string, models?: string[]) =>
      api.get<EnhancementRequest>(`${url(id, requestId)}${modelQuery(models)}`),
    update: (id: string, requestId: string, values: EnhancementRequestUpdate) =>
      api.put<EnhancementRequest>(url(id, requestId), values),
    listVersions: (id: string, requestId: string) => api.get<RequestVersion[]>(`${url(id, requestId)}/versions`),
    /** A lifecycle move; `comment` is the decline reason when declining. */
    transition: (id: string, requestId: string, status: RequestStatus, comment = "") =>
      api.post<EnhancementRequest>(`${url(id, requestId)}/transition`, { status, comment }),
    archive: (id: string, requestId: string) => api.post<EnhancementRequest>(`${url(id, requestId)}/archive`),
    unarchive: (id: string, requestId: string) => api.post<EnhancementRequest>(`${url(id, requestId)}/unarchive`),

    merge: (id: string, requestId: string, canonicalId: string, note = "") =>
      api.post<EnhancementRequest>(`${url(id, requestId)}/merge`, { canonical_id: canonicalId, note }),
    unmerge: (id: string, requestId: string) => api.post<EnhancementRequest>(`${url(id, requestId)}/unmerge`),
    listMerges: (id: string, requestId: string) => api.get<RequestMerge[]>(`${url(id, requestId)}/merges`),

    listComments: (id: string, requestId: string) => api.get<RequestComment[]>(`${url(id, requestId)}/comments`),
    addComment: (id: string, requestId: string, body: string) =>
      api.post<RequestComment>(`${url(id, requestId)}/comments`, { body }),
    editComment: (id: string, requestId: string, commentId: string, body: string) =>
      api.patch<RequestComment>(`${url(id, requestId)}/comments/${commentId}`, { body }),
    uploadCommentAttachment: (id: string, requestId: string, commentId: string, file: File) =>
      api.postFile<FileAsset>(`${url(id, requestId)}/comments/${commentId}/files`, file),
    removeCommentAttachment: (id: string, requestId: string, commentId: string, fileId: string) =>
      api.delete<void>(`${url(id, requestId)}/comments/${commentId}/files/${fileId}`),

    listReferences: (id: string, requestId: string) => api.get<ExternalRef[]>(`${url(id, requestId)}/references`),
    addReference: (id: string, requestId: string, body: ExternalRefInput) =>
      api.post<ExternalRef>(`${url(id, requestId)}/references`, body),
    updateReference: (id: string, requestId: string, referenceId: string, body: Partial<ExternalRefInput>) =>
      api.patch<ExternalRef>(`${url(id, requestId)}/references/${referenceId}`, body),
    removeReference: (id: string, requestId: string, referenceId: string) =>
      api.delete<void>(`${url(id, requestId)}/references/${referenceId}`),

    listFiles: (id: string, requestId: string) => api.get<FileAsset[]>(`${url(id, requestId)}/files`),
    uploadFile: (id: string, requestId: string, file: File) => api.postFile<FileAsset>(`${url(id, requestId)}/files`, file),
    unlinkFile: (id: string, requestId: string, fileId: string) => api.delete<void>(`${url(id, requestId)}/files/${fileId}`),
  };
}

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/product_feedback`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/product_feedback`;

/** The request type shared by both tiers' API objects, so a page can hold either as one value. */
export type RequestApi = ReturnType<typeof buildRequestApi>;

/** Project requests; the `id` argument is a `project_id`. */
export const projectRequestApi = {
  ...buildRequestApi(projectBase),
  getSettings: (projectId: string) => api.get<FeedbackSettings>(`${projectBase(projectId)}/settings`),
  setSubmissionPolicy: (projectId: string, submission_policy: SubmissionPolicy) =>
    api.put<FeedbackSettings>(`${projectBase(projectId)}/settings`, { submission_policy }),
  getDemand: (projectId: string, requestId: string) =>
    api.get<Demand>(`${projectBase(projectId)}/requests/${requestId}/demand`),
  getCloseTheLoop: (projectId: string, requestId: string) =>
    api.get<CloseTheLoop>(`${projectBase(projectId)}/requests/${requestId}/close-the-loop`),
  setInformed: (projectId: string, requestId: string, body: InformedUpdate) =>
    api.put<CloseTheLoop>(`${projectBase(projectId)}/requests/${requestId}/informed`, body),
  listOpenLoops: (projectId: string) => api.get<OpenLoop[]>(`${projectBase(projectId)}/close-the-loop`),
  /** Records how requesters asked (or clears it with a null channel); returns the refreshed demand view. */
  setRequesterChannel: (projectId: string, requestId: string, body: ChannelUpdate) =>
    api.put<Demand>(`${projectBase(projectId)}/requests/${requestId}/requester-channel`, body),
};

/** Organisation inbox requests; the `id` argument is an `organization_id`. */
export const orgRequestApi = {
  ...buildRequestApi(orgBase),
  /** Triages an inbox request into one of the organisation's projects (one-way; refused if it has links). */
  moveToProject: (organizationId: string, requestId: string, projectId: string) =>
    api.post<EnhancementRequest>(`${orgBase(organizationId)}/requests/${requestId}/move-to-project`, { project_id: projectId }),
};

/** Project tier of one of the module's classified lists (`path` is `external-systems` or `request-channels`). */
function projectVocabularyApi(path: string) {
  const url = (projectId: string) => `${projectBase(projectId)}/${path}`;
  return {
    list: (projectId: string) => api.get<EffectiveTypeRow[]>(url(projectId)),
    createLocal: (projectId: string, name: string, displayOrder?: number) =>
      api.post<unknown>(url(projectId), { name, display_order: displayOrder ?? null }),
    override: (
      projectId: string, typeRefId: string,
      values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
    ) => api.put<unknown>(`${url(projectId)}/${typeRefId}`, values),
    delete: (projectId: string, typeRefId: string) => api.delete<void>(`${url(projectId)}/${typeRefId}`),
    listHidden: (projectId: string) => api.get<HiddenDefinition[]>(`${url(projectId)}/hidden`),
    restore: (projectId: string, orgTypeIds?: string[]) =>
      api.post<unknown>(`${url(projectId)}/restore`, { org_type_ids: orgTypeIds ?? null }),
  };
}

/** Organisation tier of one of the module's classified lists. */
function orgVocabularyApi(path: string) {
  const url = (organizationId: string) => `${orgBase(organizationId)}/${path}`;
  return {
    list: (organizationId: string) => api.get<OrgTypeRow[]>(url(organizationId)),
    create: (organizationId: string, name: string) => api.post<OrgTypeRow>(url(organizationId), { name }),
    move: (organizationId: string, typeId: string, direction: "up" | "down") =>
      api.post<OrgTypeRow>(`${url(organizationId)}/${typeId}/move`, { direction }),
    update: (organizationId: string, typeId: string, values: { name?: string; is_active?: boolean }) =>
      api.patch<OrgTypeRow>(`${url(organizationId)}/${typeId}`, values),
    delete: (organizationId: string, typeId: string) => api.delete<void>(`${url(organizationId)}/${typeId}`),
  };
}

/** The external system list (Jira, ServiceNow, ...), in the shapes `TypeVocabularyPanels` take. */
export const systemTypes = { project: projectVocabularyApi("external-systems"), org: orgVocabularyApi("external-systems") };

/** The request channel list (Support ticket, Call, ...), in the shapes `TypeVocabularyPanels` take. */
export const channelTypes = { project: projectVocabularyApi("request-channels"), org: orgVocabularyApi("request-channels") };
