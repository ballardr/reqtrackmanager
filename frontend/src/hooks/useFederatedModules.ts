import { useEffect, useReducer } from "react";

import type { ModuleFrontendManifest } from "../api/types";
import {
  type FederatedLoadStatus,
  getFederatedLoadError,
  getFederatedLoadStatus,
  loadFederatedModule,
  subscribeFederatedLoader,
} from "../modules/federatedLoader";

/** The minimal shape this hook needs from an enabled-module entry — matches
 * both `ModuleNavEntry` (project scope, `useProjectEnabledModules`) and
 * `OrgModule` (org scope, `OrgAdminPage.tsx`) structurally, so either can be
 * passed directly without an adapter. */
export interface FederatedModuleCandidate {
  module_key: string;
  frontend_manifest: ModuleFrontendManifest | null;
}

export interface FederatedModuleState {
  status: FederatedLoadStatus;
  error?: string;
}

/**
 * Triggers a Tier C ("federated") load for every entry in `entries` whose
 * `frontend_manifest.tier === "federated"`, and re-renders the calling
 * component whenever any Tier C load's status changes anywhere on the page
 * — necessary because a successful load mutates `federatedLoader.ts`'s
 * module-level state (and pushes into `registry.ts`'s `installedModules`
 * array), which is otherwise invisible to React. `App.tsx` (`ProtectedRoutes`)
 * and `OrgAdminPage.tsx` each call this independently with their own
 * project-/org-scoped enabled-module list, mirroring this codebase's
 * existing "each concern fetches/derives its own data" convention
 * (`useProjectEnabledModules`'s own docstring) rather than a shared
 * provider.
 *
 * Deliberately returns per-module `{status, error}` (not just "done yet?")
 * so a caller can render a loading/failed affordance rather than the
 * module's nav entry/route silently never appearing — see `docs/modules.md`'s
 * "Tier C" section for the UX this backs, and this hook's own Storybook
 * coverage (`federatedLoader.stories.tsx`) for the loading/loaded/failed/
 * disabled states exercised.
 *
 * Once a module has loaded successfully this session, it stays merged into
 * `installedModules` for the lifetime of the page — calling this hook again
 * (even with a different `entries` array) is a cheap no-op for an
 * already-loaded module (`loadFederatedModule`'s own idempotency).
 */
export function useFederatedModules(entries: FederatedModuleCandidate[]): Record<string, FederatedModuleState> {
  const [, forceRerender] = useReducer((count: number) => count + 1, 0);

  useEffect(() => subscribeFederatedLoader(forceRerender), []);

  // Only the (module_key, remote_entry_url, exposed_module) triple actually
  // matters for whether a new load needs triggering — re-running this
  // effect merely because `entries`'s own array identity changed (a new
  // fetch result with byte-identical content, e.g.) would be harmless but
  // wasteful, since `loadFederatedModule` already no-ops for an
  // already-loaded/in-flight module; keyed on a stable string so this
  // effect doesn't need `entries` itself in its dependency array.
  const federatedKey = entries
    .filter((entry) => entry.frontend_manifest?.tier === "federated")
    .map((entry) => `${entry.module_key}:${entry.frontend_manifest?.remote_entry_url}:${entry.frontend_manifest?.exposed_module}`)
    .sort()
    .join("|");

  useEffect(() => {
    for (const entry of entries) {
      if (entry.frontend_manifest?.tier === "federated") {
        void loadFederatedModule(entry.module_key, entry.frontend_manifest);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `federatedKey` is the intentionally-narrowed dependency; see comment above.
  }, [federatedKey]);

  const result: Record<string, FederatedModuleState> = {};
  for (const entry of entries) {
    if (entry.frontend_manifest?.tier !== "federated") continue;
    const status = getFederatedLoadStatus(entry.module_key) ?? "loading";
    result[entry.module_key] = status === "failed" ? { status, error: getFederatedLoadError(entry.module_key) } : { status };
  }
  return result;
}
