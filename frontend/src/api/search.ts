/**
 * Module: api/search
 *
 * The global search API: the request/response shapes of `POST /api/v1/search`, the field list
 * the field pickers offer (`GET /api/v1/search/fields`), and the pure helpers both the header box
 * and the search page share (turning a request into URL state and back, the code a result shows).
 *
 * The query text is sent in a POST body so it never appears in an access log. It is kept in the
 * page URL (`/search?q=…`) for sharing and Back, which the server never sees as an API call.
 */
import { formatRecordCode } from "../utils/recordCode";
import { api } from "./client";

/** A search request (`SearchRequestIn` on the backend). */
export interface SearchRequest {
  q: string;
  scope: string;
  project_id?: string | null;
  organization_ids?: string[];
  project_ids?: string[];
  types?: string[];
  statuses?: string[];
  fields?: string[];
  match?: "contains" | "phrase";
  include_archived?: boolean;
  updated_from?: string | null;
  updated_to?: string | null;
  sort?: "relevance" | "updated";
  /** Whether a search of one project also covers its organisation's records; omitted uses the viewer's preference. */
  include_organization_records?: boolean;
  limit?: number;
  offset?: number;
  counts?: boolean;
}

/** The first matching field of a hit: windowed text plus `[start, end)` ranges to highlight. */
export interface SearchSnippet {
  field_key: string;
  field_label: string;
  text: string;
  ranges: [number, number][];
}

export interface SearchHit {
  type: string;
  type_label: string;
  id: string;
  code: string;
  title: string;
  status: string | null;
  status_label: string | null;
  is_archived: boolean;
  updated_at: string | null;
  project_id: string | null;
  project_name: string | null;
  project_code: string | null;
  organization_id: string | null;
  organization_code: string | null;
  open_type: string;
  open_id: string;
  open_project_id: string | null;
  snippet: SearchSnippet | null;
}

export interface SearchTypeCount {
  type: string;
  label: string;
  count: number;
  capped: boolean;
}

export interface SearchNamed {
  key: string;
  label: string;
}

export interface SearchOrganization {
  id: string;
  name: string;
  code: string;
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number | null;
  total_capped: boolean;
  type_counts: SearchTypeCount[];
  fields_used: string[];
  not_searched: SearchNamed[];
  statuses: SearchNamed[];
  organizations: SearchOrganization[];
  projects_truncated: boolean;
}

/** A field the search can match (`GET /search/fields`). */
export interface SearchField {
  key: string;
  label: string;
  types: string[];
  /** False for a field that can be chosen for one search but never saved as a default (comments). */
  default_allowed?: boolean;
}

/** Most results the server will page to; a deeper page asks the person to refine. */
export const SEARCH_MAX_DEPTH = 500;
/** Shortest query the server accepts. */
export const SEARCH_MIN_QUERY = 2;
/** The field key for comments: heavier to search, so chosen per search and never a default. */
export const COMMENTS_SEARCH_FIELD = "comments";
/** Fields every search matches (the code and the title); the field pickers show them checked and locked. */
export const LOCKED_SEARCH_FIELDS = ["id", "title"];
/** The `ui_preferences` key holding whether a project search also covers organisation records (default on). */
export const SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE = "search_include_org_records";
/** The `ui_preferences` key holding the viewer's default search fields. */
export const SEARCH_DEFAULT_FIELDS_PREFERENCE = "search_default_fields";
/** The built-in default (ID, Title, Tags) while the viewer has not chosen their own. */
export const SEARCH_BUILT_IN_FIELDS = ["id", "title", "tags"];

/** A project the search page's Project filter can pick, with its parent so nesting shows. */
export interface SearchProjectOption {
  id: string;
  name: string;
  parent_name: string | null;
}

/** Injectable calls so stories and tests stay off the network. */
export interface SearchApi {
  search: (request: SearchRequest, signal?: AbortSignal) => Promise<SearchResponse>;
  fields: () => Promise<SearchField[]>;
  projects: () => Promise<SearchProjectOption[]>;
}

export const searchApi: SearchApi = {
  search: (request, signal) => api.post<SearchResponse>("/api/v1/search", request, undefined, signal),
  fields: () => api.get<SearchField[]>("/api/v1/search/fields"),
  projects: async () => {
    const projects = await api.get<{ id: string; name: string; parent_project_name?: string | null }[]>("/api/v1/projects");
    return projects.map((p) => ({ id: p.id, name: p.name, parent_name: p.parent_project_name ?? null }));
  },
};

/** What the search page's controls and URL hold. */
export interface SearchPageState {
  q: string;
  scope: string;
  /** The project `scope === "project"` means. */
  projectId: string | null;
  organizationId: string | null;
  projectIds: string[];
  types: string[];
  statuses: string[];
  /** The fields to match, or `null` to use the viewer's default. */
  fields: string[] | null;
  includeArchived: boolean;
  match: "contains" | "phrase";
  sort: "relevance" | "updated";
  /** Whether a project search covers organisation records, or `null` to use the viewer's preference. */
  orgRecords: boolean | null;
  /** `YYYY-MM-DD` local dates, or "" for no bound. */
  updatedFrom: string;
  updatedTo: string;
}

const list = (value: string | null): string[] => (value ? value.split(",").filter(Boolean) : []);

/** Reads the page state from its URL (anything unrecognised falls back to the default). */
export function parseSearchState(params: URLSearchParams): SearchPageState {
  const fields = params.get("fields");
  return {
    q: params.get("q") ?? "",
    scope: params.get("scope") ?? "all",
    projectId: params.get("project"),
    organizationId: params.get("org"),
    projectIds: list(params.get("projects")),
    types: list(params.get("types")),
    statuses: list(params.get("statuses")),
    fields: fields === null ? null : list(fields),
    includeArchived: params.get("archived") === "1",
    orgRecords: params.has("orgrecords") ? params.get("orgrecords") === "1" : null,
    match: params.get("match") === "phrase" ? "phrase" : "contains",
    sort: params.get("sort") === "updated" ? "updated" : "relevance",
    updatedFrom: params.get("from") ?? "",
    updatedTo: params.get("to") ?? "",
  };
}

/** Writes the page state to URL parameters; defaults are left out so a URL stays short and shareable. */
export function searchStateToParams(state: SearchPageState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.scope !== "all") params.set("scope", state.scope);
  if (state.scope === "project" && state.projectId) params.set("project", state.projectId);
  if (state.organizationId) params.set("org", state.organizationId);
  if (state.projectIds.length) params.set("projects", state.projectIds.join(","));
  if (state.types.length) params.set("types", state.types.join(","));
  if (state.statuses.length) params.set("statuses", state.statuses.join(","));
  if (state.fields !== null) params.set("fields", state.fields.join(","));
  if (state.includeArchived) params.set("archived", "1");
  if (state.orgRecords !== null) params.set("orgrecords", state.orgRecords ? "1" : "0");
  if (state.match !== "contains") params.set("match", state.match);
  if (state.sort !== "relevance") params.set("sort", state.sort);
  if (state.updatedFrom) params.set("from", state.updatedFrom);
  if (state.updatedTo) params.set("to", state.updatedTo);
  return params;
}

/** The instant a local calendar day (`YYYY-MM-DD`) starts, as an ISO string; the browser owns local time. */
export function localDayStartIso(day: string): string | null {
  const [y, m, d] = day.split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d, 0, 0, 0, 0).toISOString() : null;
}

/** The last instant of a local calendar day, as an ISO string. */
export function localDayEndIso(day: string): string | null {
  const [y, m, d] = day.split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d, 23, 59, 59, 999).toISOString() : null;
}

/** The request for a page state (`limit`/`offset` are the caller's). */
export function searchRequestFor(state: SearchPageState, limit: number, offset: number): SearchRequest {
  return {
    q: state.q.trim(),
    scope: state.scope,
    project_id: state.scope === "project" ? state.projectId : undefined,
    organization_ids: state.organizationId ? [state.organizationId] : undefined,
    project_ids: state.projectIds.length ? state.projectIds : undefined,
    types: state.types.length ? state.types : undefined,
    statuses: state.statuses.length ? state.statuses : undefined,
    fields: state.fields ?? undefined,
    match: state.match,
    include_archived: state.includeArchived,
    include_organization_records: state.scope === "project" && state.orgRecords !== null ? state.orgRecords : undefined,
    updated_from: state.updatedFrom ? localDayStartIso(state.updatedFrom) : undefined,
    updated_to: state.updatedTo ? localDayEndIso(state.updatedTo) : undefined,
    sort: state.sort,
    limit,
    offset,
    counts: true,
  };
}

/** Whether a failure is the request being cancelled (a newer search superseded it). */
export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Words of a query as the server splits them (lower-case), for highlighting titles and codes. */
export function queryTerms(q: string, match: "contains" | "phrase" = "contains"): string[] {
  const text = q.trim().replace(/\s+/g, " ").toLowerCase();
  if (!text) return [];
  return match === "phrase" ? [text] : text.split(" ");
}

const CODE_SHAPE = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$/;

/**
 * The code a result shows. A global search spans projects, so a `PREFIX-nnn` code is qualified by its owning project (or, for an organisation-owned record,
 * its organisation); a code of another shape (a compliance clause reference `A.5.15`) is shown as is.
 *
 * @param hit The result.
 */
export function hitCode(hit: Pick<SearchHit, "code" | "project_code" | "organization_code" | "type">): string {
  if (hit.type === "project" || !CODE_SHAPE.test(hit.code)) return hit.code;
  const owner = hit.project_code ?? hit.organization_code;
  return formatRecordCode(hit.code, { currentProjectCode: null, enforced: false, preferred: true }, owner);
}

/** Splits `text` into plain and highlighted parts by `[start, end)` ranges (assumed sorted, non-overlapping not required). */
export function highlightParts(text: string, ranges: [number, number][]): { text: string; mark: boolean }[] {
  const merged: [number, number][] = [];
  for (const [start, end] of [...ranges].sort((a, b) => a[0] - b[0])) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  const parts: { text: string; mark: boolean }[] = [];
  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor) parts.push({ text: text.slice(cursor, start), mark: false });
    parts.push({ text: text.slice(start, end), mark: true });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), mark: false });
  return parts;
}

/** The ranges where any of `terms` occurs in `text` (case-insensitive), for highlighting a title or code. */
export function matchRanges(text: string, terms: string[]): [number, number][] {
  const lowered = text.toLowerCase();
  const ranges: [number, number][] = [];
  for (const term of terms) {
    if (!term) continue;
    let from = 0;
    for (;;) {
      const at = lowered.indexOf(term, from);
      if (at < 0) break;
      ranges.push([at, at + term.length]);
      from = at + term.length;
    }
  }
  return ranges;
}
