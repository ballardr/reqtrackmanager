/**
 * Module: api/externalReferences
 *
 * Types and calls for external references: the pointers from a record of any type to an item in an outside system
 * (Jira, DOORS, ...), on one record (`/projects/{id}/artefacts/{type}/{id}/external-references`), for the rows of a
 * list page (`/projects/{id}/external-references/{type}`), as the filter parameters (`external_system`,
 * `external_key`) every record list sends, and as a look-up of records by an outside key.
 *
 * {@link RecordReferencesApi} is injectable so stories stay off the network. A record's read fails with a 404 while
 * references are switched off for its type; callers treat any failed read as "show nothing".
 */
import { api } from "./client";
import { externalSystemApi } from "./externalSystems";

/** What a reference says about the item's relationship to the record. */
export type ExternalReferenceRole = "origin" | "delivery";

/** The order the role picker lists the roles in. */
export const EXTERNAL_REFERENCE_ROLES: readonly ExternalReferenceRole[] = ["origin", "delivery"];

/** The label of each role, as the picker and the badge show it. */
export const EXTERNAL_REFERENCE_ROLE_LABEL: Record<ExternalReferenceRole, string> = {
  origin: "Origin",
  delivery: "Delivery",
};

/** One reference as the server returns it; `link` is what it opens (its own link, else the system's template with the key). */
export interface ExternalReference {
  id: string;
  artefact_type: string;
  artefact_id: string;
  /** An id the record's tier's system picker accepts. */
  system_id: string;
  system_name: string;
  key: string;
  url: string | null;
  link: string | null;
  note: string;
  role: ExternalReferenceRole | null;
  created_by: string;
  created_at: string;
}

/** A system a record of this tier can be given a reference in. */
export interface ReferenceSystem {
  id: string;
  name: string;
  url_template: string | null;
}

/** One record's references and what its editor needs. */
export interface RecordReferences {
  references: ExternalReference[];
  can_edit: boolean;
  systems: ReferenceSystem[];
}

/** The values one reference is saved with. A blank `url` or `role` is sent as `null` (clears it). */
export interface ReferenceInput {
  system_id: string;
  key: string;
  url: string | null;
  note: string;
  role: ExternalReferenceRole | null;
}

/** A record found by an outside key, with the reference that matched. */
export interface ReferencedRecord {
  artefact_type: string;
  type_label: string;
  id: string;
  label: string;
  status: string | null;
  is_archived: boolean;
  project_id: string | null;
  project_name: string | null;
  project_code: string | null;
  reference: ExternalReference;
}

/** The references of one record; injectable for stories. Every write returns the record's whole set again. */
export interface RecordReferencesApi {
  get(projectId: string, type: string, id: string): Promise<RecordReferences>;
  add(projectId: string, type: string, id: string, input: ReferenceInput): Promise<RecordReferences>;
  update(projectId: string, type: string, id: string, referenceId: string, input: ReferenceInput): Promise<RecordReferences>;
  remove(projectId: string, type: string, id: string, referenceId: string): Promise<RecordReferences>;
  /** The references of a page of records of one type (`{record id: references}`; a record with none is absent). */
  page(projectId: string, type: string, ids: string[]): Promise<Record<string, ExternalReference[]>>;
}

function recordBase(projectId: string, type: string, id: string): string {
  return `/api/v1/projects/${projectId}/artefacts/${encodeURIComponent(type)}/${id}/external-references`;
}

/** The live implementation of {@link RecordReferencesApi}. */
export const recordReferencesApi: RecordReferencesApi = {
  get: (projectId, type, id) => api.get<RecordReferences>(recordBase(projectId, type, id)),
  add: (projectId, type, id, input) => api.post<RecordReferences>(recordBase(projectId, type, id), input),
  update: (projectId, type, id, referenceId, input) =>
    api.patch<RecordReferences>(`${recordBase(projectId, type, id)}/${referenceId}`, input),
  remove: (projectId, type, id, referenceId) => api.delete<RecordReferences>(`${recordBase(projectId, type, id)}/${referenceId}`),
  page: async (projectId, type, ids) => {
    if (ids.length === 0) return {};
    const query = new URLSearchParams();
    for (const id of ids) query.append("id", id);
    const result = await api.get<{ references: Record<string, ExternalReference[]> }>(
      `/api/v1/projects/${projectId}/external-references/${encodeURIComponent(type)}?${query}`,
    );
    return result.references;
  },
};

/**
 * Records carrying an outside key, for an integration or a person holding a Jira key (`GET .../records/by-external-reference`).
 *
 * @param projectId The project to look in.
 * @param key The key in the outside system (exact, ignoring case).
 * @param system A system name, or omit for any system.
 * @param artefactType Only records of this registered type.
 */
export async function findRecordsByReference(
  projectId: string, key: string, system?: string, artefactType?: string,
): Promise<{ records: ReferencedRecord[]; truncated: boolean }> {
  const query = new URLSearchParams({ key });
  if (system) query.set("system", system);
  if (artefactType) query.set("artefact_type", artefactType);
  return api.get(`/api/v1/projects/${projectId}/records/by-external-reference?${query}`);
}

/** `Jira: PROJ-1`: one reference as text (a reference with only a link shows the link). */
export function referenceLabel(reference: Pick<ExternalReference, "system_name" | "key" | "url" | "link">): string {
  return `${reference.system_name}: ${reference.key || reference.url || reference.link || ""}`.trimEnd();
}

/** A record's references as one cell of text (`Jira: PROJ-1, DOORS: REQ-9`), empty when it has none. */
export function referencesText(references: Array<Pick<ExternalReference, "system_name" | "key" | "url" | "link">> | undefined): string {
  return (references ?? []).map(referenceLabel).join(", ");
}

/** True for an absolute http(s) URL: the only kind a reference is rendered as a clickable link. */
export function isWebUrl(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}

/** What a list's filters carry for external references: the system names (any of them) and a fragment of the key. */
export interface ReferenceListFilters {
  external_systems?: string[];
  external_key?: string;
}

/** Adds the `external_system` and `external_key` parameters of `filters` to a list read (blank values are left out). */
export function appendReferenceParams(params: URLSearchParams, filters: ReferenceListFilters): void {
  for (const name of filters.external_systems ?? []) params.append("external_system", name);
  const key = filters.external_key?.trim();
  if (key) params.set("external_key", key);
}

/** What the list filter needs to offer: the names of the systems the project's records can be referenced in. Injectable for stories. */
export interface ReferenceFilterApi {
  systems(projectId: string): Promise<string[]>;
}

/** The live implementation of {@link ReferenceFilterApi}: the project's enabled systems, in display order. */
export const referenceFilterApi: ReferenceFilterApi = {
  systems: async (projectId) => {
    const rows = await externalSystemApi.project.list(projectId);
    return rows.filter((row) => row.is_enabled).sort((a, b) => a.display_order - b.display_order).map((row) => row.name);
  },
};
