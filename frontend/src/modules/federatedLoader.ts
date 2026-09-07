import type { ModuleFrontendManifest } from "../api/types";
import { installedModules } from "./registry";
import type { TierAModuleDefinition } from "./types";

/**
 * Module: modules/federatedLoader
 *
 * The runtime half of Tier C ("federated") frontend module integration —
 * module system follow-up, 2026-09-07, see `docs/decisions.md`'s "Module
 * system follow-up: Tier C (Module Federation)" entries and
 * `docs/modules.md`'s "Tier C" section for the full design account. Tier A
 * (`registry.ts`'s build-time `import.meta.glob`) and Tier B
 * (`<ModuleFrame>`'s sandboxed iframe) both require either a rebuild of this
 * frontend image (Tier A) or accept losing native component reuse (Tier B).
 * Tier C is for an operator who wants to drop in a genuinely third-party
 * module — built entirely outside this repo, on the module author's own
 * schedule — with **neither** a rebuild **nor** an iframe: this module
 * dynamically `import()`s the module's own pre-built remote entry script at
 * runtime and merges the result into the exact same `installedModules`
 * array Tier A's build-time discovery populates, so every existing
 * consumer (`getInstalledModule`, `buildModuleRoutes.tsx`, `OrgAdminPage.
 * tsx`'s `moduleAdminSections`) treats a Tier C module identically to one
 * discovered at build time — see `useFederatedModules` (`../hooks/
 * useFederatedModules.ts`) for how a component triggers this and re-renders
 * once a load settles.
 *
 * **Security note, stated as plainly here as everywhere else this system
 * documents it**: this is a materially bigger trust concession than either
 * Tier A or Tier B. Tier A's code was reviewed in this repo before the
 * image was built; Tier B's code runs in a sandboxed iframe with no DOM/
 * cookie access to the host. A Tier C module's code runs in the **same
 * origin, same DOM, same cookies, and the same live component tree** as
 * the host the instant it loads — there is no sandbox at all. The trust
 * falls entirely to the deployment operator to review and vet any such
 * plugin before enabling it (the repo owner's own framing, recorded
 * verbatim in `docs/decisions.md` and `docs/soc2/policies/
 * vendor-and-subprocessor-management-policy.md`). The backend's own gate
 * (`Settings.allow_external_modules`, `app.modules.registry.
 * get_frontend_manifest`) is what stands between "this manifest exists at
 * all" and "nothing to load" — this file trusts that gate, the same way
 * `<ModuleFrame>` trusts the backend's Tier B origin-allowlist rather than
 * re-implementing it client-side.
 *
 * **Container contract — a deliberate, documented substitution for a real
 * Module Federation runtime library.** The design this mechanism was built
 * against calls for `@originjs/vite-plugin-federation` (or an equivalent
 * dynamic-remote-capable Module Federation plugin) on both the host and a
 * real module author's own build. This repository's own sandboxed build/
 * test environment had no network access to the npm registry when this was
 * built (confirmed directly: `npm view`/`npm install` both timed out
 * against `registry.npmjs.org`), so adding that dependency here could not
 * be installed, built, or verified — and per this repo's own standing rule
 * to leave the test suite passing, a `vite.config.ts` importing a package
 * that isn't actually in `node_modules` would break every frontend
 * typecheck/lint/build/test run, not just this one feature. Rather than
 * ship that, this file implements, by hand, the same minimal container
 * contract every real Module Federation runtime (webpack's, `@originjs/
 * vite-plugin-federation`'s, `@module-federation/vite`'s) exposes on a
 * remote's own entry module:
 *
 * ```
 * export function init(sharedScope): Promise<void>   // registers the host's shared deps
 * export function get(exposedName): Promise<() => Module>  // resolves to a *factory* for the exposed module
 * ```
 *
 * A real Module Federation build produces exactly this shape (wrapped in a
 * great deal of dependency-version-negotiation machinery this hand-rolled
 * version does not attempt to replicate — see "Known limitations" below).
 * Because the *contract* matches, swapping this loader over to call a real
 * federation runtime's own dynamic-remote APIs later (`__federation_
 * method_setRemote`/`__federation_method_getRemote`, in `@originjs/
 * vite-plugin-federation`'s case) is a change to this one file only — no
 * change to `useFederatedModules`, `buildModuleRoutes.tsx`, `OrgAdminPage.
 * tsx`, or the backend manifest shape. See `docs/modules.md`'s "Tier C"
 * section for the exact recommended upgrade path once a deployment building
 * this repo has normal network access.
 *
 * **Known limitations of the hand-rolled shared scope, spelled out rather
 * than silently glossed over**: a real Module Federation runtime negotiates
 * shared-dependency *versions* across host and every remote (e.g. warning
 * or refusing to share React 17 with a remote that needs React 19). This
 * hand-rolled scope is a single, unversioned singleton — `window.
 * __RTM_FEDERATED_SHARED_SCOPE__` — carrying whatever React/ReactDOM
 * instances this host bundle happens to have loaded. A real deployment
 * enabling this mechanism accepts that a Tier C remote must be built
 * against a React version compatible with the host's own (documented in
 * the module-author guide), with no automated compatibility check standing
 * behind that expectation the way a real federation runtime's negotiation
 * would provide.
 */

/** The shape every Tier C remote entry module must export — see this
 * file's own docstring for why this mirrors real Module Federation's own
 * container contract deliberately, rather than inventing an unrelated one. */
interface FederationContainer {
  init(sharedScope: FederatedSharedScope): Promise<void> | void;
  get(exposedModuleName: string): Promise<() => { moduleDefinition?: TierAModuleDefinition }>;
}

/** The host's own shared-dependency singleton a Tier C remote reads from
 * instead of bundling its own copy — see this file's own docstring's
 * "Known limitations" for why this is a plain singleton, not a real
 * negotiated shared scope. Exposed on `window` (not just as an in-memory
 * module-level object) because a remote entry is a genuinely separate ES
 * module graph, loaded via a runtime `import()` of a URL outside this
 * bundle's own module graph — the two module graphs share nothing except
 * the one JS realm (`window`) they both execute in. */
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

/** Subscribes to every Tier C load-status change (any module, any status) —
 * `useFederatedModules` uses this to force its owning component to
 * re-render once a load settles, since mutating `installedModules`/this
 * module's own `statuses` map is otherwise invisible to React. Returns an
 * unsubscribe function. */
export function subscribeFederatedLoader(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current load status of `moduleKey`'s Tier C module, or `undefined`
 * if no load has ever been attempted for it this session. */
export function getFederatedLoadStatus(moduleKey: string): FederatedLoadStatus | undefined {
  return statuses.get(moduleKey);
}

/** The error message from `moduleKey`'s most recent failed load attempt, if
 * its current status is `"failed"` — `undefined` otherwise. Surfaced so a
 * failed-state UI (Storybook coverage; a future admin-facing banner) can
 * show *why*, not just that it failed. */
export function getFederatedLoadError(moduleKey: string): string | undefined {
  return errors.get(moduleKey);
}

/** Resets every in-memory Tier C loader state — test-only. Production code
 * never calls this: a load, once successful, stays merged into
 * `installedModules` for the lifetime of the page, the same as a
 * build-time-discovered module never un-registers itself. */
export function _resetFederatedLoaderStateForTests(): void {
  statuses.clear();
  inFlight.clear();
  errors.clear();
  listeners.clear();
}

/**
 * Dynamically loads `moduleKey`'s Tier C remote entry (per `manifest.
 * remote_entry_url`/`.exposed_module`) and, on success, merges the result
 * into the real `installedModules` array (`registry.ts`) — the same array
 * Tier A's build-time `import.meta.glob` discovery populates, so every
 * existing consumer needs no Tier-C-specific branch of its own (this file's
 * own docstring explains why this is the whole point of the design).
 *
 * Idempotent and safe to call repeatedly/concurrently for the same
 * `moduleKey`: a module already present in `installedModules` (a previous
 * successful load, this session) resolves immediately without re-fetching;
 * an in-flight load is awaited rather than duplicated.
 *
 * Never throws — a failure (network error, malformed remote, a
 * `moduleDefinition.key` mismatch) is logged via `console.error` and
 * recorded as this module's `"failed"` status (readable via `getFederated
 * LoadError`), mirroring this codebase's established "log and exclude,
 * don't crash the page over one module's own bug" convention
 * (`app.modules.registry`'s own per-module fault isolation on the backend).
 *
 * @param moduleKey - The module's registry key (`ModuleNavEntry.module_key`
 *   / `OrgModule.module_key`) — must match the `key` the loaded remote's own
 *   `moduleDefinition.key` declares, or the load is rejected (a module
 *   cannot silently register itself under a different key than the backend
 *   declared for it).
 * @param manifest - The module's `ModuleFrontendManifest`; a no-op
 *   (resolves `null`) if `manifest.tier !== "federated"`.
 * @returns The loaded `TierAModuleDefinition`, or `null` on failure or a
 *   non-federated manifest.
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
        // Normalised to the plain module object either way (`react`/
        // `react-dom` are CJS-authored packages; Vite's dependency
        // pre-bundling gives every named export both directly on the
        // namespace object *and* via a synthetic `.default`) — a Tier C
        // remote's own code reads `sharedScope.react.createElement` etc.
        // without needing to know or care which form its own bundler
        // would have produced.
        react: (reactModule as { default?: unknown }).default ?? reactModule,
        "react-dom": (reactDomModule as { default?: unknown }).default ?? reactDomModule,
      };
      window.__RTM_FEDERATED_SHARED_SCOPE__ = sharedScope;

      // `remoteEntryUrl` is a runtime value (from the backend's manifest,
      // not known at build time) — this is exactly the case Vite's own
      // docs call out `/* @vite-ignore */` for: a dynamic import specifier
      // Vite's static analysis cannot (and must not try to) resolve
      // against this bundle's own module graph, since the whole point of
      // Tier C is loading a module that was never part of it.
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
