import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgFutureStatesPanel } from "./OrgFutureStatesPanel";
import type { FutureState } from "./types";

const ORG_ID = "org-1";

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: "future-state-1", scope: "organization", organization_id: ORG_ID, project_id: null, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
    current_state: "", desired_state: "We are the top provider in our region.", target_date: "2028-06-30",
    outcomes: "", success_measures: "", constraints: "", assumptions: "",
    status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPanelApis(futureStates: FutureState[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/modules/context_strategy/future-states`)) return futureStates;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgFutureStatesPanel> = {
  title: "Modules/ContextStrategy/OrgFutureStatesPanel",
  component: OrgFutureStatesPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgFutureStatesPanel>;

export const ListsOrgFutureStates: Story = {
  beforeEach: () => mockPanelApis([futureState(), futureState({ id: "future-state-2", title: "Diversified supply base", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Regional #1 by 2028")).toBeInTheDocument());
    await expect(canvas.getByText("Diversified supply base")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No organisation-scoped Future State recorded yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Future State" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Future State" }));
    await expect(within(document.body).getByRole("heading", { name: "New Future State (organisation)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOrgFutureStates };
export const DarkTheme: Story = { ...ListsOrgFutureStates, globals: { theme: "dark" } };
