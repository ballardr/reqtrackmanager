/**
 * Module: modules/context_strategy/api
 *
 * Thin wrapper functions over `api` (frontend/src/api/client.ts) for every Strategy, Future State, Pain Point, Guiding
 * Principle and Open Question endpoint of `backend/app/modules/context_strategy/{router,project_router}.py`, as
 * `modules/decisions/api.ts` does for its module. See `buildFutureStateApi`, `buildGuidingPrincipleApi` and
 * `projectOpenQuestionApi` for why each is a factory or a flat object.
 *
 * Strategy's backend gives every endpoint an identical organisation- and project-scoped twin (same schemas, suffixes
 * and behaviour, differing only in which id builds the URL), so `buildStrategyApi` is one factory parameterised by the
 * base-URL builder and `projectStrategyApi` / `orgStrategyApi` are its two instantiations. An endpoint whose behaviour
 * diverges between scopes can be pulled out of the factory.
 */
import { api } from "../../api/client";
import { appendTagParams, type TagListFilters } from "../../api/tags";
import { appendScopeParam, type ScopeListFilters } from "../../api/projectScope";
import type { FileAsset, PrincipalRef } from "../../api/types";
import type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import type {
  ContextStrategyLink,
  EffectivePainPointType,
  OrgPainPointSubmissionSettings,
  FutureState,
  FutureStateComment,
  FutureStateFieldValues,
  FutureStateLinkKind,
  FutureStateVersion,
  GuidingPrinciple,
  GuidingPrincipleComment,
  GuidingPrincipleFieldValues,
  GuidingPrincipleLinkKind,
  GuidingPrincipleVersion,
  OpenQuestion,
  OpenQuestionComment,
  OpenQuestionFieldValues,
  OpenQuestionLinkKind,
  PainPoint,
  PainPointComment,
  PainPointFieldValues,
  PainPointLinkKind,
  PainPointRollup,
  PainPointScoreInput,
  PainPointScores,
  PainPointScoringTargets,
  PainPointScoringList,
  PainPointSubmissionPolicy,
  PainPointSubmissionSettings,
  PainPointTypeDefinition,
  ProjectPainPointType,
  Strategy,
  StrategyComment,
  StrategyFieldValues,
  StrategyLinkKind,
  StrategyVersion,
} from "./types";

/** The query string of a list read: the archived toggle and the tag filter. */
function listQuery(filters: { include_archived?: boolean } & TagListFilters & ScopeListFilters): string {
  const params = new URLSearchParams();
  if (filters.include_archived) params.set("include_archived", "true");
  appendTagParams(params, filters);
  appendScopeParam(params, filters);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export interface StrategyListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
}

function buildStrategyApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: StrategyListFilters = {}) {
      const query = listQuery(filters);
      return api.get<Strategy[]>(`${base(id)}/strategies${query}`);
    },
    create(id: string, values: Omit<StrategyFieldValues, "change_note">) {
      return api.post<Strategy>(`${base(id)}/strategies`, values);
    },
    get(id: string, strategyId: string) {
      return api.get<Strategy>(`${base(id)}/strategies/${strategyId}`);
    },
    update(id: string, strategyId: string, values: StrategyFieldValues) {
      return api.put<Strategy>(`${base(id)}/strategies/${strategyId}`, values);
    },
    listVersions(id: string, strategyId: string) {
      return api.get<StrategyVersion[]>(`${base(id)}/strategies/${strategyId}/versions`);
    },
    archive(id: string, strategyId: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/archive`);
    },
    unarchive(id: string, strategyId: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/unarchive`);
    },

    // --- Lifecycle transitions ------------------------------------------------
    propose(id: string, strategyId: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/propose`);
    },
    submitForReview(id: string, strategyId: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/submit-for-review`);
    },
    sendBack(id: string, strategyId: string, comment: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/send-back`, { comment });
    },
    approve(id: string, strategyId: string, comment?: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/approve`, { comment: comment || null });
    },
    activate(id: string, strategyId: string, comment?: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/activate`, { comment: comment || null });
    },
    supersede(id: string, strategyId: string, comment?: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/supersede`, { comment: comment || null });
    },
    retire(id: string, strategyId: string, comment?: string) {
      return api.post<Strategy>(`${base(id)}/strategies/${strategyId}/retire`, { comment: comment || null });
    },

    // --- Comments ---------------------------------------------------------
    listComments(id: string, strategyId: string) {
      return api.get<StrategyComment[]>(`${base(id)}/strategies/${strategyId}/comments`);
    },
    addComment(id: string, strategyId: string, body: string) {
      return api.post<StrategyComment>(`${base(id)}/strategies/${strategyId}/comments`, { body });
    },
    editComment(id: string, strategyId: string, commentId: string, body: string) {
      return api.patch<StrategyComment>(`${base(id)}/strategies/${strategyId}/comments/${commentId}`, { body });
    },
    uploadCommentAttachment(id: string, strategyId: string, commentId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/strategies/${strategyId}/comments/${commentId}/files`, file);
    },
    removeCommentAttachment(id: string, strategyId: string, commentId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/strategies/${strategyId}/comments/${commentId}/files/${fileId}`);
    },

    // --- Direct file attachments -------------------------------------------
    listFiles(id: string, strategyId: string) {
      return api.get<FileAsset[]>(`${base(id)}/strategies/${strategyId}/files`);
    },
    uploadFile(id: string, strategyId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/strategies/${strategyId}/files`, file);
    },
    unlinkFile(id: string, strategyId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/strategies/${strategyId}/files/${fileId}`);
    },

    // --- Relationships -------------------------------------------
    listRelationships(id: string, strategyId: string) {
      return api.get<ContextStrategyLink[]>(`${base(id)}/strategies/${strategyId}/relationships`);
    },
    createRelationship(id: string, strategyId: string, kind: StrategyLinkKind, targetId: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/strategies/${strategyId}/relationships`, {
        kind, target_id: targetId,
      });
    },
    createSupersessionLink(id: string, strategyId: string, oldStrategyId: string, comment?: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/strategies/${strategyId}/supersessions`, {
        old_strategy_id: oldStrategyId, comment: comment || null,
      });
    },
  };
}

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/context_strategy`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/context_strategy`;

/** Every Strategy endpoint, project-scoped — `id` parameters below are a
 * `project_id`. */
export const projectStrategyApi = buildStrategyApi(projectBase);
/** Every Strategy endpoint, org-scoped — `id` parameters below are an
 * `organization_id`. */
export const orgStrategyApi = buildStrategyApi(orgBase);

// --- Future State ------------------------------------------------

export interface FutureStateListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
}

/**
 * A sibling factory to `buildStrategyApi`, not a reuse: the endpoint shapes are identical, but the field list differs
 * (no `priority` or `time_horizon`; adds `target_date`), and one factory generic over both field shapes would need
 * TypeScript generics through every payload type to save one ~130-line function. It is parameterised the same way
 * (`base: (id: string) => string`) and points at `/future-states`.
 *
 * `target_date` needs no "explicitly set" flag on the client: `FutureStateUpdate` is a full-replace payload and the
 * router always passes `target_date_explicitly_set=True` for a `PUT` (`project_router.py`
 * `update_project_future_state`), so `update()` sends a date string to set it and `null` to clear it.
 */
function buildFutureStateApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: FutureStateListFilters = {}) {
      const query = listQuery(filters);
      return api.get<FutureState[]>(`${base(id)}/future-states${query}`);
    },
    create(id: string, values: Omit<FutureStateFieldValues, "change_note">) {
      return api.post<FutureState>(`${base(id)}/future-states`, values);
    },
    get(id: string, futureStateId: string) {
      return api.get<FutureState>(`${base(id)}/future-states/${futureStateId}`);
    },
    update(id: string, futureStateId: string, values: FutureStateFieldValues) {
      return api.put<FutureState>(`${base(id)}/future-states/${futureStateId}`, values);
    },
    listVersions(id: string, futureStateId: string) {
      return api.get<FutureStateVersion[]>(`${base(id)}/future-states/${futureStateId}/versions`);
    },
    archive(id: string, futureStateId: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/archive`);
    },
    unarchive(id: string, futureStateId: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/unarchive`);
    },

    // --- Lifecycle transitions ------------------------------------------------
    propose(id: string, futureStateId: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/propose`);
    },
    submitForReview(id: string, futureStateId: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/submit-for-review`);
    },
    sendBack(id: string, futureStateId: string, comment: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/send-back`, { comment });
    },
    approve(id: string, futureStateId: string, comment?: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/approve`, { comment: comment || null });
    },
    activate(id: string, futureStateId: string, comment?: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/activate`, { comment: comment || null });
    },
    supersede(id: string, futureStateId: string, comment?: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/supersede`, { comment: comment || null });
    },
    retire(id: string, futureStateId: string, comment?: string) {
      return api.post<FutureState>(`${base(id)}/future-states/${futureStateId}/retire`, { comment: comment || null });
    },

    // --- Comments ---------------------------------------------------------
    listComments(id: string, futureStateId: string) {
      return api.get<FutureStateComment[]>(`${base(id)}/future-states/${futureStateId}/comments`);
    },
    addComment(id: string, futureStateId: string, body: string) {
      return api.post<FutureStateComment>(`${base(id)}/future-states/${futureStateId}/comments`, { body });
    },
    editComment(id: string, futureStateId: string, commentId: string, body: string) {
      return api.patch<FutureStateComment>(`${base(id)}/future-states/${futureStateId}/comments/${commentId}`, { body });
    },
    uploadCommentAttachment(id: string, futureStateId: string, commentId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/future-states/${futureStateId}/comments/${commentId}/files`, file);
    },
    removeCommentAttachment(id: string, futureStateId: string, commentId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/future-states/${futureStateId}/comments/${commentId}/files/${fileId}`);
    },

    // --- Direct file attachments -------------------------------------------
    listFiles(id: string, futureStateId: string) {
      return api.get<FileAsset[]>(`${base(id)}/future-states/${futureStateId}/files`);
    },
    uploadFile(id: string, futureStateId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/future-states/${futureStateId}/files`, file);
    },
    unlinkFile(id: string, futureStateId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/future-states/${futureStateId}/files/${fileId}`);
    },

    // --- Relationships -------------------------------------------
    listRelationships(id: string, futureStateId: string) {
      return api.get<ContextStrategyLink[]>(`${base(id)}/future-states/${futureStateId}/relationships`);
    },
    createRelationship(id: string, futureStateId: string, kind: FutureStateLinkKind, targetId: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/future-states/${futureStateId}/relationships`, {
        kind, target_id: targetId,
      });
    },
    createSupersessionLink(id: string, futureStateId: string, oldFutureStateId: string, comment?: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/future-states/${futureStateId}/supersessions`, {
        old_future_state_id: oldFutureStateId, comment: comment || null,
      });
    },
  };
}

/** Every Future State endpoint, project-scoped — `id` parameters below are a
 * `project_id`. */
export const projectFutureStateApi = buildFutureStateApi(projectBase);
/** Every Future State endpoint, org-scoped — `id` parameters below are an
 * `organization_id`. */
export const orgFutureStateApi = buildFutureStateApi(orgBase);

// --- Pain Point --------------------------------------------------
//
// No `buildPainPointApi` factory: the factory shape serves an artefact with identical organisation- and
// project-scoped endpoint sets, and Pain Point is project-scoped only. `orgPainPointTypeApi` (organisation-scoped
// `PainPointTypeDefinition` CRUD) and `projectPainPointApi` (the project type-override tier and the Pain Point
// itself) are plain objects, as in `modules/decisions/api.ts`.

/** Builds the `?model_key=&rollup=` query string for the scoring endpoints. */
function scoringQuery(params: { model_key?: string; rollup?: string; include_archived?: boolean }): string {
  const query = new URLSearchParams();
  if (params.model_key) query.set("model_key", params.model_key);
  if (params.rollup) query.set("rollup", params.rollup);
  if (params.include_archived) query.set("include_archived", "true");
  const text = query.toString();
  return text ? `?${text}` : "";
}

export interface PainPointListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
}

/** The organisation's default for who may submit a Pain Point (`null` clears it). */
export const orgPainPointSettingsApi = {
  get(organizationId: string) {
    return api.get<OrgPainPointSubmissionSettings>(`${orgBase(organizationId)}/pain-point-settings`);
  },
  setSubmissionPolicy(organizationId: string, policy: PainPointSubmissionPolicy | null) {
    return api.put<OrgPainPointSubmissionSettings>(`${orgBase(organizationId)}/pain-point-settings`, { submission_policy: policy });
  },
};

/** Org-scoped `PainPointTypeDefinition` CRUD (the shared base
 * tier) — `id` parameters below are an `organization_id`. */
export const orgPainPointTypeApi = {
  list(organizationId: string) {
    return api.get<PainPointTypeDefinition[]>(`${orgBase(organizationId)}/pain-point-types`);
  },
  create(organizationId: string, name: string, definition?: string) {
    return api.post<PainPointTypeDefinition>(`${orgBase(organizationId)}/pain-point-types`, {
      name, definition: definition ?? null,
    });
  },
  move(organizationId: string, painPointTypeId: string, direction: "up" | "down") {
    return api.post<PainPointTypeDefinition>(
      `${orgBase(organizationId)}/pain-point-types/${painPointTypeId}/move`, { direction }
    );
  },
  update(organizationId: string, painPointTypeId: string, values: { name?: string; is_active?: boolean; definition?: string }) {
    return api.patch<PainPointTypeDefinition>(`${orgBase(organizationId)}/pain-point-types/${painPointTypeId}`, values);
  },
  delete(organizationId: string, painPointTypeId: string) {
    return api.delete<void>(`${orgBase(organizationId)}/pain-point-types/${painPointTypeId}`);
  },
};

/** Every project-scoped Pain Point endpoint — both tiers of the type
 * vocabulary and the Pain Point artefact itself —
 * `id` parameters below are a `project_id`. */
export const projectPainPointApi = {
  // --- Pain Point type vocabulary, project tier ---------------------------
  listTypes(projectId: string) {
    return api.get<EffectivePainPointType[]>(`${projectBase(projectId)}/pain-point-types`);
  },
  createLocalType(projectId: string, name: string, displayOrder?: number, definition?: string) {
    return api.post<ProjectPainPointType>(`${projectBase(projectId)}/pain-point-types`, {
      name, display_order: displayOrder ?? null, definition: definition ?? null,
    });
  },
  overrideType(
    projectId: string, typeRefId: string,
    values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null; definition?: string | null },
  ) {
    return api.put<ProjectPainPointType>(`${projectBase(projectId)}/pain-point-types/${typeRefId}`, values);
  },
  deleteType(projectId: string, typeRefId: string) {
    return api.delete<void>(`${projectBase(projectId)}/pain-point-types/${typeRefId}`);
  },
  listHiddenTypes(projectId: string) {
    return api.get<HiddenDefinition[]>(`${projectBase(projectId)}/pain-point-types/hidden`);
  },
  restoreTypes(projectId: string, orgTypeIds?: string[]) {
    return api.post<unknown>(`${projectBase(projectId)}/pain-point-types/restore`, { org_type_ids: orgTypeIds ?? null });
  },

  // --- Submission policy ------------------------------------------------------
  getSubmissionSettings(projectId: string) {
    return api.get<PainPointSubmissionSettings>(`${projectBase(projectId)}/pain-point-settings`);
  },
  /** Sets the project's own policy; `null` removes it so the project inherits. */
  setSubmissionPolicy(projectId: string, policy: PainPointSubmissionPolicy | null) {
    return api.put<PainPointSubmissionSettings>(`${projectBase(projectId)}/pain-point-settings`, { submission_policy: policy });
  },

  // --- CRUD -----------------------------------------------------------------
  list(projectId: string, filters: PainPointListFilters = {}) {
    const query = listQuery(filters);
    return api.get<PainPoint[]>(`${projectBase(projectId)}/pain-points${query}`);
  },
  create(projectId: string, values: PainPointFieldValues) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points`, values);
  },
  get(projectId: string, painPointId: string) {
    return api.get<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}`);
  },
  update(projectId: string, painPointId: string, values: PainPointFieldValues & { owner: PrincipalRef | null }) {
    return api.put<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}`, values);
  },
  // --- Per-persona scoring ---------------------------------------
  listScores(projectId: string, params: { model_key?: string; rollup?: PainPointRollup; include_archived?: boolean } = {}) {
    return api.get<PainPointScoringList>(`${projectBase(projectId)}/pain-point-scores${scoringQuery(params)}`);
  },
  /** Whether the caller may score, and the personas on offer, before a Pain Point exists. */
  getScoringTargets(projectId: string) {
    return api.get<PainPointScoringTargets>(`${projectBase(projectId)}/pain-point-scoring-targets`);
  },
  getScores(projectId: string, painPointId: string, params: { model_key?: string; rollup?: PainPointRollup } = {}) {
    return api.get<PainPointScores>(`${projectBase(projectId)}/pain-points/${painPointId}/scores${scoringQuery(params)}`);
  },
  /** Replaces the whole score set; the response is the roll-up under `params`. */
  setScores(
    projectId: string, painPointId: string, scores: PainPointScoreInput[],
    params: { model_key?: string; rollup?: PainPointRollup } = {},
  ) {
    return api.put<PainPointScores>(
      `${projectBase(projectId)}/pain-points/${painPointId}/scores${scoringQuery(params)}`, { scores },
    );
  },
  archive(projectId: string, painPointId: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/archive`);
  },
  unarchive(projectId: string, painPointId: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/unarchive`);
  },

  // --- Lifecycle (branching) -------------------------------------------------
  triage(projectId: string, painPointId: string, comment?: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/triage`, { comment: comment || null });
  },
  reject(projectId: string, painPointId: string, comment: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/reject`, { comment });
  },
  markDuplicate(projectId: string, painPointId: string, comment: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/mark-duplicate`, { comment });
  },
  accept(projectId: string, painPointId: string, comment?: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/accept`, { comment: comment || null });
  },
  address(projectId: string, painPointId: string, comment?: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/address`, { comment: comment || null });
  },
  close(projectId: string, painPointId: string, comment?: string) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}/close`, { comment: comment || null });
  },

  // --- Comments ---------------------------------------------------------
  listComments(projectId: string, painPointId: string) {
    return api.get<PainPointComment[]>(`${projectBase(projectId)}/pain-points/${painPointId}/comments`);
  },
  addComment(projectId: string, painPointId: string, body: string) {
    return api.post<PainPointComment>(`${projectBase(projectId)}/pain-points/${painPointId}/comments`, { body });
  },
  editComment(projectId: string, painPointId: string, commentId: string, body: string) {
    return api.patch<PainPointComment>(`${projectBase(projectId)}/pain-points/${painPointId}/comments/${commentId}`, { body });
  },
  uploadCommentAttachment(projectId: string, painPointId: string, commentId: string, file: File) {
    return api.postFile<FileAsset>(`${projectBase(projectId)}/pain-points/${painPointId}/comments/${commentId}/files`, file);
  },
  removeCommentAttachment(projectId: string, painPointId: string, commentId: string, fileId: string) {
    return api.delete<void>(`${projectBase(projectId)}/pain-points/${painPointId}/comments/${commentId}/files/${fileId}`);
  },

  // --- Direct file attachments ("evidence") ----------------------------------
  listFiles(projectId: string, painPointId: string) {
    return api.get<FileAsset[]>(`${projectBase(projectId)}/pain-points/${painPointId}/files`);
  },
  uploadFile(projectId: string, painPointId: string, file: File) {
    return api.postFile<FileAsset>(`${projectBase(projectId)}/pain-points/${painPointId}/files`, file);
  },
  unlinkFile(projectId: string, painPointId: string, fileId: string) {
    return api.delete<void>(`${projectBase(projectId)}/pain-points/${painPointId}/files/${fileId}`);
  },

  // --- Relationships -------------------------------------------
  listRelationships(projectId: string, painPointId: string) {
    return api.get<ContextStrategyLink[]>(`${projectBase(projectId)}/pain-points/${painPointId}/relationships`);
  },
  createRelationship(projectId: string, painPointId: string, kind: PainPointLinkKind, targetId: string) {
    return api.post<ContextStrategyLink>(`${projectBase(projectId)}/pain-points/${painPointId}/relationships`, {
      kind, target_id: targetId,
    });
  },
};

// --- Guiding Principle -------------------------------------------
//
// A `buildStrategyApi`-shaped factory: every endpoint has an identical organisation- and project-scoped twin.
// `update()` takes `values: GuidingPrincipleFieldValues & { owner: PrincipalRef | null }` because `owner` is not in
// `GuidingPrincipleFieldValues` (`types.ts`) yet the backend's `GuidingPrincipleUpdate` requires it on every `PUT` and
// an omitted `owner` would clear the existing one. Every call site passes the current `owner` through, as
// `projectPainPointApi.update` does.

export interface GuidingPrincipleListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
}

function buildGuidingPrincipleApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: GuidingPrincipleListFilters = {}) {
      const query = listQuery(filters);
      return api.get<GuidingPrinciple[]>(`${base(id)}/guiding-principles${query}`);
    },
    create(id: string, values: Omit<GuidingPrincipleFieldValues, "change_note"> & { owner?: PrincipalRef | null }) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles`, values);
    },
    get(id: string, guidingPrincipleId: string) {
      return api.get<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}`);
    },
    update(id: string, guidingPrincipleId: string, values: GuidingPrincipleFieldValues & { owner: PrincipalRef | null }) {
      return api.put<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}`, values);
    },
    listVersions(id: string, guidingPrincipleId: string) {
      return api.get<GuidingPrincipleVersion[]>(`${base(id)}/guiding-principles/${guidingPrincipleId}/versions`);
    },
    archive(id: string, guidingPrincipleId: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/archive`);
    },
    unarchive(id: string, guidingPrincipleId: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/unarchive`);
    },

    // --- Lifecycle transitions (no `submit-for-review` — Guiding Principle's
    // own shorter lifecycle has no `under_review` step) ------------------------
    propose(id: string, guidingPrincipleId: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/propose`);
    },
    sendBack(id: string, guidingPrincipleId: string, comment: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/send-back`, { comment });
    },
    approve(id: string, guidingPrincipleId: string, comment?: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/approve`, { comment: comment || null });
    },
    activate(id: string, guidingPrincipleId: string, comment?: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/activate`, { comment: comment || null });
    },
    supersede(id: string, guidingPrincipleId: string, comment?: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/supersede`, { comment: comment || null });
    },
    retire(id: string, guidingPrincipleId: string, comment?: string) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}/retire`, { comment: comment || null });
    },

    // --- Comments ---------------------------------------------------------
    listComments(id: string, guidingPrincipleId: string) {
      return api.get<GuidingPrincipleComment[]>(`${base(id)}/guiding-principles/${guidingPrincipleId}/comments`);
    },
    addComment(id: string, guidingPrincipleId: string, body: string) {
      return api.post<GuidingPrincipleComment>(`${base(id)}/guiding-principles/${guidingPrincipleId}/comments`, { body });
    },
    editComment(id: string, guidingPrincipleId: string, commentId: string, body: string) {
      return api.patch<GuidingPrincipleComment>(`${base(id)}/guiding-principles/${guidingPrincipleId}/comments/${commentId}`, { body });
    },
    uploadCommentAttachment(id: string, guidingPrincipleId: string, commentId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/guiding-principles/${guidingPrincipleId}/comments/${commentId}/files`, file);
    },
    removeCommentAttachment(id: string, guidingPrincipleId: string, commentId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/guiding-principles/${guidingPrincipleId}/comments/${commentId}/files/${fileId}`);
    },

    // --- Direct file attachments -------------------------------------------
    listFiles(id: string, guidingPrincipleId: string) {
      return api.get<FileAsset[]>(`${base(id)}/guiding-principles/${guidingPrincipleId}/files`);
    },
    uploadFile(id: string, guidingPrincipleId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/guiding-principles/${guidingPrincipleId}/files`, file);
    },
    unlinkFile(id: string, guidingPrincipleId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/guiding-principles/${guidingPrincipleId}/files/${fileId}`);
    },

    // --- Relationships -------------------------------------------
    listRelationships(id: string, guidingPrincipleId: string) {
      return api.get<ContextStrategyLink[]>(`${base(id)}/guiding-principles/${guidingPrincipleId}/relationships`);
    },
    createRelationship(id: string, guidingPrincipleId: string, kind: GuidingPrincipleLinkKind, targetId: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/guiding-principles/${guidingPrincipleId}/relationships`, {
        kind, target_id: targetId,
      });
    },
    createSupersessionLink(id: string, guidingPrincipleId: string, oldGuidingPrincipleId: string, comment?: string) {
      return api.post<ContextStrategyLink>(`${base(id)}/guiding-principles/${guidingPrincipleId}/supersessions`, {
        old_guiding_principle_id: oldGuidingPrincipleId, comment: comment || null,
      });
    },
  };
}

/** Every Guiding Principle endpoint, project-scoped — `id` parameters below
 * are a `project_id`. */
export const projectGuidingPrincipleApi = buildGuidingPrincipleApi(projectBase);
/** Every Guiding Principle endpoint, org-scoped — `id` parameters below are
 * an `organization_id`. */
export const orgGuidingPrincipleApi = buildGuidingPrincipleApi(orgBase);

// --- Open Question ------------------------------------------------
//
// No `buildOpenQuestionApi` factory: Open Question has no organisation scope, so a single flat object is used, as for
// Pain Point. `id` parameters below are a `project_id`.

export interface OpenQuestionListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
}

/** Every Open Question endpoint (CRUD/lifecycle/comments/files and
 * relationships) — `id` parameters below are a `project_id`. */
export const projectOpenQuestionApi = {
  // --- CRUD -----------------------------------------------------------------
  list(projectId: string, filters: OpenQuestionListFilters = {}) {
    const query = listQuery(filters);
    return api.get<OpenQuestion[]>(`${projectBase(projectId)}/open-questions${query}`);
  },
  create(projectId: string, values: OpenQuestionFieldValues) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions`, values);
  },
  get(projectId: string, openQuestionId: string) {
    return api.get<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}`);
  },
  update(projectId: string, openQuestionId: string, values: OpenQuestionFieldValues & { owner: PrincipalRef | null }) {
    return api.put<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}`, values);
  },
  archive(projectId: string, openQuestionId: string) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}/archive`);
  },
  unarchive(projectId: string, openQuestionId: string) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}/unarchive`);
  },

  // --- Lifecycle (branching, two branch points) -------------------------------
  investigate(projectId: string, openQuestionId: string, comment?: string) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}/investigate`, { comment: comment || null });
  },
  markReadyForDecision(projectId: string, openQuestionId: string, comment?: string) {
    return api.post<OpenQuestion>(
      `${projectBase(projectId)}/open-questions/${openQuestionId}/mark-ready-for-decision`, { comment: comment || null }
    );
  },
  withdraw(projectId: string, openQuestionId: string, comment: string) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}/withdraw`, { comment });
  },
  resolve(projectId: string, openQuestionId: string, comment?: string) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}/resolve`, { comment: comment || null });
  },

  // --- Comments ---------------------------------------------------------
  listComments(projectId: string, openQuestionId: string) {
    return api.get<OpenQuestionComment[]>(`${projectBase(projectId)}/open-questions/${openQuestionId}/comments`);
  },
  addComment(projectId: string, openQuestionId: string, body: string) {
    return api.post<OpenQuestionComment>(`${projectBase(projectId)}/open-questions/${openQuestionId}/comments`, { body });
  },
  editComment(projectId: string, openQuestionId: string, commentId: string, body: string) {
    return api.patch<OpenQuestionComment>(`${projectBase(projectId)}/open-questions/${openQuestionId}/comments/${commentId}`, { body });
  },
  uploadCommentAttachment(projectId: string, openQuestionId: string, commentId: string, file: File) {
    return api.postFile<FileAsset>(`${projectBase(projectId)}/open-questions/${openQuestionId}/comments/${commentId}/files`, file);
  },
  removeCommentAttachment(projectId: string, openQuestionId: string, commentId: string, fileId: string) {
    return api.delete<void>(`${projectBase(projectId)}/open-questions/${openQuestionId}/comments/${commentId}/files/${fileId}`);
  },

  // --- Direct file attachments ("evidence") ----------------------------------
  listFiles(projectId: string, openQuestionId: string) {
    return api.get<FileAsset[]>(`${projectBase(projectId)}/open-questions/${openQuestionId}/files`);
  },
  uploadFile(projectId: string, openQuestionId: string, file: File) {
    return api.postFile<FileAsset>(`${projectBase(projectId)}/open-questions/${openQuestionId}/files`, file);
  },
  unlinkFile(projectId: string, openQuestionId: string, fileId: string) {
    return api.delete<void>(`${projectBase(projectId)}/open-questions/${openQuestionId}/files/${fileId}`);
  },

  // --- Relationships -------------------------------------------
  listRelationships(projectId: string, openQuestionId: string) {
    return api.get<ContextStrategyLink[]>(`${projectBase(projectId)}/open-questions/${openQuestionId}/relationships`);
  },
  createRelationship(projectId: string, openQuestionId: string, kind: OpenQuestionLinkKind, targetId: string) {
    return api.post<ContextStrategyLink>(`${projectBase(projectId)}/open-questions/${openQuestionId}/relationships`, {
      kind, target_id: targetId,
    });
  },
};
