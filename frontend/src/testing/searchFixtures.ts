/**
 * Module: testing/searchFixtures
 *
 * Fixtures for the global-search stories: result builders and a fake `SearchApi` whose calls are
 * Storybook spies, so a story can assert what the UI asked for and control when a response lands.
 */
import { fn } from "storybook/test";

import type { SearchApi, SearchField, SearchHit, SearchProjectOption, SearchRequest, SearchResponse } from "../api/search";

/** A requirement hit by default; override any field. A record opens itself unless `open_type`/`open_id` say otherwise. */
export function buildSearchHit(overrides: Partial<SearchHit> = {}): SearchHit {
  const type = overrides.type ?? "requirement";
  const id = overrides.id ?? "r1";
  return {
    type,
    type_label: "Requirement",
    id,
    code: "REQ-001",
    title: "Voltage limit",
    status: "draft",
    status_label: "Draft",
    is_archived: false,
    updated_at: "2026-10-01T09:00:00Z",
    project_id: "p1",
    project_name: "Alpha",
    project_code: "ALPHA",
    organization_id: "o1",
    organization_code: "ACME",
    open_type: type,
    open_id: id,
    open_project_id: "p1",
    snippet: null,
    ...overrides,
  };
}

/** A response with the given hits; type counts are derived from them. */
export function buildSearchResponse(hits: SearchHit[], overrides: Partial<SearchResponse> = {}): SearchResponse {
  const counts = new Map<string, { label: string; count: number }>();
  for (const hit of hits) {
    const found = counts.get(hit.type) ?? { label: hit.type_label, count: 0 };
    found.count += 1;
    counts.set(hit.type, found);
  }
  return {
    hits,
    total: hits.length,
    total_capped: false,
    type_counts: [...counts].map(([type, v]) => ({ type, label: v.label, count: v.count, capped: false })),
    fields_used: ["id", "title", "tags"],
    not_searched: [],
    statuses: [{ key: "draft", label: "Draft" }],
    organizations: [{ id: "o1", name: "Acme", code: "ACME" }],
    projects_truncated: false,
    ...overrides,
  };
}

/** The fields a typical viewer is offered. */
export const SEARCH_FIELDS: SearchField[] = [
  { key: "id", label: "ID", types: [] },
  { key: "title", label: "Title", types: [] },
  { key: "tags", label: "Tags", types: [] },
  { key: "description", label: "Description", types: [] },
  { key: "reasoning", label: "Reasoning", types: ["Requirement"] },
  { key: "mitigation", label: "Mitigation", types: ["Risk"] },
  { key: "rationale", label: "Rationale", types: ["Decision", "Strategy"] },
];

export const SEARCH_PROJECTS: SearchProjectOption[] = [
  { id: "p1", name: "Alpha", parent_name: null },
  { id: "p2", name: "Beta", parent_name: "Alpha" },
];

/**
 * A fake `SearchApi`.
 *
 * @param respond Maps a request to its response; may return a promise the story resolves later.
 */
export function fakeSearchApi(
  respond: (request: SearchRequest) => SearchResponse | Promise<SearchResponse>,
  fields: SearchField[] = SEARCH_FIELDS,
): SearchApi & { search: ReturnType<typeof fn> } {
  return {
    search: fn(async (request: SearchRequest) => respond(request)),
    fields: fn(async () => fields),
    projects: fn(async () => SEARCH_PROJECTS),
  } as unknown as SearchApi & { search: ReturnType<typeof fn> };
}
