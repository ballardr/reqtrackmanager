/**
 * Module: modules/compliance/useOrgComplianceStatus
 *
 * Shared, deduplicated fetch of `listOrgProjectComplianceStatus(orgId)` —
 * extracted (compliance-module-plan.md Phase 25b hardening) because
 * `ComplianceOrgOverviewTiles.tsx` (the `OrgOverviewPage.tsx` header tiles)
 * and `OrgComplianceDashboard.tsx` (the default-active `orgOverviewSections`
 * group on that same page) both need these exact rows and, by construction,
 * both mount at once on a normal page load (`OrgOverviewPage.tsx`'s own
 * `sections[0]` fallback renders the Dashboard group by default, right
 * alongside the always-visible header). Two independent `useEffect`/
 * `useState` fetches were firing the identical request twice per page load
 * and could transiently disagree if a compliance assessment changed
 * between the two requests resolving — the same "two copies of the same
 * logic drifting apart" risk `orgComplianceSummary.ts`'s own extraction
 * already targeted, one layer further down (the fetch itself, not just the
 * computation over its result).
 *
 * Deliberately a **self-contained hook backed by a tiny module-level
 * external store** (`useSyncExternalStore`), mirroring
 * `useComplianceNavVisibility.ts`'s own identical shape one directory up —
 * same "module-level cache + in-flight guard + `useSyncExternalStore`"
 * mechanism, just keyed by `orgId` instead of the current user's id, and
 * caching a resolved value per key rather than a single global one. A
 * `useEffect`, not a direct call during render, triggers the lazy fetch
 * (`getSnapshot` must stay pure per `useSyncExternalStore`'s own contract).
 */
import { useEffect, useSyncExternalStore } from "react";

import * as complianceApi from "./api";
import type { ProjectComplianceStatus } from "./types";

interface CacheEntry {
  data: ProjectComplianceStatus[] | null;
  inFlight: boolean;
}

const cache = new Map<string, CacheEntry>();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function ensureFetchedFor(orgId: string): void {
  const existing = cache.get(orgId);
  if (existing && (existing.data !== null || existing.inFlight)) return;
  cache.set(orgId, { data: null, inFlight: true });
  complianceApi
    .listOrgProjectComplianceStatus(orgId)
    .then((rows) => {
      cache.set(orgId, { data: rows, inFlight: false });
    })
    .catch(() => {
      cache.set(orgId, { data: [], inFlight: false });
    })
    .finally(() => notify());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(orgId: string): ProjectComplianceStatus[] | null {
  return cache.get(orgId)?.data ?? null;
}

/** `null` while the (shared, deduplicated) fetch for this `orgId` is still
 * in flight; the rows once resolved (an empty array on either a genuinely
 * empty org or a fetch error — callers can't distinguish the two, matching
 * every other org-wide compliance list's own "swallow and render empty"
 * convention in this module). */
export function useOrgComplianceStatus(orgId: string): ProjectComplianceStatus[] | null {
  useEffect(() => {
    ensureFetchedFor(orgId);
  }, [orgId]);
  return useSyncExternalStore(subscribe, () => getSnapshot(orgId));
}

/** Forces a refetch for one org and notifies every subscriber once it
 * resolves — call after any action that could change this org's
 * project-compliance rows (e.g. an assessment update) while a page reading
 * this hook is mounted. No known call site yet (both current consumers are
 * read-only dashboards reached via fresh navigation), included for the same
 * reason `useComplianceNavVisibility.ts`'s own `refresh*` export exists:
 * cache invalidation should be a first-class part of the hook's contract,
 * not bolted on the first time it's needed. */
export function refreshOrgComplianceStatus(orgId: string): void {
  if (!cache.has(orgId)) return;
  cache.delete(orgId);
  ensureFetchedFor(orgId);
}
