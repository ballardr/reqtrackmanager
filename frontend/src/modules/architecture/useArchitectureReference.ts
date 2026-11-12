/**
 * Module: modules/architecture/useArchitectureReference
 *
 * The reference data every architecture screen of a project needs for its forms and filters: the project and its
 * organisation's members, the effective element types, connection types and symbols. Loaded once per screen; a failed
 * list resolves to empty (the form then offers nothing to choose) rather than blocking the page.
 */
import { useCallback, useEffect, useState } from "react";

import type { OrgUser, Project } from "../../api/types";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import { connectionTypeApi, elementTypeApi, symbolApi } from "./api";
import type { ArchitectureSymbol, ConnectionType, ElementType } from "./types";

/** What `useArchitectureReference` returns; `loaded` is false until every list has answered. */
export interface ArchitectureReference {
  project: Project | null;
  orgUsers: OrgUser[];
  elementTypes: ElementType[];
  connectionTypes: ConnectionType[];
  symbols: ArchitectureSymbol[];
  loaded: boolean;
}

/**
 * @param projectId The project whose vocabularies are read.
 * @returns The reference data of the project.
 */
export function useArchitectureReference(projectId: string): ArchitectureReference {
  const { project, orgUsers } = useProjectPeople(projectId);
  const [lists, setLists] = useState<{ projectId: string; element: ElementType[]; connection: ConnectionType[]; symbols: ArchitectureSymbol[] } | null>(null);

  const load = useCallback(() => {
    let live = true;
    Promise.all([
      elementTypeApi.projectList(projectId).catch(() => [] as ElementType[]),
      connectionTypeApi.projectList(projectId).catch(() => [] as ConnectionType[]),
      symbolApi.projectList(projectId).catch(() => [] as ArchitectureSymbol[]),
    ]).then(([element, connection, symbols]) => { if (live) setLists({ projectId, element, connection, symbols }); });
    return () => { live = false; };
  }, [projectId]);
  useEffect(() => load(), [load]);

  const ready = lists?.projectId === projectId ? lists : null;
  return {
    project,
    orgUsers: orgUsers ?? [],
    elementTypes: ready?.element ?? [],
    connectionTypes: ready?.connection ?? [],
    symbols: ready?.symbols ?? [],
    loaded: ready !== null && project !== null && orgUsers !== null,
  };
}
