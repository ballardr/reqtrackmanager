/**
 * Module: modules/compliance/useComplianceNavVisibility
 *
 * Whether the current user sees the top-level "Compliance Standards" nav-rail tab, from the compliance module's own
 * `GET /api/v1/compliance/nav-visibility`, so the decision stays in this module and not in core `/auth/me/memberships`.
 *
 * A module-level external store (`useSyncExternalStore`), not a Provider: the only reader is a compliance-owned
 * component registered through `module.ts`'s `globalNavItems`, and `Layout.tsx` has no tree position to mount one at.
 * The cache is keyed to the signed-in user's id, so a different user always gets a fresh fetch.
 * `refreshComplianceNavVisibility()` refetches and notifies subscribers; compliance-owned pages call it after an action
 * that can flip visibility (first standard created, standard archived). Core pages cannot call it without importing
 * this module, so visibility there converges on the next full page load (see docs/decisions.md).
 */
import { useEffect, useSyncExternalStore } from "react";

import { useAuth } from "../../context/AuthContext";
import * as complianceApi from "./api";

interface Snapshot extends complianceApi.ComplianceNavVisibility {
  /** False until the first answer for the current user arrives (a failed request counts as an answer). */
  loaded: boolean;
}

const NOT_LOADED: Snapshot = { visible: false, status_organization_ids: [], loaded: false };
const NOT_VISIBLE: Snapshot = { ...NOT_LOADED, loaded: true };
let cached: Snapshot = NOT_LOADED;
let cachedForUserId: string | null = null;
let fetchInFlightForUserId: string | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function fetchFor(userId: string): void {
  fetchInFlightForUserId = userId;
  complianceApi
    .getNavVisibility()
    .then((r) => {
      cached = { ...r, loaded: true };
    })
    .catch(() => {
      cached = NOT_VISIBLE;
    })
    .finally(() => {
      cachedForUserId = userId;
      fetchInFlightForUserId = null;
      notify();
    });
}

function ensureFetchedFor(userId: string | null): void {
  if (userId === null) {
    if (cachedForUserId !== null || cached.visible) {
      cachedForUserId = null;
      cached = NOT_LOADED;
      notify();
    }
    return;
  }
  if (cachedForUserId === userId || fetchInFlightForUserId === userId) return;
  fetchFor(userId);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Snapshot {
  return cached;
}

/** Forces a refetch for the current session's user and notifies every
 * subscriber once it resolves — see this module's own docstring for the
 * known call sites and why some plausible ones are deliberately absent. */
export function refreshComplianceNavVisibility(): void {
  if (cachedForUserId === null) return;
  fetchFor(cachedForUserId);
}

function useCachedVisibility(): Snapshot {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  // Fetched in an effect, not during render: the fetch is a side effect and `getSnapshot` must stay pure.
  // `ensureFetchedFor`'s guards make a call on every `userId` change safe.
  useEffect(() => {
    ensureFetchedFor(userId);
  }, [userId]);
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Whether the current user sees the "Compliance Standards" nav entry (and so the page's Standards tab). */
export function useComplianceNavVisibility(): boolean {
  return useCachedVisibility().visible;
}

/**
 * The organisations where the current user may read the organisation-wide status views (the Standards page's By
 * standard and Outstanding tabs).
 *
 * @returns `ids`: empty while loading and for a person who can only read standards; `loaded`: whether the answer is in.
 */
export function useComplianceStatusOrganizations(): { ids: readonly string[]; loaded: boolean } {
  const { status_organization_ids: ids, loaded } = useCachedVisibility();
  return { ids, loaded };
}
