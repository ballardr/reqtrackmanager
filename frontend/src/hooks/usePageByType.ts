/**
 * Module: hooks/usePageByType
 *
 * The one read behind a list's per-record extra columns (Components, External references): ask the server about the
 * rows a page is showing, one request per record type, and merge the answers by record id. A failed read shows no
 * column rather than an error, since the extra is secondary to the list, and an answer is kept with the request it
 * belongs to so rows that changed since are never shown the old values.
 */
import { useEffect, useState } from "react";

import { useLatest } from "./useLatest";

/**
 * @param projectId The project the list is opened in; `undefined` turns the read off.
 * @param idsByType `{record type: the ids of that type's rows on the page}`; a type with no rows is not asked about.
 * @param read Reads one type's answer (`{record id: value}`); it is called again only when the project or the ids change.
 * @returns `{record id: value}` for the rows the server answered about (empty until the reads return).
 */
export function usePageByType<T>(
  projectId: string | undefined, idsByType: Record<string, string[]>,
  read: (projectId: string, type: string, ids: string[]) => Promise<Record<string, T>>,
): Record<string, T> {
  const asks = Object.entries(idsByType).filter(([, ids]) => ids.length > 0).sort(([a], [b]) => a.localeCompare(b));
  const key = asks.map(([type, ids]) => `${type}:${ids.join(",")}`).join("|");
  // The effect reads the asks and the reader through refs: `key` names exactly what they are, so it is the only dependency.
  const latestAsks = useLatest(asks);
  const latestRead = useLatest(read);
  const [answer, setAnswer] = useState<{ key: string; values: Record<string, T> } | null>(null);
  useEffect(() => {
    let active = true;
    if (!projectId || key === "") return;
    const asked = `${projectId}/${key}`;
    Promise.all((latestAsks.current ?? []).map(([type, ids]) => latestRead.current!(projectId, type, ids).catch(() => ({} as Record<string, T>))))
      .then((parts) => active && setAnswer({ key: asked, values: Object.assign({}, ...parts) }));
    return () => {
      active = false;
    };
  }, [projectId, key, latestAsks, latestRead]);
  return answer !== null && answer.key === `${projectId}/${key}` ? answer.values : (NONE as Record<string, T>);
}

const NONE: Record<string, never> = {};
