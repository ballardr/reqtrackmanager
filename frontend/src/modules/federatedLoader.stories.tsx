import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import type { ModuleFrontendManifest } from "../api/types";
import { useFederatedModules } from "../hooks/useFederatedModules";
// `?raw` imports the fixture's source text, not its executed module, so the fixture stays outside the static module
// graph. The "Loaded" story turns that text into a `Blob` object URL and dynamically `import()`s it, a separate
// out-of-graph module load that exercises `federatedLoader.ts`'s runtime mechanism (see the fixture's header).
import federatedFixtureSource from "./__fixtures__/federatedRemoteEntryFixture.js?raw";
import { getInstalledModule } from "./registry";

/**
 * Storybook coverage for the Tier C (Module Federation) runtime loader (`federatedLoader.ts`, whose docstring covers
 * the mechanism and why it is a contract-compatible loader rather than a federation plugin). A harness renders
 * `useFederatedModules`'s status output plus the loaded module's route element, as `App.stories.tsx`'s
 * `TierARoutingHarness` and `ModuleFrame.stories.tsx` do, proving loading -> merged into `installedModules` -> rendered.
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
    // Proves the remote entry was dynamically imported and its exposed module resolved. A duplicate React copy would
    // still render this text, so the shared-scope handoff is verified by architecture (fixture and loader source);
    // failing to reach this text means the handoff itself is broken (`sharedScope.react` undefined, for example).
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
    // Asserted without `waitFor`: the fixture's artificial 300ms delay in `get()` keeps the status "loading" at first
    // render, unlike the real file in the `Loaded` story, whose timing is not controlled.
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
