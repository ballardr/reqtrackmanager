import type { ReactNode } from "react";

/**
 * One route a Tier A ("installed") module contributes — a plain React
 * Router route spliced into `App.tsx`'s `<Routes>` alongside the core
 * pages, compiled directly into this bundle (compliance-module-plan.md
 * Phase 3). `path` must match the `nav_path` the module's backend
 * `ModuleFrontendManifest` declares, so the nav entry `Layout.tsx` renders
 * (from `GET /projects/{id}/enabled-modules`) actually links somewhere.
 */
export interface TierAModuleRoute {
  path: string;
  element: ReactNode;
}

/**
 * A first-party (or npm-installed third-party) Tier A module's frontend
 * registration — the module ships its own route components and registers
 * them here, the same way this file's own first-party pages are declared
 * in `App.tsx`, rather than through any dynamic/remote-loading mechanism
 * (that's Tier B, `<ModuleFrame>`). See `registry.ts`'s own docstring.
 */
export interface TierAModuleDefinition {
  /** Must match the `module_key` the backend `ModuleDefinition` registers
   * (`backend/app/modules/registry.py`), so `App.tsx` can look up which
   * routes to mount for a given currently-enabled module. */
  key: string;
  routes: TierAModuleRoute[];
}
