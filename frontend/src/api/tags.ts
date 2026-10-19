/**
 * Module: api/tags
 *
 * Types and calls for tags: the vocabulary of a project or organisation, the tags on one record
 * of any type (`/projects/{id}/artefacts/{type}/{id}/tags`), usage tables, bulk reclassify and
 * finding records by tag.
 *
 * Two injectable interfaces keep stories off the network: {@link RecordTagsApi} (one record's
 * tags, used by the record header and the create forms) and {@link TagAdminApi} (a vocabulary
 * and its maintenance, bound to a project or to the organisation by the factory that builds it
 * so the admin panel is one component for both).
 */
import { api } from "./client";

/** A tag as shown on a record. */
export interface TagChipData {
  id: string;
  name: string;
  colour: string | null;
}

/** A vocabulary entry; `editable` is false for a tag inherited from a parent project. */
export interface Tag extends TagChipData {
  usage_count: number;
  editable: boolean;
}

export type TagMode = "free" | "restricted";

export interface TagVocabulary {
  mode: TagMode;
  /** The mode comes from an ancestor project (or the default), not this project's own setting. */
  mode_inherited: boolean;
  /** The tags belong to an ancestor project, which manages them. */
  inherited: boolean;
  /** The project is nested under another, so it may follow that project's setting. */
  has_parent: boolean;
  /** This project's own setting; `null` follows the nearest ancestor. */
  own_mode: TagMode | null;
  tags: Tag[];
}

/** One record's tags and what its picker needs. */
export interface RecordTags {
  tags: TagChipData[];
  can_edit: boolean;
  restricted: boolean;
  suggestions: TagChipData[];
}

export interface TagUsageRow {
  tag_id: string;
  name: string;
  colour: string | null;
  count: number;
  last_used: string | null;
}

export interface TagTypeUsage {
  artefact_type: string;
  label: string;
  rows: TagUsageRow[];
}

export interface TagUsage {
  tables: TagTypeUsage[];
  /** Vocabulary tags no record carries. */
  unused: TagChipData[];
}

export interface ReclassifyRequest {
  /** Every record carrying this tag... */
  from_tag_id?: string;
  /** ...optionally only of these record types. */
  artefact_types?: string[];
  /** ...or exactly these records (project only). */
  records?: Array<{ artefact_type: string; artefact_id: string }>;
  add?: string[];
  remove?: string[];
  dry_run: boolean;
}

export interface ReclassifyResult {
  matched: number;
  added: number;
  removed: number;
  dry_run: boolean;
}

export interface TaggedRecord {
  artefact_type: string;
  type_label: string;
  id: string;
  label: string;
  status: string | null;
  is_archived: boolean;
  project_id: string | null;
}

export const TAG_NAME_MAX_LENGTH = 40;

/** Why a typed tag name is not acceptable (the server enforces the same rules), or `null` when it is. */
export function tagNameProblem(raw: string): "empty" | "too_long" | "invalid_characters" | null {
  const name = raw.trim().replace(/\s+/g, " ");
  if (name === "") return "empty";
  if (name.length > TAG_NAME_MAX_LENGTH) return "too_long";
  for (const ch of name) {
    if (ch === "," || ch === ";" || ch.charCodeAt(0) < 32) return "invalid_characters";
  }
  return null;
}

/** A tag name as stored: trimmed with inner whitespace collapsed. */
export function normaliseTagName(raw: string): string {
  return raw.trim().replace(/\s+/g, " ");
}

/** The tags of one record; injectable for stories. */
export interface RecordTagsApi {
  get(projectId: string, type: string, id: string): Promise<RecordTags>;
  /** Makes the record carry exactly these names. */
  set(projectId: string, type: string, id: string, names: string[]): Promise<RecordTags>;
  /** The project's vocabulary (a create form has no record yet). */
  vocabulary(projectId: string): Promise<TagVocabulary>;
}

/** A vocabulary and its maintenance, bound to one project or to the organisation. */
export interface TagAdminApi {
  vocabulary(): Promise<TagVocabulary>;
  create(name: string, colour?: string | null): Promise<Tag>;
  update(tagId: string, patch: { name?: string; colour?: string | null; clear_colour?: boolean }): Promise<Tag>;
  merge(tagId: string, intoTagId: string): Promise<{ records_moved: number }>;
  remove(tagId: string): Promise<{ records_untagged: number }>;
  /** `null` makes a project follow its nearest ancestor (an organisation must choose). */
  setMode(mode: TagMode | null): Promise<TagVocabulary>;
  usage(artefactType?: string): Promise<TagUsage>;
  reclassify(body: ReclassifyRequest): Promise<ReclassifyResult>;
}

function recordBase(projectId: string, type: string, id: string): string {
  return `/api/v1/projects/${projectId}/artefacts/${encodeURIComponent(type)}/${id}/tags`;
}

/** The live implementation of {@link RecordTagsApi}. */
export const recordTagsApi: RecordTagsApi = {
  get: (projectId, type, id) => api.get<RecordTags>(recordBase(projectId, type, id)),
  set: (projectId, type, id, names) => api.put<RecordTags>(recordBase(projectId, type, id), { tags: names }),
  vocabulary: (projectId) => api.get<TagVocabulary>(`/api/v1/projects/${projectId}/tags`),
};

function adminApi(base: string, modeUrl: string, supportsRecords: boolean): TagAdminApi {
  return {
    vocabulary: () => api.get<TagVocabulary>(base),
    create: (name, colour) => api.post<Tag>(base, { name, colour: colour ?? null }),
    update: (tagId, patch) => api.patch<Tag>(`${base}/${tagId}`, patch),
    merge: (tagId, intoTagId) => api.post<{ records_moved: number }>(`${base}/${tagId}/merge`, { into_tag_id: intoTagId }),
    remove: (tagId) => api.delete<{ records_untagged: number }>(`${base}/${tagId}`),
    setMode: (mode) => api.put<TagVocabulary>(modeUrl, { mode }),
    usage: (artefactType) =>
      api.get<TagUsage>(`${base}/usage${artefactType ? `?artefact_type=${encodeURIComponent(artefactType)}` : ""}`),
    reclassify: (body) => {
      if (!supportsRecords && body.records) throw new Error("Organisation tags are reclassified by tag.");
      return api.post<ReclassifyResult>(`${base}/reclassify`, body);
    },
  };
}

/** The admin calls for one project's own vocabulary. */
export function projectTagAdminApi(projectId: string): TagAdminApi {
  return adminApi(`/api/v1/projects/${projectId}/tags`, `/api/v1/projects/${projectId}/tag-settings`, true);
}

/** The admin calls for the organisation's own vocabulary (used by organisation-owned records). */
export function orgTagAdminApi(organizationId: string): TagAdminApi {
  return adminApi(`/api/v1/orgs/${organizationId}/tags`, `/api/v1/orgs/${organizationId}/tags/settings`, false);
}

/** Records of any type carrying some tags that the caller can open. */
export function findTaggedRecords(
  projectId: string, tags: string[], mode: "any" | "all" = "any", artefactType?: string,
): Promise<{ records: TaggedRecord[]; truncated: boolean }> {
  const query = new URLSearchParams();
  for (const tag of tags) query.append("tag", tag);
  query.set("tag_mode", mode);
  if (artefactType) query.set("artefact_type", artefactType);
  return api.get(`/api/v1/projects/${projectId}/tags/records?${query}`);
}

/** The `tag` and `tag_mode` query parameters of a list read (empty when no tag is chosen). */
export function tagQuery(tags: string[], mode: "any" | "all"): string {
  if (tags.length === 0) return "";
  const query = new URLSearchParams();
  for (const tag of tags) query.append("tag", tag);
  query.set("tag_mode", mode);
  return query.toString();
}

/** What a list's filters carry for tags: the chosen names and whether a record needs any or all. */
export interface TagListFilters {
  tags?: string[];
  tag_mode?: "any" | "all";
}

/** Adds the `tag` and `tag_mode` parameters of `filters` to a list read. */
export function appendTagParams(params: URLSearchParams, filters: TagListFilters): void {
  if (!filters.tags || filters.tags.length === 0) return;
  for (const tag of filters.tags) params.append("tag", tag);
  params.set("tag_mode", filters.tag_mode ?? "any");
}
