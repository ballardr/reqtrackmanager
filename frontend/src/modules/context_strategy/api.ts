/**
 * Module: modules/context_strategy/api
 *
 * Thin wrapper functions over `api` (frontend/src/api/client.ts) for every
 * Strategy (Phase 7.1), Future State (Phase 7.2), Pain Point (Phase 7.3),
 * Guiding Principle (Phase 7.4), and Open Question (Phase 7.5) endpoint
 * `backend/app/modules/context_strategy/{router,project_router}.py` exposes
 * — mirrors `modules/decisions/api.ts`'s own dedicated-per-module-file
 * precedent. See `buildFutureStateApi`'s own docstring below for why Future
 * State gets a sibling factory rather than reusing `buildStrategyApi`,
 * `buildGuidingPrincipleApi`'s own docstring for why Guiding Principle goes
 * back to the factory shape after Pain Point's own project-scoped-only
 * exception, and `projectOpenQuestionApi`'s own docstring for why Open
 * Question stays with Pain Point's flat-object shape rather than reverting
 * to a factory a third time.
 *
 * **Design choice, Decided by: Agent:** unlike `modules/decisions/api.ts`
 * (which only needed a project/org split for two small definition-table
 * resources — Decision Types/Templates — while the Decision artefact
 * itself is project-scoped only), Strategy's own backend gives every single
 * endpoint an *identical* org-scoped and project-scoped twin (Phase 0 Q2's
 * scope discriminator — `router.py`/`project_router.py` mirror each other
 * exactly, same schemas, same suffixes, same behaviour, differing only in
 * which id the URL is built from). Rather than hand-writing ~25 functions
 * twice, `buildStrategyApi` is a small factory parameterised by the base-
 * URL builder; `projectStrategyApi`/`orgStrategyApi` are its two
 * instantiations. If a *future* Strategy endpoint's behaviour ever
 * genuinely diverges between scopes, that one function can be pulled out of
 * the factory and hand-written per scope at that point — nothing here
 * forces the two to stay identical forever, it just avoids duplicating them
 * while they are.
 */
import { api } from "../../api/client";
import type { FileAsset } from "../../api/types";
import type {
  ContextStrategyLink,
  EffectivePainPointType,
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
  PainPointTypeDefinition,
  ProjectPainPointType,
  Strategy,
  StrategyComment,
  StrategyFieldValues,
  StrategyLinkKind,
  StrategyVersion,
} from "./types";

export interface StrategyListFilters {
  include_archived?: boolean;
}

function buildStrategyApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: StrategyListFilters = {}) {
      const query = filters.include_archived ? "?include_archived=true" : "";
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

    // --- Relationships (Phase 6) -------------------------------------------
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

// --- Future State (Phase 7.2) ------------------------------------------------

export interface FutureStateListFilters {
  include_archived?: boolean;
}

/**
 * **A sibling factory, not a reuse of `buildStrategyApi` (Decided by:
 * Agent).** Future State's backend endpoint *shapes* are identical to
 * Strategy's (org/project twin routers, same CRUD/lifecycle/comments/files/
 * relationships surface — Phase 2's own "exact structural mirror" of
 * Phase 1), which is the same condition that justified `buildStrategyApi`
 * as one factory instantiated twice rather than ~25 hand-written functions
 * per scope. But Future State's own *field list* genuinely diverges from
 * Strategy's (no `priority`/`time_horizon`; adds `target_date`), so forcing
 * both artefact types through one generic-over-field-shape factory would
 * need real TypeScript generics threaded through every method's payload
 * type for a one-time saving of a ~130-line function — not worth the added
 * indirection for a function this size. `buildFutureStateApi` is a
 * structural copy of `buildStrategyApi`, parameterised the same way
 * (`base: (id: string) => string`), pointed at `/future-states` instead of
 * `/strategies`. If a *sixth* artefact type ever needs this identical shape
 * again, that would be the point to reconsider a shared generic factory.
 *
 * `target_date` needs no client-side "explicitly set" flag distinct from
 * "leave unchanged" the way the backend's `apply_future_state_new_version`
 * does internally — the `PUT` endpoint's own `FutureStateUpdate` schema is a
 * full-replace payload (every field always present), and the router always
 * passes `target_date_explicitly_set=True` for a `PUT` (see
 * `project_router.py`'s `update_project_future_state`), so `update()` below
 * just sends whatever the form holds: a date string to set it, `null` to
 * clear it. The "explicitly set" distinction only exists to let *creation*
 * (which has no such flag) and *update* share one internal `apply_*_new_
 * version` function — it never reaches the wire.
 */
function buildFutureStateApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: FutureStateListFilters = {}) {
      const query = filters.include_archived ? "?include_archived=true" : "";
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

    // --- Relationships (Phase 6) -------------------------------------------
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

// --- Pain Point (Phase 7.3) --------------------------------------------------
//
// **No `buildPainPointApi` factory, unlike Strategy/Future State (Decided by:
// Agent).** The factory shape exists specifically for an artefact with an
// *identical* org-scoped and project-scoped twin endpoint set (Phase 0 Q2's
// scope discriminator) — Pain Point has no organisation scope at all (source
// overview §6), so there is nothing to instantiate twice. `orgPainPointTypeApi`
// (the org-scoped `PainPointTypeDefinition` CRUD tier, Phase 0 Q3) and
// `projectPainPointApi` (everything else — the project-scoped type-override
// tier plus the Pain Point artefact itself) are two plain, hand-written
// objects instead, mirroring `modules/decisions/api.ts`'s own flat-function
// shape for a project-scoped-only artefact.

export interface PainPointListFilters {
  include_archived?: boolean;
}

/** Org-scoped `PainPointTypeDefinition` CRUD (Phase 0 Q3's shared base
 * tier) — `id` parameters below are an `organization_id`. */
export const orgPainPointTypeApi = {
  list(organizationId: string) {
    return api.get<PainPointTypeDefinition[]>(`${orgBase(organizationId)}/pain-point-types`);
  },
  create(organizationId: string, name: string) {
    return api.post<PainPointTypeDefinition>(`${orgBase(organizationId)}/pain-point-types`, { name });
  },
  move(organizationId: string, painPointTypeId: string, direction: "up" | "down") {
    return api.post<PainPointTypeDefinition>(
      `${orgBase(organizationId)}/pain-point-types/${painPointTypeId}/move`, { direction }
    );
  },
  update(organizationId: string, painPointTypeId: string, values: { name?: string; is_active?: boolean }) {
    return api.patch<PainPointTypeDefinition>(`${orgBase(organizationId)}/pain-point-types/${painPointTypeId}`, values);
  },
  delete(organizationId: string, painPointTypeId: string) {
    return api.delete<void>(`${orgBase(organizationId)}/pain-point-types/${painPointTypeId}`);
  },
};

/** Every project-scoped Pain Point endpoint — both tiers of the type
 * vocabulary (Phase 0 Q3) and the Pain Point artefact itself (Phase 3) —
 * `id` parameters below are a `project_id`. */
export const projectPainPointApi = {
  // --- Pain Point type vocabulary, project tier ---------------------------
  listTypes(projectId: string) {
    return api.get<EffectivePainPointType[]>(`${projectBase(projectId)}/pain-point-types`);
  },
  createLocalType(projectId: string, name: string, displayOrder?: number) {
    return api.post<ProjectPainPointType>(`${projectBase(projectId)}/pain-point-types`, {
      name, display_order: displayOrder ?? null,
    });
  },
  overrideType(
    projectId: string, typeRefId: string,
    values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
  ) {
    return api.put<ProjectPainPointType>(`${projectBase(projectId)}/pain-point-types/${typeRefId}`, values);
  },
  deleteType(projectId: string, projectPainPointTypeId: string) {
    return api.delete<void>(`${projectBase(projectId)}/pain-point-types/${projectPainPointTypeId}`);
  },

  // --- CRUD -----------------------------------------------------------------
  list(projectId: string, filters: PainPointListFilters = {}) {
    const query = filters.include_archived ? "?include_archived=true" : "";
    return api.get<PainPoint[]>(`${projectBase(projectId)}/pain-points${query}`);
  },
  create(projectId: string, values: PainPointFieldValues) {
    return api.post<PainPoint>(`${projectBase(projectId)}/pain-points`, values);
  },
  get(projectId: string, painPointId: string) {
    return api.get<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}`);
  },
  update(projectId: string, painPointId: string, values: PainPointFieldValues & { owner_id: string | null }) {
    return api.put<PainPoint>(`${projectBase(projectId)}/pain-points/${painPointId}`, values);
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

  // --- Relationships (Phase 6) -------------------------------------------
  listRelationships(projectId: string, painPointId: string) {
    return api.get<ContextStrategyLink[]>(`${projectBase(projectId)}/pain-points/${painPointId}/relationships`);
  },
  createRelationship(projectId: string, painPointId: string, kind: PainPointLinkKind, targetId: string) {
    return api.post<ContextStrategyLink>(`${projectBase(projectId)}/pain-points/${painPointId}/relationships`, {
      kind, target_id: targetId,
    });
  },
};

// --- Guiding Principle (Phase 7.4) -------------------------------------------
//
// Back to a `buildStrategyApi`-shaped factory (Decided by: Agent) — Guiding
// Principle's backend gives every endpoint an identical org-scoped/
// project-scoped twin, the same condition that justified Strategy's/Future
// State's own factory shape and does not apply to Pain Point (project-scoped
// only). `update()` below deliberately takes `values: GuidingPrincipleFieldValues
// & { owner_id: string | null }`, not just `GuidingPrincipleFieldValues`
// (unlike `buildStrategyApi.update`/`buildFutureStateApi.update`, whose own
// field-value types already include every field the backend's full-replace
// `PUT` expects) — `owner_id` is deliberately excluded from
// `GuidingPrincipleFieldValues` itself (`types.ts`'s own docstring), but the
// backend's `GuidingPrincipleUpdate` schema still requires it on every `PUT`
// (defaulting to `None` if omitted, which would silently clear an existing
// owner on every plain content edit) — every call site must pass the
// Guiding Principle's own current `owner_id` through explicitly, the same
// discipline `projectPainPointApi.update`'s identical `& { owner_id: string
// | null }` extension already establishes for Pain Point.

export interface GuidingPrincipleListFilters {
  include_archived?: boolean;
}

function buildGuidingPrincipleApi(base: (id: string) => string) {
  return {
    // --- CRUD ---------------------------------------------------------------
    list(id: string, filters: GuidingPrincipleListFilters = {}) {
      const query = filters.include_archived ? "?include_archived=true" : "";
      return api.get<GuidingPrinciple[]>(`${base(id)}/guiding-principles${query}`);
    },
    create(id: string, values: Omit<GuidingPrincipleFieldValues, "change_note"> & { owner_id?: string | null }) {
      return api.post<GuidingPrinciple>(`${base(id)}/guiding-principles`, values);
    },
    get(id: string, guidingPrincipleId: string) {
      return api.get<GuidingPrinciple>(`${base(id)}/guiding-principles/${guidingPrincipleId}`);
    },
    update(id: string, guidingPrincipleId: string, values: GuidingPrincipleFieldValues & { owner_id: string | null }) {
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

    // --- Relationships (Phase 6) -------------------------------------------
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

// --- Open Question (Phase 7.5) ------------------------------------------------
//
// No `buildOpenQuestionApi` factory (Decided by: Agent) — the same
// "nothing to instantiate twice" reasoning `projectPainPointApi`'s own
// docstring gives. Open Question has no organisation scope at all (source
// overview §9), so a single flat, hand-written object is used instead, the
// same shape Pain Point's own project-scoped-only exception already
// established. `id` parameters below are a `project_id`.

export interface OpenQuestionListFilters {
  include_archived?: boolean;
}

/** Every Open Question endpoint (Phase 5's CRUD/lifecycle/comments/files,
 * Phase 6's relationships) — `id` parameters below are a `project_id`. */
export const projectOpenQuestionApi = {
  // --- CRUD -----------------------------------------------------------------
  list(projectId: string, filters: OpenQuestionListFilters = {}) {
    const query = filters.include_archived ? "?include_archived=true" : "";
    return api.get<OpenQuestion[]>(`${projectBase(projectId)}/open-questions${query}`);
  },
  create(projectId: string, values: OpenQuestionFieldValues) {
    return api.post<OpenQuestion>(`${projectBase(projectId)}/open-questions`, values);
  },
  get(projectId: string, openQuestionId: string) {
    return api.get<OpenQuestion>(`${projectBase(projectId)}/open-questions/${openQuestionId}`);
  },
  update(projectId: string, openQuestionId: string, values: OpenQuestionFieldValues & { owner_id: string | null }) {
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

  // --- Relationships (Phase 6) -------------------------------------------
  listRelationships(projectId: string, openQuestionId: string) {
    return api.get<ContextStrategyLink[]>(`${projectBase(projectId)}/open-questions/${openQuestionId}/relationships`);
  },
  createRelationship(projectId: string, openQuestionId: string, kind: OpenQuestionLinkKind, targetId: string) {
    return api.post<ContextStrategyLink>(`${projectBase(projectId)}/open-questions/${openQuestionId}/relationships`, {
      kind, target_id: targetId,
    });
  },
};
