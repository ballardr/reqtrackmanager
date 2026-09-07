// Fixture: a hand-authored Tier C ("federated") remote entry module —
// module system follow-up, 2026-09-07 (Module Federation). See
// `frontend/src/modules/federatedLoader.ts`'s own docstring for why this is
// hand-authored plain JS rather than the output of a real Module Federation
// build: this repository's own sandboxed build/test environment had no
// network access to install `@originjs/vite-plugin-federation` (or an
// equivalent) when this was built, so a real module author's build tool
// could not be exercised here. This file instead implements, directly and
// by hand, the exact minimal container contract (`init(sharedScope)` /
// `get(exposedModuleName)`) `federatedLoader.ts` consumes — the same
// contract a real Module Federation remote build produces — so it proves
// the *host's* dynamic-import/shared-scope loading mechanism for real
// (genuinely loaded via a runtime `import()` of a URL outside this bundle's
// own module graph, in a real browser, in `federatedLoader.stories.tsx`),
// even though this specific file's own authoring process differs from what
// a production Tier C module author would use (see `docs/modules.md`'s
// "Tier C: module-author guide" for that real, recommended build process).
//
// Deliberately plain JavaScript, not TypeScript/JSX: a real remote's own
// build step would compile its JSX/TS away into exactly this shape before
// shipping a `remoteEntry.js` — this fixture just skips needing a build
// step for something this small, by never using JSX/TS syntax in the first
// place. `react.createElement` is called directly instead, exactly the way
// compiled JSX itself expands to.
//
// Not part of this app's own module graph: nothing in `src/` imports this
// file via a normal `import` specifier (only `?raw`, from
// `federatedLoader.stories.tsx`, to obtain its source text and construct a
// Blob URL from it — that's the whole point of the test: proving a URL
// *outside* Vite's own static module graph can be loaded at runtime the
// same way a real deployment's `/external-modules/.../remoteEntry.js`
// would be). It therefore never ships into this app's own production
// bundle.

let hostSharedScope = null;

/** Every Tier C remote must export this — see `federatedLoader.ts`'s own
 * `FederationContainer` interface. Records the host's shared dependency
 * scope (here: just `{react, "react-dom"}`) for `get()` to read from below,
 * so this fixture's own rendered element uses the *host's* React instance
 * rather than bundling (or, here, simply omitting) its own. */
export function init(sharedScope) {
  hostSharedScope = sharedScope;
  return Promise.resolve();
}

/** Every Tier C remote must export this — resolves to a *factory function*
 * (not the module directly), mirroring real Module Federation's own
 * container contract exactly (`federatedLoader.ts` calls `factory()` after
 * awaiting this). Only one exposed module is published, `"./Module"`,
 * matching this fixture's own manifest declaration in
 * `federatedLoader.stories.tsx`. */
export function get(exposedModuleName) {
  if (exposedModuleName !== "./Module") {
    return Promise.reject(new Error(`federatedRemoteEntryFixture has no exposed module "${exposedModuleName}"`));
  }
  return Promise.resolve(function moduleFactory() {
    const react = hostSharedScope && hostSharedScope.react;
    return {
      moduleDefinition: {
        key: "federated_fixture_module",
        routes: [
          {
            path: "/federated-fixture",
            element: react
              ? react.createElement(
                  "div",
                  { "data-testid": "federated-fixture-route" },
                  "Federated fixture module loaded, sharing the host's own React instance."
                )
              : null,
          },
        ],
        orgAdminSections: [
          {
            key: "federated-fixture-admin",
            label: "Federated Fixture",
            render: () =>
              react
                ? react.createElement(
                    "div",
                    { "data-testid": "federated-fixture-admin-section" },
                    "Federated fixture org-admin section"
                  )
                : null,
          },
        ],
      },
    };
  });
}
