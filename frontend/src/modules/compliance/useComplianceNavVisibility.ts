/**
 * Module: modules/compliance/useComplianceNavVisibility
 *
 * Backs whether the current user should see the top-level "Compliance
 * Standards" nav-rail tab (docs/compliance-module-plan.md Phase 18), via
 * the compliance module's own `GET /api/v1/compliance/nav-visibility`
 * (`backend/app/modules/compliance/global_router.py`) — a genuinely
 * compliance-module-owned decision (module effectively enabled for at
 * least one of the caller's orgs, and either a manage-capable role there
 * or that org having a real standard), so this logic lives inside the
 * compliance module rather than as a field bolted onto core `/auth/me/
 * memberships`, per the plan's own design.
 *
 * Deliberately a **self-contained hook backed by a tiny module-level
 * external store** (`useSyncExternalStore`), not a React Context/Provider —
 * this value is read by exactly one compliance-owned component
 * (`ComplianceGlobalNavLink.tsx`), reached only through `module.ts`'s
 * declarative `globalNavItems` registration. `Layout.tsx` never imports
 * anything from this module directly (the same boundary `orgAdminSections`
 * already enforces for `OrgAdminPage.tsx` — see that mechanism's own
 * docstring in `modules/types.ts`), so there is no core-owned tree position
 * to mount a Provider at; a plain external store needs no such position.
 *
 * Cache is keyed to the currently authenticated user's id (mirroring
 * `FavouritesContext`'s own "refetch when `user` changes" behaviour, just
 * expressed as a store invalidation instead of a Context re-render) — a
 * different user logging in on the same tab always gets a fresh fetch
 * rather than momentarily inheriting the previous user's cached value.
 * `refreshComplianceNavVisibility()` forces a refetch for the current user
 * and notifies every subscriber — call after any action that could flip
 * visibility. Known call sites today: `StandardListPage.tsx` (creating an
 * org's first standard) and `StandardWorkspacePage.tsx` (archiving/
 * unarchiving a standard, which can flip an org from/to zero non-archived
 * standards) — both already compliance-owned pages. A core page performing
 * an action that could also flip it (e.g. `OrgAdminPage.tsx` toggling the
 * module's own enablement, or granting/revoking `compliance_manager`)
 * cannot call this without the same core-imports-a-specific-module coupling
 * this file exists to avoid — visibility there converges on the next full
 * page load instead, a deliberate, documented trade-off (see
 * docs/decisions.md's Phase 18 entry) rather than a boundary exception.
 */
import { useEffect, useSyncExternalStore } from "react";

import { useAuth } from "../../context/AuthContext";
import * as complianceApi from "./api";

let cachedVisible = false;
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
      cachedVisible = r.visible;
    })
    .catch(() => {
      cachedVisible = false;
    })
    .finally(() => {
      cachedForUserId = userId;
      fetchInFlightForUserId = null;
      notify();
    });
}

function ensureFetchedFor(userId: string | null): void {
  if (userId === null) {
    if (cachedForUserId !== null || cachedVisible) {
      cachedForUserId = null;
      cachedVisible = false;
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

function getSnapshot(): boolean {
  return cachedVisible;
}

/** Forces a refetch for the current session's user and notifies every
 * subscriber once it resolves — see this module's own docstring for the
 * known call sites and why some plausible ones are deliberately absent. */
export function refreshComplianceNavVisibility(): void {
  if (cachedForUserId === null) return;
  fetchFor(cachedForUserId);
}

export function useComplianceNavVisibility(): boolean {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  // A `useEffect`, not a direct call during render — triggering the lazy
  // fetch is a side effect, and `useSyncExternalStore`'s own contract
  // requires `getSnapshot` (and, transitively, the render itself) to stay
  // pure. `ensureFetchedFor`'s own in-flight/cached-user guards make this
  // safe to call on every `userId` change without ever double-fetching.
  useEffect(() => {
    ensureFetchedFor(userId);
  }, [userId]);
  return useSyncExternalStore(subscribe, getSnapshot);
}
