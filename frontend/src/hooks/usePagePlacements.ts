/**
 * Module: hooks/usePagePlacements
 *
 * The places of the rows a list is showing, read in one request for the whole page, for the list's Components
 * column (`DirectoryTable`'s `placements`). A failed read shows no column rather than an error: the places are
 * secondary to the list.
 */
import { useEffect, useState } from "react";

import { useLatest } from "./useLatest";
import { recordPlacementsApi, type Placement, type RecordPlacementsApi } from "../api/placements";

/**
 * @param projectId The project the list is opened in; `undefined` turns the read off.
 * @param artefactType The listed record type.
 * @param ids The ids of the rows on the page.
 * @param api Injectable calls (stories pass a fake).
 * @returns `{record id: places}` for the rows that are placed somewhere (empty until the read returns).
 */
export function usePagePlacements(
  projectId: string | undefined, artefactType: string | undefined, ids: string[], api: RecordPlacementsApi = recordPlacementsApi,
): Record<string, Placement[]> {
  return usePagePlacementsByType(projectId, artefactType ? { [artefactType]: ids } : {}, api);
}

/**
 * The same read for a list that shows more than one record type (the Diagrams list): one request per type, merged.
 *
 * @param projectId The project the list is opened in; `undefined` turns the read off.
 * @param idsByType `{record type: the ids of that type's rows on the page}`; a type with no rows is not asked about.
 * @param api Injectable calls (stories pass a fake).
 * @returns `{record id: places}` for the rows that are placed somewhere (empty until the reads return).
 */
export function usePagePlacementsByType(
  projectId: string | undefined, idsByType: Record<string, string[]>, api: RecordPlacementsApi = recordPlacementsApi,
): Record<string, Placement[]> {
  const asks = Object.entries(idsByType).filter(([, ids]) => ids.length > 0).sort(([a], [b]) => a.localeCompare(b));
  const key = asks.map(([type, ids]) => `${type}:${ids.join(",")}`).join("|");
  // The effect reads the asks through a ref: `key` names exactly what they are, so it is the only dependency.
  const latestAsks = useLatest(asks);
  // The answer is kept with the request it belongs to, so rows that changed since are never shown the old places.
  const [answer, setAnswer] = useState<{ key: string; places: Record<string, Placement[]> } | null>(null);
  useEffect(() => {
    let active = true;
    if (!projectId || key === "") return;
    const asked = `${projectId}/${key}`;
    Promise.all((latestAsks.current ?? []).map(([type, ids]) => api.page(projectId, type, ids).catch(() => ({} as Record<string, Placement[]>))))
      .then((parts) => active && setAnswer({ key: asked, places: Object.assign({}, ...parts) }));
    return () => {
      active = false;
    };
  }, [api, projectId, key, latestAsks]);
  return answer !== null && answer.key === `${projectId}/${key}` ? answer.places : NO_PLACES;
}

const NO_PLACES: Record<string, Placement[]> = {};
