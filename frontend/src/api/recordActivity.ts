/**
 * Module: api/recordActivity
 *
 * Types and the call for a record's activity timeline
 * (`GET /projects/{id}/artefacts/{type}/{id}/activity`), shown in the detail
 * page aside's Activity tab. The server authorises it like the record itself
 * and omits link events whose other end the viewer cannot see.
 *
 * The call is injectable (`RecordActivityApi`) so stories need no network.
 */
import { api } from "./client";
import type { ChangeEntry } from "./types";

export interface RecordActivityPage {
  entries: ChangeEntry[];
  has_more: boolean;
}

export interface RecordActivityApi {
  /** One page of a record's activity, newest first. */
  list(projectId: string, type: string, id: string, params?: { limit?: number; offset?: number }): Promise<RecordActivityPage>;
}

/** The live implementation of {@link RecordActivityApi}. */
export const recordActivityApi: RecordActivityApi = {
  list: (projectId, type, id, params = {}) => {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query}` : "";
    return api.get<RecordActivityPage>(`/api/v1/projects/${projectId}/artefacts/${type}/${id}/activity${suffix}`);
  },
};
