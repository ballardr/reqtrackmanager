// Fixture: a plain-JS Tier C ("federated") remote entry module. It implements the minimal Module Federation
// container contract (`init(sharedScope)` / `get(exposedModuleName)`) that `federatedLoader.ts` consumes, so the
// host's runtime `import()` and shared-scope loading is exercised without a Module Federation build step
// (`docs/modules.md`, "Tier C: module-author guide", describes a real remote's build).
//
// It is plain JavaScript, not TypeScript or JSX: `react.createElement` is called directly, as compiled JSX expands.
//
// Nothing in `src/` imports it with a normal specifier; `federatedLoader.stories.tsx` imports it with `?raw` and
// builds a Blob URL from the source, which proves a URL outside Vite's static module graph loads at runtime. It
// never ships in the production bundle.

let hostSharedScope = null;

/** Every Tier C remote exports this (`FederationContainer` in `federatedLoader.ts`). Records the host's shared
 * dependency scope (`{react, "react-dom"}`) so the rendered element uses the host's React instance. */
export function init(sharedScope) {
  hostSharedScope = sharedScope;
  return Promise.resolve();
}

/** Every Tier C remote exports this; it resolves to a factory function (`federatedLoader.ts` calls `factory()`
 * after awaiting it), as Module Federation's container contract does. Only `"./Module"` is exposed, matching the
 * manifest in `federatedLoader.stories.tsx`. */
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
