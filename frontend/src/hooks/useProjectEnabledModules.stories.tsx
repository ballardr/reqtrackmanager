import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import type { ModuleNavEntry } from "../api/types";
import { useProjectEnabledModules } from "./useProjectEnabledModules";

/** Renders the hook's own `loaded`/`modules` result as text — the hook has
 * no UI of its own, so this is the thinnest possible harness for exercising
 * it through Storybook's component/play-function convention (this codebase
 * has no `renderHook`-style hook-testing infra). */
function Harness({ projectId }: { projectId: string }) {
  const { modules, loaded } = useProjectEnabledModules(projectId);
  return <div>{loaded ? `loaded:${modules.length}` : "loading"}</div>;
}

/** Same harness, but with `ready` starting `false` and a button to flip it —
 * stands in for `App.tsx` passing `!loading` (`AuthProvider`'s own auth
 * state) as `ready`, so the "not ready yet" -> "ready" transition can be
 * driven from a `play` function without needing `AuthProvider` itself. */
function ReadyGateHarness({ projectId }: { projectId: string }) {
  const [ready, setReady] = useState(false);
  const { modules, loaded } = useProjectEnabledModules(projectId, ready);
  return (
    <div>
      <button onClick={() => setReady(true)}>Become ready</button>
      <div>{loaded ? `loaded:${modules.length}` : "loading"}</div>
    </div>
  );
}

const FIXTURE_MODULES: ModuleNavEntry[] = [
  {
    module_key: "compliance", name: "Compliance",
    frontend_manifest: {
      tier: "installed", nav_label: "Compliance", nav_path: "/projects/{project_id}/modules/compliance",
      frame_url: null, remote_entry_url: null, exposed_module: null,
    },
  },
];

const meta: Meta<typeof Harness> = {
  title: "Hooks/useProjectEnabledModules",
  component: Harness,
  args: { projectId: "proj-1" },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ResolvesLoadedOnSuccess: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => FIXTURE_MODULES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("loaded:1")).toBeInTheDocument());
  },
};

/**
 * Regression test for a real bug (found 2026-09-15 while documenting the
 * Modules section): this hook's fetch had no `.catch`, so a failed request
 * (a transient 401, here) left `loaded` `false` forever instead of settling.
 * `App.tsx`'s project-scoped wildcard route holds on a spinner specifically
 * until `loaded` flips (see that file's own comment at the wildcard route),
 * so the one failure produced a permanently stuck spinner on every module
 * route for that project, with no retry short of luck on a later reload.
 * The fix falls back to `modules: [], loaded: true` on failure — the same
 * safe default already returned while the fetch is in flight.
 */
export const ResolvesLoadedEvenWhenTheFetchFails: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => {
      throw new ApiError(401, "Could not validate credentials.");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("loaded:0")).toBeInTheDocument());
  },
};

/**
 * Regression test for a second, structural bug found the same session:
 * `App.tsx`'s `ProtectedRoutes` must call this hook unconditionally, before
 * its own `if (loading) return <Spinner />` early return (Rules of Hooks) —
 * but React fires a commit's passive effects child-before-parent, so on a
 * fresh app boot this hook's effect (a descendant of `AuthProvider`) could
 * fire, and dispatch its fetch, *before* `AuthProvider`'s own effect had
 * called `loadStoredToken()`. That request went out with no `Authorization`
 * header, 401ed, and — because `projectId` never changes again for the rest
 * of that project visit — the hook never got a second chance: every Tier A
 * module's nav entry/route stayed hidden for that project for the whole
 * session. `ready` fixes this by not firing the effect at all until the
 * caller says authentication is actually settled.
 */
export const DoesNotFetchUntilReady: Story = {
  render: () => <ReadyGateHarness projectId="proj-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => FIXTURE_MODULES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("loading")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();

    await userEvent.click(canvas.getByRole("button", { name: "Become ready" }));
    await waitFor(() => expect(canvas.getByText("loaded:1")).toBeInTheDocument());
  },
};
