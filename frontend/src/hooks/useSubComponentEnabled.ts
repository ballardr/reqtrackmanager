/**
 * Module: hooks/useSubComponentEnabled
 *
 * Whether one sub-component of a module is effectively on, read from the generic sub-component listing (so no
 * module-specific endpoint is needed): for a project, its own switch else the organisation's default; for an
 * organisation, the organisation's own switch. A page uses it to show a feature only where the backend would serve it
 * (the routes of a switched-off sub-component answer 404).
 *
 * Both hooks return `null` while loading and `false` when the lookup fails, so a caller shows nothing rather than a
 * control that would be refused.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OrgModuleSubComponent, ProjectModuleSubComponent } from "../api/types";

/** Reads `url`'s listing: the rows, an empty list when the read fails, or null while loading (a new URL reads as loading). */
function useSubComponentRows<T>(url: string | null): T[] | null {
  const [state, setState] = useState<{ url: string; rows: T[] } | null>(null);
  useEffect(() => {
    if (!url) return;
    let active = true;
    api.get<T[]>(url)
      .then((rows) => { if (active) setState({ url, rows }); })
      .catch(() => { if (active) setState({ url, rows: [] }); });
    return () => { active = false; };
  }, [url]);
  return state && state.url === url ? state.rows : null;
}

/**
 * @param projectId The project, or undefined (then the answer stays null).
 * @param moduleKey The declaring module's key.
 * @param key The sub-component's key.
 * @returns Whether the sub-component is effectively enabled for the project; null while loading.
 */
export function useProjectSubComponentEnabled(projectId: string | undefined, moduleKey: string, key: string): boolean | null {
  const rows = useSubComponentRows<ProjectModuleSubComponent>(
    projectId ? `/api/v1/projects/${projectId}/modules/${moduleKey}/subcomponents` : null,
  );
  return rows && rows.some((s) => s.subcomponent_key === key && s.effective_enabled);
}

/**
 * @param organizationId The organisation, or undefined (then the answer stays null).
 * @param moduleKey The declaring module's key.
 * @param key The sub-component's key.
 * @returns Whether the sub-component is enabled for the organisation; null while loading.
 */
export function useOrgSubComponentEnabled(organizationId: string | undefined, moduleKey: string, key: string): boolean | null {
  const rows = useSubComponentRows<OrgModuleSubComponent>(
    organizationId ? `/api/v1/orgs/${organizationId}/modules/${moduleKey}/subcomponents` : null,
  );
  return rows && rows.some((s) => s.subcomponent_key === key && s.enabled);
}
