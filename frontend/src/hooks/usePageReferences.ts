/**
 * Module: hooks/usePageReferences
 *
 * The external references of the rows a list is showing, read in one request for the whole page, for the list's
 * External references column (`DirectoryTable`'s `placements` config carries it, a hand-written table calls this and
 * `referencesText`). A failed read, or references switched off for the type, shows no column rather than an error.
 */
import { recordReferencesApi, type ExternalReference, type RecordReferencesApi } from "../api/externalReferences";
import { usePageByType } from "./usePageByType";

/**
 * @param projectId The project the list is opened in; `undefined` turns the read off.
 * @param artefactType The listed record type.
 * @param ids The ids of the rows on the page.
 * @param api Injectable calls (stories pass a fake).
 * @returns `{record id: references}` for the rows that have some (empty until the read returns).
 */
export function usePageReferences(
  projectId: string | undefined, artefactType: string | undefined, ids: string[], api: RecordReferencesApi = recordReferencesApi,
): Record<string, ExternalReference[]> {
  return usePageReferencesByType(projectId, artefactType ? { [artefactType]: ids } : {}, api);
}

/**
 * The same read for a list that shows more than one record type: one request per type, merged.
 *
 * @param projectId The project the list is opened in; `undefined` turns the read off.
 * @param idsByType `{record type: the ids of that type's rows on the page}`; a type with no rows is not asked about.
 * @param api Injectable calls (stories pass a fake).
 */
export function usePageReferencesByType(
  projectId: string | undefined, idsByType: Record<string, string[]>, api: RecordReferencesApi = recordReferencesApi,
): Record<string, ExternalReference[]> {
  return usePageByType(projectId, idsByType, api.page);
}
