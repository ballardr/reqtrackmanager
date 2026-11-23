import { Route } from "react-router-dom";

import type { ModuleNavEntry } from "../api/types";
import { ModuleFrame } from "../components/ModuleFrame";
import { getInstalledModule } from "./registry";

/**
 * Builds one `<Route>` per enabled module, to be spread into `<Routes>`' children in `App.tsx`. It returns a plain array of
 * literal `<Route>` elements because React Router's `createRoutesFromChildren` does not see into a wrapper component. A Tier A
 * ("installed") module contributes its registered routes (`registry.ts`); a Tier B ("remote") one gets a generic `<ModuleFrame>`
 * route at the `nav_path` its backend `ModuleFrontendManifest` declares. A module with no frontend manifest (nothing declared,
 * or a Tier B `frame_url` the deployment's allowlist rejected) contributes nothing, as in `Layout.tsx`'s nav.
 * It lives outside `App.tsx` so that file exports only a component, which Fast Refresh requires
 * (react-refresh/only-export-components).
 */
export function buildModuleRoutes(enabledModules: ModuleNavEntry[], projectId: string | null) {
  return enabledModules.flatMap((moduleEntry) => {
    const manifest = moduleEntry.frontend_manifest;
    if (!manifest) return [];
    if (manifest.tier === "installed") {
      const installed = getInstalledModule(moduleEntry.module_key);
      if (!installed) return [];
      // `routes` is optional: a module contributing only `orgAdminSections` declares none.
      return (installed.routes ?? []).map((route) => (
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
