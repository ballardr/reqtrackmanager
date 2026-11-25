import { useEffect, useReducer } from "react";

import type { ModuleFrontendManifest } from "../api/types";
import {
  type FederatedLoadStatus,
  getFederatedLoadError,
  getFederatedLoadStatus,
  loadFederatedModule,
  subscribeFederatedLoader,
} from "../modules/federatedLoader";

/** The shape this hook needs from an enabled-module entry; both `ModuleNavEntry`
 * (`useProjectEnabledModules`) and `OrgModule` (`OrgAdminPage.tsx`) satisfy it structurally. */
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
 * `frontend_manifest.tier === "federated"`, and re-renders the calling component
 * whenever any Tier C load's status changes: a successful load mutates
 * `federatedLoader.ts`'s module-level state (and `registry.ts`'s `installedModules`),
 * which is invisible to React. Each caller (`App.tsx`, `OrgAdminPage.tsx`) passes its own
 * project- or organisation-scoped enabled-module list.
 *
 * Returns per-module `{status, error}` so a caller can render a loading or failed state
 * instead of the module's nav entry or route silently missing (`docs/modules.md`, "Tier C").
 *
 * A module that has loaded stays merged into `installedModules` for the page's lifetime, so
 * calling this hook again is a no-op for it (`loadFederatedModule` is idempotent).
 */
export function useFederatedModules(entries: FederatedModuleCandidate[]): Record<string, FederatedModuleState> {
  const [, forceRerender] = useReducer((count: number) => count + 1, 0);

  useEffect(() => subscribeFederatedLoader(forceRerender), []);

  // Only the (module_key, remote_entry_url, exposed_module) triple decides whether a load is
  // needed; keying the effect on a stable string avoids re-running it when `entries` changes identity.
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
