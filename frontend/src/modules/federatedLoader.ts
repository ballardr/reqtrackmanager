import type { ModuleFrontendManifest } from "../api/types";
import { installedModules } from "./registry";
import type { TierAModuleDefinition } from "./types";

/**
 * Module: modules/federatedLoader
 *
 * The runtime half of Tier C ("federated") frontend module integration (`docs/decisions.md` "Module system follow-up:
 * Tier C (Module Federation)", `docs/modules.md` "Tier C"). Tier A (`registry.ts`'s build-time `import.meta.glob`)
 * needs a rebuild of the frontend image and Tier B (`<ModuleFrame>`'s sandboxed iframe) loses native component reuse.
 * Tier C is for an operator dropping in a third-party module built outside this repository, with neither: this module
 * dynamically `import()`s the module's pre-built remote entry script at runtime and merges the result into the same
 * `installedModules` array Tier A populates, so every consumer (`getInstalledModule`, `buildModuleRoutes.tsx`,
 * `OrgAdminPage.tsx`'s `moduleAdminSections`) treats it identically. `useFederatedModules`
 * (`../hooks/useFederatedModules.ts`) triggers a load and re-renders when it settles.
 *
 * Security: this is a larger trust concession than Tier A or B. Tier A code is reviewed in this repository and Tier B
 * runs in a sandboxed iframe, but a Tier C module runs in the same origin, DOM, cookies and live component tree as the
 * host the moment it loads, with no sandbox. The deployment operator must review any such plugin before enabling it
 * (`docs/decisions.md`, `docs/soc2/policies/vendor-and-subprocessor-management-policy.md`). The backend gate
 * (`Settings.allow_external_modules`, `app.modules.registry.get_frontend_manifest`) decides whether a manifest exists
 * at all; this file trusts it, as `<ModuleFrame>` trusts the backend's Tier B origin allowlist.
 *
 * Container contract: this file implements by itself the minimal contract that every Module Federation runtime
 * (webpack, `@originjs/vite-plugin-federation`, `@module-federation/vite`) exposes on a remote's entry module, instead
 * of depending on such a plugin:
 *
 * ```
 * export function init(sharedScope): Promise<void>   // registers the host's shared deps
 * export function get(exposedName): Promise<() => Module>  // resolves to a *factory* for the exposed module
 * ```
 *
 * A real federation build produces this shape plus dependency-version negotiation that this loader does not
 * replicate. Because the contract matches, switching to a real runtime's dynamic-remote API
 * (`__federation_method_setRemote` / `__federation_method_getRemote` for `@originjs/vite-plugin-federation`) changes
 * this file only, not `useFederatedModules`, `buildModuleRoutes.tsx`, `OrgAdminPage.tsx` or the backend manifest shape
 * (`docs/modules.md` "Tier C").
 *
 * Known limitations: the shared scope is a single unversioned singleton, `window.__RTM_FEDERATED_SHARED_SCOPE__`,
 * carrying the React and ReactDOM instances of this host bundle. A Tier C remote must be built against a React version
 * compatible with the host's (see the module-author guide); nothing checks it.
 */

/** The shape every Tier C remote entry module must export: the container contract of real Module Federation (see the module docstring). */
interface FederationContainer {
  init(sharedScope: FederatedSharedScope): Promise<void> | void;
  get(exposedModuleName: string): Promise<() => { moduleDefinition?: TierAModuleDefinition }>;
}

/** The host's shared-dependency singleton a Tier C remote reads instead of bundling its own copy (see "Known
 * limitations" in the module docstring). It is on `window` because a remote entry is a separate ES module graph loaded
 * by a runtime `import()` of a URL outside this bundle, and the two graphs share only the JS realm. */
export interface FederatedSharedScope {
  react: unknown;
  "react-dom": unknown;
}

declare global {
  interface Window {
    __RTM_FEDERATED_SHARED_SCOPE__?: FederatedSharedScope;
  }
}

export type FederatedLoadStatus = "loading" | "loaded" | "failed";

const statuses = new Map<string, FederatedLoadStatus>();
const inFlight = new Map<string, Promise<TierAModuleDefinition | null>>();
const errors = new Map<string, string>();
type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

/** Subscribes to every Tier C load-status change (any module, any status); `useFederatedModules` uses it to re-render its component once a load settles, since mutating `installedModules` or `statuses` is invisible to React. Returns an unsubscribe function. */
export function subscribeFederatedLoader(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current load status of `moduleKey`'s Tier C module, or `undefined`
 * if no load has ever been attempted for it this session. */
export function getFederatedLoadStatus(moduleKey: string): FederatedLoadStatus | undefined {
  return statuses.get(moduleKey);
}

/** The error message of `moduleKey`'s most recent failed load while its status is `"failed"`, else `undefined`; lets a failed-state UI show why it failed. */
export function getFederatedLoadError(moduleKey: string): string | undefined {
  return errors.get(moduleKey);
}

/** Resets all in-memory Tier C loader state; test-only. A successful load stays merged into `installedModules` for the page's lifetime, as a build-time module never un-registers. */
export function _resetFederatedLoaderStateForTests(): void {
  statuses.clear();
  inFlight.clear();
  errors.clear();
  listeners.clear();
}

/**
 * Dynamically loads `moduleKey`'s Tier C remote entry (`manifest.remote_entry_url` / `.exposed_module`) and, on
 * success, merges the result into `installedModules` (`registry.ts`), so consumers need no Tier C branch.
 *
 * Idempotent and safe to call repeatedly or concurrently for one `moduleKey`: a module already in `installedModules`
 * resolves immediately and an in-flight load is awaited, not duplicated.
 *
 * Never throws: a failure (network error, malformed remote, `moduleDefinition.key` mismatch) is logged with
 * `console.error` and recorded as the `"failed"` status (see `getFederatedLoadError`), so one module's fault does not
 * crash the page (as the backend's `app.modules.registry` isolates per-module faults).
 *
 * @param moduleKey - The module's registry key (`ModuleNavEntry.module_key` / `OrgModule.module_key`); it must equal
 *   the `key` of the loaded remote's `moduleDefinition`, or the load is rejected, so a module cannot register under
 *   another key than the backend declared.
 * @param manifest - The module's `ModuleFrontendManifest`; a no-op (resolves `null`) if `manifest.tier !== "federated"`.
 * @returns The loaded `TierAModuleDefinition`, or `null` on failure or a non-federated manifest.
 */
export function loadFederatedModule(
  moduleKey: string,
  manifest: ModuleFrontendManifest
): Promise<TierAModuleDefinition | null> {
  if (manifest.tier !== "federated" || !manifest.remote_entry_url || !manifest.exposed_module) {
    return Promise.resolve(null);
  }

  const alreadyLoaded = installedModules.find((m) => m.key === moduleKey);
  if (alreadyLoaded) {
    statuses.set(moduleKey, "loaded");
    return Promise.resolve(alreadyLoaded);
  }

  const existing = inFlight.get(moduleKey);
  if (existing) return existing;

  statuses.set(moduleKey, "loading");
  errors.delete(moduleKey);
  notify();

  const remoteEntryUrl = manifest.remote_entry_url;
  const exposedModule = manifest.exposed_module;

  const promise = (async () => {
    try {
      const [reactModule, reactDomModule] = await Promise.all([import("react"), import("react-dom")]);
      const sharedScope: FederatedSharedScope = {
        // Normalised to the plain module object: `react` and `react-dom` are CJS packages, so Vite's pre-bundling
        // exposes named exports on the namespace and on a synthetic `.default`; a remote reads
        // `sharedScope.react.createElement` whichever form its bundler produced.
        react: (reactModule as { default?: unknown }).default ?? reactModule,
        "react-dom": (reactDomModule as { default?: unknown }).default ?? reactDomModule,
      };
      window.__RTM_FEDERATED_SHARED_SCOPE__ = sharedScope;

      // `remoteEntryUrl` is a runtime value from the backend manifest, so `/* @vite-ignore */` stops Vite's static
      // analysis resolving the specifier against this bundle's module graph, which Tier C modules are never part of.
      const container = (await import(/* @vite-ignore */ remoteEntryUrl)) as Partial<FederationContainer>;
      if (typeof container.init !== "function" || typeof container.get !== "function") {
        throw new Error(
          `remote entry at ${remoteEntryUrl} does not export the required init()/get() container contract`
        );
      }
      await container.init(sharedScope);
      const factory = await container.get(exposedModule);
      const loadedModule = factory();
      const definition = loadedModule?.moduleDefinition;
      if (!definition) {
        throw new Error(`exposed module ${exposedModule} did not export a moduleDefinition`);
      }
      if (definition.key !== moduleKey) {
        throw new Error(
          `exposed module ${exposedModule}'s moduleDefinition.key ("${definition.key}") does not match the ` +
            `backend-declared module key ("${moduleKey}")`
        );
      }

      if (!installedModules.some((m) => m.key === definition.key)) {
        installedModules.push(definition);
      }
      statuses.set(moduleKey, "loaded");
      return definition;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`Failed to load federated (Tier C) module "${moduleKey}" from ${remoteEntryUrl}:`, err);
      statuses.set(moduleKey, "failed");
      errors.set(moduleKey, message);
      return null;
    } finally {
      inFlight.delete(moduleKey);
      notify();
    }
  })();

  inFlight.set(moduleKey, promise);
  return promise;
}
