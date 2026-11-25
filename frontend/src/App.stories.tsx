import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { ModuleNavEntry } from "./api/types";
import { useToast } from "./context/ToastContext";
import { buildModuleRoutes } from "./modules/buildModuleRoutes";
import { installedModules } from "./modules/registry";
import { withToast } from "./testing/storybook-helpers";

const FIXTURE_MODULE_KEY = "fake_tier_a_fixture_module";

/**
 * A minimal Tier A module page that proves the mechanism, as `backend/tests/test_module_registry.py`'s
 * `fake_module` does for the backend registry. It calls the real `useToast()`: an installed module's route
 * components are compiled into this bundle and use every shared component and context as a first-party page does
 * (Tier B, `<ModuleFrame>`, is covered in `ModuleFrame.stories.tsx`).
 */
function FixtureTierAModulePage() {
  const { showToast } = useToast();
  return (
    <div>
      <h1>Fixture Tier A Module</h1>
      <button className="btn" onClick={() => showToast("Fixture module action succeeded")}>
        Do something
      </button>
    </div>
  );
}

// Registered once at module scope, as OrgAdminPage.stories.tsx's `entitledEnabledModule` is, not per story:
// only `App.tsx`'s route building and `Layout.tsx`'s nav rendering read `installedModules`, and no other story
// file exercises them, so a permanent fixture entry interferes with nothing.
installedModules.push({
  key: FIXTURE_MODULE_KEY,
  routes: [{ path: "/projects/:projectId/modules/fixture", element: <FixtureTierAModulePage /> }],
});

const enabledModules: ModuleNavEntry[] = [
  {
    module_key: FIXTURE_MODULE_KEY, name: "Fixture Module",
    frontend_manifest: {
      tier: "installed", nav_label: "Fixture Module", nav_path: "/projects/:projectId/modules/fixture",
      frame_url: null, remote_entry_url: null, exposed_module: null,
    },
  },
];

/** Harness reproducing what `ProtectedRoutes` does with `buildModuleRoutes`'s output: a `MemoryRouter` matching
 * the fixture module's path, spliced in as real enabled modules are. */
function TierARoutingHarness() {
  return (
    <MemoryRouter initialEntries={["/projects/proj-1/modules/fixture"]}>
      <Routes>
        {buildModuleRoutes(enabledModules, "proj-1")}
        <Route path="*" element={<div>No route matched</div>} />
      </Routes>
    </MemoryRouter>
  );
}

const meta: Meta<typeof TierARoutingHarness> = {
  title: "Modules/Tier A Routing",
  component: TierARoutingHarness,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof TierARoutingHarness>;

/** A Tier A module registered in `frontend/src/modules/registry.ts` and listed as enabled by the backend renders
 * its own route component (part of this bundle, not loaded dynamically), and its use of a shared context
 * (`useToast()`) works as on a first-party page. */
export const RendersInstalledModuleRouteWithRealSharedComponents: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Fixture Tier A Module" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Do something" }));
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Fixture module action succeeded")).toBeInTheDocument());
  },
};

/** A module with no matching `getInstalledModule` entry (a Tier B manifest, or an `enabledModules` entry naming a
 * module not registered on the frontend) contributes no route and never crashes. */
export const ContributesNoRouteWhenNotRegisteredOnTheFrontend: Story = {
  render: () => (
    <MemoryRouter initialEntries={["/projects/proj-1/modules/fixture"]}>
      <Routes>
        {buildModuleRoutes(
          [{ module_key: "not_actually_installed", name: "Ghost Module", frontend_manifest: null }],
          "proj-1"
        )}
        <Route path="*" element={<div>No route matched</div>} />
      </Routes>
    </MemoryRouter>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No route matched")).toBeInTheDocument();
  },
};
