/**
 * Module: modules/architecture/useArchitectureReference
 *
 * The reference data every architecture screen of a project needs for its forms and filters: the project and its
 * organisation's members, the effective element types, connection types, domains and symbols. Loaded once per screen; a failed
 * list resolves to empty (the form then offers nothing to choose) rather than blocking the page.
 */
import { useCallback, useEffect, useState } from "react";

import type { OrgUser, Project } from "../../api/types";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import { connectionTypeApi, domainApi, elementTypeApi, symbolApi } from "./api";
import type { ArchitectureDomain, ArchitectureSymbol, ConnectionType, ElementType } from "./types";

/** What `useArchitectureReference` returns; `loaded` is false until every list has answered. */
export interface ArchitectureReference {
  project: Project | null;
  orgUsers: OrgUser[];
  elementTypes: ElementType[];
  connectionTypes: ConnectionType[];
  domains: ArchitectureDomain[];
  symbols: ArchitectureSymbol[];
  loaded: boolean;
  /** Reads the symbol library again (after the picker uploaded a symbol). */
  reloadSymbols: () => void;
}

/**
 * @param projectId The project whose vocabularies are read.
 * @returns The reference data of the project.
 */
export function useArchitectureReference(projectId: string): ArchitectureReference {
  const { project, orgUsers } = useProjectPeople(projectId);
  const [lists, setLists] = useState<{ projectId: string; element: ElementType[]; connection: ConnectionType[]; domains: ArchitectureDomain[]; symbols: ArchitectureSymbol[] } | null>(null);

  const load = useCallback(() => {
    let live = true;
    Promise.all([
      elementTypeApi.projectList(projectId).catch(() => [] as ElementType[]),
      connectionTypeApi.projectList(projectId).catch(() => [] as ConnectionType[]),
      domainApi.projectList(projectId).catch(() => [] as ArchitectureDomain[]),
      symbolApi.projectList(projectId).catch(() => [] as ArchitectureSymbol[]),
    ]).then(([element, connection, domains, symbols]) => { if (live) setLists({ projectId, element, connection, domains, symbols }); });
    return () => { live = false; };
  }, [projectId]);
  useEffect(() => load(), [load]);

  const reloadSymbols = useCallback(() => {
    symbolApi.projectList(projectId).then((symbols) => {
      setLists((current) => (current && current.projectId === projectId ? { ...current, symbols } : current));
    }).catch(() => undefined);
  }, [projectId]);

  const ready = lists?.projectId === projectId ? lists : null;
  return {
    project,
    orgUsers: orgUsers ?? [],
    elementTypes: ready?.element ?? [],
    connectionTypes: ready?.connection ?? [],
    domains: ready?.domains ?? [],
    symbols: ready?.symbols ?? [],
    loaded: ready !== null && project !== null && orgUsers !== null,
    reloadSymbols,
  };
}
