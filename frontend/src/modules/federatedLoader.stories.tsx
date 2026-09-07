import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import type { ModuleFrontendManifest } from "../api/types";
import { useFederatedModules } from "../hooks/useFederatedModules";
// `?raw` (a Vite-specific import-suffix convention) imports this fixture's
// own *source text*, not its executed module — the fixture is never part
// of this app's own static module graph (nothing else `import`s it
// normally). The "Loaded" story below turns that text into a `Blob`/object
// URL and dynamically `import()`s *that* — a real, separate, out-of-graph
// module load, proving `federatedLoader.ts`'s actual runtime mechanism
// rather than merely asserting its code compiles. See that fixture file's
// own header comment for the full rationale.
import federatedFixtureSource from "./__fixtures__/federatedRemoteEntryFixture.js?raw";
import { getInstalledModule } from "./registry";

/**
 * Storybook coverage for the Tier C ("federated"/Module Federation) runtime
 * loader (module system follow-up, 2026-09-07) — see `federatedLoader.ts`'s
 * own docstring for the full mechanism and its documented deviation from
 * the originally-specified `@originjs/vite-plugin-federation` dependency
 * (no network access to the npm registry in this repo's own sandboxed
 * build/test environment; a hand-rolled but contract-compatible substitute
 * was built and is exercised for real here instead).
 *
 * Mirrors this codebase's existing convention for module-system
 * infrastructure with no real third-party module to exercise yet
 * (`App.stories.tsx`'s `TierARoutingHarness`, `ModuleFrame.stories.tsx`):
 * a small harness renders `useFederatedModules`'s own status output plus
 * whatever the loaded module's own route element renders, proving the full
 * loading → merged-into-`installedModules` → rendered pipeline end to end.
 */
function FederatedLoaderHarness({ moduleKey, manifest }: { moduleKey: string; manifest: ModuleFrontendManifest | null }) {
  const states = useFederatedModules(manifest ? [{ module_key: moduleKey, frontend_manifest: manifest }] : []);
  const state = states[moduleKey];
  const loaded = getInstalledModule(moduleKey);
  const routeElement = loaded?.routes?.[0]?.element;

  return (
    <div>
      <p data-testid="loader-status">{state ? state.status : "disabled"}</p>
      {state?.status === "failed" && <p data-testid="loader-error">{state.error}</p>}
      {routeElement && <div data-testid="loaded-route">{routeElement}</div>}
    </div>
  );
}

const meta: Meta<typeof FederatedLoaderHarness> = {
  title: "Modules/FederatedLoader (Tier C)",
  component: FederatedLoaderHarness,
};
export default meta;
type Story = StoryObj<typeof FederatedLoaderHarness>;

// --- Loaded: a real, separate remote entry, genuinely dynamically imported ---

const loadedFixtureUrl = URL.createObjectURL(new Blob([federatedFixtureSource], { type: "text/javascript" }));

export const Loaded: Story = {
  args: {
    moduleKey: "federated_fixture_module",
    manifest: {
      tier: "federated", nav_label: "Federated Fixture", nav_path: "/federated-fixture",
      frame_url: null, remote_entry_url: loadedFixtureUrl, exposed_module: "./Module",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("loader-status")).toHaveTextContent("loaded"));
    // Proves two things at once: (1) the real remote entry file was
    // dynamically imported and its exposed module resolved, and (2) the
    // element it rendered used the *host's* own `react.createElement` (via
    // the shared scope `federatedLoader.ts` hands it) — a duplicate,
    // isolated React copy would still render this text (React's `disable`
    // safeguards aren't what's being tested here), so the real proof is
    // architectural (traced in the fixture/loader source), but a failure
    // to reach this text at all would mean the shared-scope handoff itself
    // is broken (`sharedScope.react` was `undefined`, e.g.).
    await expect(canvas.getByTestId("loaded-route")).toHaveTextContent(
      "Federated fixture module loaded, sharing the host's own React instance."
    );
  },
};

// --- Loading: an artificial delay proves the interim state renders --------

const delayedFixtureSource = `
let shared = null;
export function init(sharedScope) { shared = sharedScope; return Promise.resolve(); }
export function get(name) {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve(() => ({
        moduleDefinition: {
          key: "federated_delayed_fixture_module",
          routes: [{ path: "/federated-delayed", element: shared.react.createElement("div", null, "delayed") }],
        },
      }));
    }, 300);
  });
}
`;
const delayedFixtureUrl = URL.createObjectURL(new Blob([delayedFixtureSource], { type: "text/javascript" }));

export const Loading: Story = {
  args: {
    moduleKey: "federated_delayed_fixture_module",
    manifest: {
      tier: "federated", nav_label: "Delayed Fixture", nav_path: "/federated-delayed",
      frame_url: null, remote_entry_url: delayedFixtureUrl, exposed_module: "./Module",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Asserted immediately (no `waitFor`) — the artificial 300ms delay in
    // the fixture's own `get()` above is what makes this reliably still
    // "loading" at first render, not a race against real network/parse
    // timing the way asserting this on the `Loaded` story's real file
    // would be.
    await expect(canvas.getByTestId("loader-status")).toHaveTextContent("loading");
    await waitFor(() => expect(canvas.getByTestId("loader-status")).toHaveTextContent("loaded"));
  },
};

// --- Failed: a remote that doesn't honour the container contract ----------

const brokenFixtureSource = `
export const notTheRightShape = true;
`;
const brokenFixtureUrl = URL.createObjectURL(new Blob([brokenFixtureSource], { type: "text/javascript" }));

export const Failed: Story = {
  args: {
    moduleKey: "federated_broken_fixture_module",
    manifest: {
      tier: "federated", nav_label: "Broken Fixture", nav_path: "/federated-broken",
      frame_url: null, remote_entry_url: brokenFixtureUrl, exposed_module: "./Module",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("loader-status")).toHaveTextContent("failed"));
    await expect(canvas.getByTestId("loader-error")).toHaveTextContent("does not export the required init()/get()");
  },
};

// --- Disabled: a non-federated (or absent) manifest triggers no load ------

export const Disabled: Story = {
  args: {
    moduleKey: "federated_never_loaded_module",
    manifest: null,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("loader-status")).toHaveTextContent("disabled");
    expect(getInstalledModule("federated_never_loaded_module")).toBeUndefined();
  },
};
