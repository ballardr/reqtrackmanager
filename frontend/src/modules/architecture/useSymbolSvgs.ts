/**
 * Module: modules/architecture/useSymbolSvgs
 *
 * Fetches the sanitised SVG text of the symbols a diagram draws, once per symbol, for the shared canvas (which sanitises it a
 * second time before showing it as an image). The request carries the person's token and goes through the project, which
 * applies the visibility rule; a symbol that cannot be read is simply not drawn.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import { projectSymbolUrl } from "./api";

/**
 * @param projectId The project the symbols are read through.
 * @param symbolIds The symbols the diagram's boxes use (duplicates and nulls are ignored).
 * @returns A lookup from a symbol id to its SVG text, once fetched.
 */
export function useSymbolSvgs(projectId: string, symbolIds: (string | null)[]): (symbolId: string) => string | undefined {
  const [loaded, setLoaded] = useState<Record<string, string | null>>({});
  const requested = useRef(new Set<string>());
  const wanted = [...new Set(symbolIds.filter((id): id is string => id !== null))].sort().join(",");

  useEffect(() => {
    let live = true;
    for (const id of wanted.split(",").filter(Boolean)) {
      const slot = `${projectId}:${id}`;
      if (requested.current.has(slot)) continue;
      requested.current.add(slot);
      api.getForBlob(projectSymbolUrl(projectId, id))
        .then((blob) => blob.text())
        .catch(() => null)
        .then((svg) => { if (live) setLoaded((current) => ({ ...current, [slot]: svg })); });
    }
    return () => { live = false; };
  }, [projectId, wanted]);

  // Stable until a symbol arrives, so a canvas built from it is not rebuilt on every render.
  return useCallback((symbolId: string) => loaded[`${projectId}:${symbolId}`] ?? undefined, [loaded, projectId]);
}
