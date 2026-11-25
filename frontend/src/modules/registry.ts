import type { ReportViewDef, TierAModuleDefinition } from "./types";

/**
 * Module: modules/registry
 *
 * The frontend half of the Tier A ("installed module") registration convention, the sibling of
 * `backend/app/modules/registry.py`'s `INSTALLED_MODULES`. A first-party module (e.g. Compliance) ships its own
 * `frontend/src/modules/<key>/module.ts` exporting a `moduleDefinition: TierAModuleDefinition` (the mirror of the
 * backend's `app/modules/<key>/module.py` `MODULE_DEFINITION`), which lets it import and render the shared components
 * (`Toast`, `ConfirmDialog`, `Modal`, `SidePanel`, `DirectoryTable`, `FilterPanel`, form inputs) directly, unlike the
 * Tier B `<ModuleFrame>` iframe and bridge.
 *
 * Auto-discovery (`docs/decisions.md` "Module system follow-up: frontend module auto-discovery"): `import.meta.glob`
 * (a Vite build-time primitive that behaves the same under Vite dev/build, Vitest and Storybook, which share Vite's
 * module graph) eagerly imports every first-party `module.ts`, and this file assembles and sorts the results. Adding
 * `frontend/src/modules/<key>/module.ts` registers a module without editing this file, as the backend auto-imports ORM
 * models for `Base.metadata`. Third-party (npm-installed) Tier A modules are not discovered: the glob matches only
 * paths under this directory (`./*\/module.ts`), so they would need a separate mechanism (a symlink or an explicit
 * registration point), which is not built because no third-party Tier A module exists.
 *
 * `route.path` uses React Router's `:projectId` syntax and must match, once the segment is substituted with an id, the
 * `nav_path` of the backend's `ModuleFrontendManifest` (`backend/app/modules/compliance/module.py`). That uses a literal
 * `"{project_id}"` placeholder the backend interpolates before sending it
 * (`routers/projects.py::list_project_enabled_modules`). See `frontend/src/modules/compliance/module.ts` for
 * Compliance's registration, including `orgAdminSections`, the organisation-level counterpart that `OrgAdminPage.tsx`
 * reads from `installedModules` directly, since this routing and nav discovery is project-scoped throughout.
 */
const moduleFiles = import.meta.glob<{ moduleDefinition: TierAModuleDefinition }>("./*/module.ts", {
  eager: true,
});

export const installedModules: TierAModuleDefinition[] = Object.values(moduleFiles)
  .map((mod) => mod.moduleDefinition)
  .sort((a, b) => a.key.localeCompare(b.key));

/** Looks up a Tier A module's route registration by its `module_key`, or
 * `undefined` if no installed module registers that key (e.g. a currently-
 * enabled module is Tier B/`"remote"`, or isn't a frontend-integrated
 * module at all). */
export function getInstalledModule(key: string): TierAModuleDefinition | undefined {
  return installedModules.find((module) => module.key === key);
}

/** Looks up a module's custom view for one of its reports, or `undefined`
 * when the report has none and the generic `ReportViewer` applies. */
export function getReportView(moduleKey: string, reportKey: string): ReportViewDef | undefined {
  return getInstalledModule(moduleKey)?.reportViews?.[reportKey];
}

/** Looks up a Tier A module's registration by `module_key`, or `undefined` if no installed module registers it (for example an enabled Tier B `"remote"` module, or one with no frontend integration). */