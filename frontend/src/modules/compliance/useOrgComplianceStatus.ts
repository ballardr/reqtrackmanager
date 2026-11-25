/**
 * Module: modules/compliance/useOrgComplianceStatus
 *
 * Shared, deduplicated fetch of `listOrgProjectComplianceStatus(orgId)`: the organisation's compliance widgets
 * (`OrgComplianceWidgets.tsx`) and the Compliance sections of the organisation overview can mount together, so one
 * request serves them all and they cannot disagree between two requests.
 *
 * A module-level external store (`useSyncExternalStore`) with a per-`orgId` cache and in-flight guard, the same shape
 * as `useComplianceNavVisibility.ts`. A `useEffect` triggers the lazy fetch because `getSnapshot` must stay pure.
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

/** `null` while the shared fetch for `orgId` is in flight; the rows once resolved (empty both for an empty organisation and on a fetch error, matching the module's other organisation-wide lists). */
export function useOrgComplianceStatus(orgId: string): ProjectComplianceStatus[] | null {
  useEffect(() => {
    ensureFetchedFor(orgId);
  }, [orgId]);
  return useSyncExternalStore(subscribe, () => getSnapshot(orgId));
}

/** Refetches one organisation's rows and notifies every subscriber; call after an action that changes its project-compliance rows while a page reading this hook is mounted. */
export function refreshOrgComplianceStatus(orgId: string): void {
  if (!cache.has(orgId)) return;
  cache.delete(orgId);
  ensureFetchedFor(orgId);
}
