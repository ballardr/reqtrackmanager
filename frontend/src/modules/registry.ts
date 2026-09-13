import type { TierAModuleDefinition } from "./types";

/**
 * Module: modules/registry
 *
 * The frontend half of the Tier A ("installed module") registration
 * convention (compliance-module-plan.md Phase 3) — the sibling of
 * `backend/app/modules/registry.py`'s `INSTALLED_MODULES`. A first-party
 * module (e.g. Compliance) ships its own `frontend/src/modules/<key>/
 * module.ts`, exporting a `moduleDefinition: TierAModuleDefinition` — the
 * frontend mirror of the backend's `app/modules/<key>/module.py` exposing a
 * `MODULE_DEFINITION` — and is what lets it directly import and render
 * every real shared component (`Toast`, `ConfirmDialog`, `Modal`,
 * `SidePanel`, `DirectoryTable`, `FilterPanel`, form inputs) rather than
 * going through the Tier B `<ModuleFrame>` iframe/bridge.
 *
 * **Auto-discovery** (module system follow-up, 2026-09-07 — see
 * `docs/decisions.md`'s "Module system follow-up: frontend module
 * auto-discovery" entry): `installedModules` is no longer a hand-maintained
 * array a new module edits this file to append to. `import.meta.glob`
 * (Vite's own build-time file-glob-to-module-map primitive — works
 * identically under the real Vite dev/build, Vitest, and Storybook's
 * Vitest-based test runner, since all three share Vite's module graph)
 * eagerly imports every first-party module's own `module.ts`, and this file
 * just assembles + sorts the results. Dropping a new `frontend/src/
 * modules/<key>/module.ts` file is now sufficient to register a module —
 * no hand-edit to this file needed, mirroring the backend's own
 * registry-driven `Base.metadata` auto-import follow-up for ORM models.
 * Third-party (npm-installed) Tier A modules are explicitly **not**
 * discovered this way — `import.meta.glob`'s pattern only ever matches
 * paths physically under this directory (`./*\/module.ts`), so an
 * npm-installed module would need its own, separate mechanism (symlinking
 * or an explicit registration point) not built here; no third-party Tier A
 * module exists yet, so building one now would be speculative (mirrors
 * Phase 3's own "both tiers built, no real third-party module ships"
 * scoping note).
 *
 * Registered for real for the first time in Phase 13 (Project Compliance
 * View) — `route.path` uses React Router's own `:projectId` param syntax
 * and must match, once the router segment is substituted for a real id,
 * the `nav_path` the backend's `ModuleFrontendManifest` declares
 * (`backend/app/modules/compliance/module.py`), which uses a literal
 * `"{project_id}"` placeholder the backend interpolates with a concrete id
 * before sending it to the frontend
 * (`routers/projects.py::list_project_enabled_modules`) — see that
 * function's own docstring. See `frontend/src/modules/compliance/
 * module.ts` for Compliance's own registration, including its
 * `orgAdminSections` (the org-level counterpart of this mechanism —
 * `OrgAdminPage.tsx` reads `installedModules` directly for those, since
 * Phase 3's routing/nav-discovery mechanism here is project-scoped end to
 * end and has no org-level equivalent; see that phase's own notes).
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
