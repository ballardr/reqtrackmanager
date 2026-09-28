/**
 * Module: modules/context_strategy/api
 *
 * Thin wrapper functions over `api` (frontend/src/api/client.ts) for every
 * Strategy endpoint `backend/app/modules/context_strategy/{router,
 * project_router}.py` exposes (docs/plans/module-01-context-and-strategy-
 * plan.md Phase 7.1) — mirrors `modules/decisions/api.ts`'s own dedicated-
 * per-module-file precedent.
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
import type { ContextStrategyLink, Strategy, StrategyComment, StrategyFieldValues, StrategyLinkKind, StrategyVersion } from "./types";

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
