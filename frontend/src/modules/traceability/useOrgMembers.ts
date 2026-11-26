/**
 * Module: modules/traceability/useOrgMembers
 *
 * Loads an organisation's users once for the principal pickers of a policy form, so a picked user shows a name.
 * A failed read leaves the list empty: the pickers still search the directory by name.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";

/**
 * @param organizationId The organisation whose users are wanted; `undefined` until it is known.
 * @returns The organisation's users, empty until loaded or when the read fails.
 */
export function useOrgMembers(organizationId: string | undefined): OrgUser[] {
  const [loaded, setLoaded] = useState<{ organizationId: string; users: OrgUser[] } | null>(null);
  useEffect(() => {
    if (!organizationId) return;
    let live = true;
    api.get<OrgUser[]>(`/api/v1/orgs/${organizationId}/users`).then(
      (users) => { if (live) setLoaded({ organizationId, users }); },
      () => { if (live) setLoaded({ organizationId, users: [] }); },
    );
    return () => { live = false; };
  }, [organizationId]);
  return loaded && loaded.organizationId === organizationId ? loaded.users : [];
}
