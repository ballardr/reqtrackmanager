import { createElement } from "react";

import type { TierAModuleDefinition } from "./types";
import { ProjectCompliancePage } from "./compliance/ProjectCompliancePage";

/**
 * Module: modules/registry
 *
 * The frontend half of the Tier A ("installed module") registration
 * convention (compliance-module-plan.md Phase 3) — the sibling of
 * `backend/app/modules/registry.py`'s `INSTALLED_MODULES`. A first-party
 * module (Compliance) or an npm-installed third-party one adds its own
 * entry here, the same way it adds a `ModuleDefinition` to the backend's
 * `INSTALLED_MODULES`: this is what lets it directly import and render
 * every real shared component (`Toast`, `ConfirmDialog`, `Modal`,
 * `SidePanel`, `DirectoryTable`, `FilterPanel`, form inputs) rather than
 * going through the Tier B `<ModuleFrame>` iframe/bridge.
 *
 * Registered here for real for the first time in Phase 13 (Project
 * Compliance View) — `route.path` uses React Router's own `:projectId`
 * param syntax and must match, once the router segment is substituted for
 * a real id, the `nav_path` the backend's `ModuleFrontendManifest`
 * declares (`backend/app/modules/compliance/module.py`), which uses a
 * literal `"{project_id}"` placeholder the backend interpolates with a
 * concrete id before sending it to the frontend
 * (`routers/projects.py::list_project_enabled_modules`) — see that
 * function's own docstring. Phase 12's org-scoped `ComplianceAdminPanel`
 * needed no entry here since Phase 3's routing mechanism is project-scoped
 * end to end and has no org-level equivalent (see that phase's own notes);
 * this is the mechanism's first real exercise.
 */
export const installedModules: TierAModuleDefinition[] = [
  {
    key: "compliance",
    routes: [
      { path: "/projects/:projectId/modules/compliance", element: createElement(ProjectCompliancePage) },
    ],
  },
];

/** Looks up a Tier A module's route registration by its `module_key`, or
 * `undefined` if no installed module registers that key (e.g. a currently-
 * enabled module is Tier B/`"remote"`, or isn't a frontend-integrated
 * module at all). */
export function getInstalledModule(key: string): TierAModuleDefinition | undefined {
  return installedModules.find((module) => module.key === key);
}
