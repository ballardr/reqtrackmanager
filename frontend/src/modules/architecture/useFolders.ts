/**
 * Module: modules/architecture/useFolders
 *
 * Loads the folders of one kind (elements, connections or diagrams) for a project, or the organisation's element
 * folders, and gives the calls to change them. Folders are navigation only, so a failed read (the organisation's list
 * is for administrators; a module that is off) is an empty list, never an error the page has to handle.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { orgFolderApi, projectFolderApi } from "./api";
import type { ArchitectureFolder, FolderKind } from "./types";

/** Whose folders: a project's (any kind) or an organisation's element folders. */
export interface FolderOwner {
  projectId?: string;
  organizationId?: string;
}

/**
 * @param owner The project or organisation whose folders to load; nothing loads without one.
 * @param kind Which list the folders organise (an organisation has `element` only).
 * @returns The folders in tree order, whether they have loaded, the calls and `reload`.
 */
export function useFolders({ projectId, organizationId }: FolderOwner, kind: FolderKind) {
  const [folders, setFolders] = useState<ArchitectureFolder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const calls = useMemo(
    () => (projectId ? projectFolderApi(projectId, kind) : organizationId ? orgFolderApi(organizationId) : null),
    [projectId, organizationId, kind],
  );

  useEffect(() => {
    if (!calls) return;
    let active = true;
    calls.list()
      // Anything but a list (a screen that answers every read alike) is no folders.
      .then((list) => { if (active) { setFolders(Array.isArray(list) ? list : []); setLoaded(true); } })
      .catch(() => { if (active) { setFolders([]); setLoaded(true); } });
    return () => { active = false; };
  }, [calls, refreshKey]);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  return { folders, loaded, calls, reload };
}
