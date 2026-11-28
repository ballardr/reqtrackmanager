/**
 * Module: modules/traceability/exceptionApi
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for the traceability exception endpoints of
 * `backend/app/modules/traceability/exception_router.py` that the screens call: the list, one exception, and its comments
 * and evidence in the shape the shared `RecordDiscussion` expects (`id` is the project id).
 */
import { api } from "../../api/client";
import { appendScopeParam, type ScopeListFilters } from "../../api/projectScope";
import { appendTagParams, type TagListFilters } from "../../api/tags";
import type { FileAsset } from "../../api/types";
import type { ExceptionComment, ExceptionStatus, TraceabilityException } from "./types";

const base = (projectId: string) => `/api/v1/projects/${projectId}/modules/traceability/exceptions`;
const one = (projectId: string, exceptionId: string) => `${base(projectId)}/${exceptionId}`;

/** Optional filters of the exception list. */
export interface ExceptionListFilters extends TagListFilters, ScopeListFilters {
  status?: ExceptionStatus;
  include_archived?: boolean;
  open_only?: boolean;
}

export const exceptionApi = {
  list(projectId: string, filters: ExceptionListFilters = {}) {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.include_archived) params.set("include_archived", "true");
    if (filters.open_only) params.set("open_only", "true");
    appendTagParams(params, filters);
    appendScopeParam(params, filters);
    const query = params.toString();
    return api.get<TraceabilityException[]>(`${base(projectId)}${query ? `?${query}` : ""}`);
  },
  get: (projectId: string, exceptionId: string) => api.get<TraceabilityException>(one(projectId, exceptionId)),

  listComments: (projectId: string, exceptionId: string) => api.get<ExceptionComment[]>(`${one(projectId, exceptionId)}/comments`),
  addComment: (projectId: string, exceptionId: string, body: string) =>
    api.post<ExceptionComment>(`${one(projectId, exceptionId)}/comments`, { body }),
  editComment: (projectId: string, exceptionId: string, commentId: string, body: string) =>
    api.patch<ExceptionComment>(`${one(projectId, exceptionId)}/comments/${commentId}`, { body }),
  uploadCommentAttachment: (projectId: string, exceptionId: string, commentId: string, file: File) =>
    api.postFile<FileAsset>(`${one(projectId, exceptionId)}/comments/${commentId}/files`, file),
  removeCommentAttachment: (projectId: string, exceptionId: string, commentId: string, fileId: string) =>
    api.delete<void>(`${one(projectId, exceptionId)}/comments/${commentId}/files/${fileId}`),
  listFiles: (projectId: string, exceptionId: string) => api.get<FileAsset[]>(`${one(projectId, exceptionId)}/files`),
  uploadFile: (projectId: string, exceptionId: string, file: File) =>
    api.postFile<FileAsset>(`${one(projectId, exceptionId)}/files`, file),
  unlinkFile: (projectId: string, exceptionId: string, fileId: string) =>
    api.delete<void>(`${one(projectId, exceptionId)}/files/${fileId}`),
};
