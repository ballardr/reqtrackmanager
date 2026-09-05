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
 * A minimal Tier A module page (compliance-module-plan.md Phase 3) —
 * exists only to prove the mechanism, the same way `backend/tests/
 * test_module_registry.py`'s `fake_module` proves the backend registry
 * without a real module existing yet (none does until Phase 12 registers
 * Compliance's own frontend here). Deliberately calls the real `useToast()`
 * — the whole point of Tier A is that an installed module's route
 * components are compiled directly into this bundle and can use every real
 * shared component/context exactly like a first-party page, not a
 * lookalike rendered behind an iframe boundary (that's Tier B,
 * `<ModuleFrame>`, covered separately in `ModuleFrame.stories.tsx`).
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

// Registered once, at module scope — mirrors this codebase's existing
// Storybook fixture convention (e.g. OrgAdminPage.stories.tsx's module-
// scope `entitledEnabledModule` constant) rather than a per-story
// beforeEach/cleanup pair: nothing else in this codebase reads
// `installedModules` except `App.tsx`'s own route-building and
// `Layout.tsx`'s nav rendering, neither of which any *other* story file
// exercises, so a permanently-registered fixture here causes no
// cross-file interference — unlike the backend's `INSTALLED_MODULES`
// (server-wide RBAC/registry state many backend tests read), there is
// nothing here for a leaked entry to corrupt.
installedModules.push({
  key: FIXTURE_MODULE_KEY,
  routes: [{ path: "/projects/:projectId/modules/fixture", element: <FixtureTierAModulePage /> }],
});

const enabledModules: ModuleNavEntry[] = [
  {
    module_key: FIXTURE_MODULE_KEY, name: "Fixture Module",
    frontend_manifest: {
      tier: "installed", nav_label: "Fixture Module", nav_path: "/projects/:projectId/modules/fixture",
      frame_url: null,
    },
  },
];

/** Harness reproducing exactly what `ProtectedRoutes` does with
 * `buildModuleRoutes`'s output — a `MemoryRouter` matching the fixture
 * module's own registered path, spliced in the same way real enabled
 * modules are. */
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

/** A Tier A module registered in `frontend/src/modules/registry.ts` and
 * listed as enabled by the backend renders its own route component —
 * genuinely part of this bundle, not fetched/loaded dynamically — and that
 * component's use of a real shared context (`useToast()`) works exactly
 * like it would on any first-party page. */
export const RendersInstalledModuleRouteWithRealSharedComponents: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Fixture Tier A Module" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Do something" }));
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Fixture module action succeeded")).toBeInTheDocument());
  },
};

/** A module with no matching `getInstalledModule` entry (e.g. a Tier B
 * manifest, or a stale `enabledModules` entry naming a module never
 * registered on the frontend) contributes no route at all — never a
 * crash. */
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
