import { useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { ProjectContext } from "../context/ProjectContextValue";

/** Organisation codes already fetched, so a list of organisation-owned records asks once. */
const codes = new Map<string, Promise<string | null>>();

/** Forgets (or replaces) the cached code of an organisation after an admin changes it. */
export function rememberOrganizationCode(orgId: string, code: string | null): void {
  if (code === null) codes.delete(orgId);
  else codes.set(orgId, Promise.resolve(code));
}

/**
 * The code of an organisation, which qualifies the codes of records it owns (`ACME-PER-001`).
 * Inside a project the project's own organisation is already known; elsewhere (the organisation
 * pages) it is fetched once per organisation.
 *
 * @param orgId The organisation, or null/undefined for a record that is not organisation-owned.
 * @returns The code, or null while it loads, on failure, or when `orgId` is empty.
 */
export function useOrganizationCode(orgId: string | null | undefined): string | null {
  const project = useContext(ProjectContext);
  const known = orgId && project.organizationId === orgId ? (project.organizationCode ?? null) : null;
  const [fetched, setFetched] = useState<{ orgId: string; code: string | null } | null>(null);
  useEffect(() => {
    if (!orgId || known) return;
    let active = true;
    let pending = codes.get(orgId);
    if (!pending) {
      pending = api.get<Organization>(`/api/v1/orgs/${orgId}`).then((org) => org.code || null).catch(() => null);
      codes.set(orgId, pending);
    }
    void pending.then((code) => {
      if (active) setFetched({ orgId, code });
    });
    return () => {
      active = false;
    };
  }, [orgId, known]);
  if (!orgId) return null;
  return known ?? (fetched?.orgId === orgId ? fetched.code : null);
}

/**
 * The code to pass as a record's owner when displaying its code: the owning organisation's code for
 * an organisation-scoped record, `undefined` for a project-scoped one (its own project is implied).
 */
export function useRecordOwnerCode(record: { scope?: string; organization_id?: string | null }): string | undefined {
  return useOrganizationCode(record.scope === "organization" ? record.organization_id : null) ?? undefined;
}
