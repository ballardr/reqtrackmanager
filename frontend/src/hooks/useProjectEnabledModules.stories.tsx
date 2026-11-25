import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import type { ModuleNavEntry } from "../api/types";
import { refreshProjectEnabledModules, useProjectEnabledModules } from "./useProjectEnabledModules";

/** Renders the hook's `loaded` and `modules` result as text, so a play function can exercise it. */
function Harness({ projectId }: { projectId: string }) {
  const { modules, loaded } = useProjectEnabledModules(projectId);
  return <div>{loaded ? `loaded:${modules.length}` : "loading"}</div>;
}

/** The same harness with `ready` starting `false` and a button to flip it, standing in for `App.tsx` passing
 * `!loading` as `ready`. */
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
 * A failed request (a transient 401) settles to `modules: [], loaded: true`; `App.tsx`'s project-scoped wildcard
 * route waits on `loaded`, so a flag that stayed `false` would leave a spinner on every module route.
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
 * With `ready` false no request is sent: passive effects run child before parent, so a fetch fired before
 * `AuthProvider` loads the stored token would carry no `Authorization` header and never be retried.
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

/** `refreshProjectEnabledModules(projectId)` re-fetches for that project only, without dropping back to
 * `loading`; a failed refresh keeps the list already shown. */
export const RefreshesWhenToldAndKeepsTheListOnFailure: Story = {
  beforeEach: () => {
    let calls = 0;
    spyOn(api, "get").mockImplementation(async () => {
      calls += 1;
      if (calls === 1) return [];
      if (calls === 2) return FIXTURE_MODULES;
      throw new ApiError(500, "Transient failure.");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("loaded:0")).toBeInTheDocument());

    refreshProjectEnabledModules("another-project");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(api.get).toHaveBeenCalledTimes(1);

    refreshProjectEnabledModules("proj-1");
    await waitFor(() => expect(canvas.getByText("loaded:1")).toBeInTheDocument());

    refreshProjectEnabledModules("proj-1");
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    await expect(canvas.getByText("loaded:1")).toBeInTheDocument();
  },
};
