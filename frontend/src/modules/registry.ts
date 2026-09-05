import type { TierAModuleDefinition } from "./types";

/**
 * Module: modules/registry
 *
 * The frontend half of the Tier A ("installed module") registration
 * convention (compliance-module-plan.md Phase 3) — the sibling of
 * `backend/app/modules/registry.py`'s `INSTALLED_MODULES`. A first-party
 * module (Compliance, from Phase 12) or an npm-installed third-party one
 * adds its own entry here, the same way it adds a `ModuleDefinition` to the
 * backend's `INSTALLED_MODULES`: this is what lets it directly import and
 * render every real shared component (`Toast`, `ConfirmDialog`, `Modal`,
 * `SidePanel`, `DirectoryTable`, `FilterPanel`, form inputs) rather than
 * going through the Tier B `<ModuleFrame>` iframe/bridge.
 *
 * Empty until Phase 12 registers Compliance's own frontend here — this is
 * the mechanism itself, proven only against a fixture module in this
 * codebase's own tests/stories in the absence of a real one yet, the same
 * position the backend registry's own `INSTALLED_MODULES` was left in
 * after Phase 1 until Phase 5.
 */
export const installedModules: TierAModuleDefinition[] = [];

/** Looks up a Tier A module's route registration by its `module_key`, or
 * `undefined` if no installed module registers that key (e.g. a currently-
 * enabled module is Tier B/`"remote"`, or isn't a frontend-integrated
 * module at all). */
export function getInstalledModule(key: string): TierAModuleDefinition | undefined {
  return installedModules.find((module) => module.key === key);
}
