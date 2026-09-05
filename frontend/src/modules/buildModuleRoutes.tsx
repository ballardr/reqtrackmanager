import { Route } from "react-router-dom";

import type { ModuleNavEntry } from "../api/types";
import { ModuleFrame } from "../components/ModuleFrame";
import { getInstalledModule } from "./registry";

/**
 * Builds one `<Route>` per currently-enabled module (compliance-module-
 * plan.md Phase 3), to be spread directly into `<Routes>`'s children in
 * `App.tsx` — React Router's `createRoutesFromChildren` only recognises
 * literal `<Route>`/`<Fragment>` elements in that tree, so this returns a
 * plain array of `<Route>` elements rather than a rendered wrapper
 * component (which `<Routes>` would not see into). A Tier A ("installed")
 * module contributes its own registered routes (`registry.ts`); a Tier B
 * ("remote") one gets a generic `<ModuleFrame>` route at the `nav_path` its
 * backend `ModuleFrontendManifest` declares. A module with no frontend
 * manifest at all (nothing declared, or a Tier B `frame_url` the
 * deployment's allowlist rejected) contributes nothing here, mirroring
 * `Layout.tsx`'s identical nav-side omission.
 *
 * Split out of `App.tsx` itself (which only exports the `App` component)
 * to keep Fast Refresh working there — a file mixing component and
 * non-component exports breaks it (react-refresh/only-export-components),
 * the same reasoning `context/ProjectContextValue.ts` already documents
 * for its own split from `TerminologyContext.tsx`.
 */
export function buildModuleRoutes(enabledModules: ModuleNavEntry[], projectId: string | null) {
  return enabledModules.flatMap((moduleEntry) => {
    const manifest = moduleEntry.frontend_manifest;
    if (!manifest) return [];
    if (manifest.tier === "installed") {
      const installed = getInstalledModule(moduleEntry.module_key);
      if (!installed) return [];
      return installed.routes.map((route) => (
        <Route key={`${moduleEntry.module_key}:${route.path}`} path={route.path} element={route.element} />
      ));
    }
    return [
      <Route
        key={moduleEntry.module_key}
        path={manifest.nav_path}
        element={
          <ModuleFrame
            moduleKey={moduleEntry.module_key}
            frameUrl={manifest.frame_url ?? ""}
            navLabel={manifest.nav_label}
            projectId={projectId ?? undefined}
          />
        }
      />,
    ];
  });
}
