/**
 * Module: components/useLinkGraph
 *
 * Loads a record's link graph for a trace view: `depth` hops, once per
 * (project, record, depth), with a failure flag instead of a thrown error.
 * A view of a different record mounts anew (the modal closes on navigation), so the
 * state is not reset between records.
 */
import { useEffect, useState } from "react";

import type { ArtefactLinksApi, LinkGraph } from "../api/artefactLinks";

/**
 * @param api The (injectable) links API.
 * @param projectId The page's project.
 * @param type The record's artefact type.
 * @param id The record's id.
 * @param depth Hops to read (the server allows up to 3).
 * @returns The graph (`null` while loading or after a failure) and whether the read failed.
 */
export function useLinkGraph(api: ArtefactLinksApi, projectId: string, type: string, id: string, depth = 1) {
  const [graph, setGraph] = useState<LinkGraph | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    api.graph(projectId, type, id, depth)
      .then((result) => {
        if (active) setGraph(result);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api, projectId, type, id, depth]);
  return { graph, failed };
}
