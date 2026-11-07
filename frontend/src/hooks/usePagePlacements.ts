/**
 * Module: hooks/usePagePlacements
 *
 * The places of the rows a list is showing, read in one request for the whole page, for the list's Components
 * column (`DirectoryTable`'s `placements`). A failed read shows no column rather than an error: the places are
 * secondary to the list.
 */
import { useEffect, useState } from "react";

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
  const key = ids.join(",");
  // The answer is kept with the request it belongs to, so rows that changed since are never shown the old places.
  const [answer, setAnswer] = useState<{ key: string; places: Record<string, Placement[]> } | null>(null);
  useEffect(() => {
    let active = true;
    if (!projectId || !artefactType || key === "") return;
    const asked = `${projectId}/${artefactType}/${key}`;
    api.page(projectId, artefactType, key.split(","))
      .then((places) => active && setAnswer({ key: asked, places }))
      .catch(() => active && setAnswer({ key: asked, places: {} }));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, key]);
  return answer !== null && answer.key === `${projectId}/${artefactType}/${key}` ? answer.places : NO_PLACES;
}

const NO_PLACES: Record<string, Placement[]> = {};
