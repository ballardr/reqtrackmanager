import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import type { Strategy } from "./types";

const ORG_ID = "org-1";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "strategy-1", scope: "organization", organization_id: ORG_ID, project_id: null, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
    objective: "Become the top provider in our region.", current_state: "", desired_future_state: "",
    rationale: "", expected_outcomes: "", constraints: "", measures_of_success: "", priority: "high",
    time_horizon: "long_term", status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPanelApis(strategies: Strategy[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/modules/context_strategy/strategies`)) return strategies;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgStrategiesPanel> = {
  title: "Modules/ContextStrategy/OrgStrategiesPanel",
  component: OrgStrategiesPanel,
  args: { orgId: ORG_ID },
  decorators: [withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgStrategiesPanel>;

export const ListsOrgStrategies: Story = {
  beforeEach: () => mockPanelApis([strategy(), strategy({ id: "strategy-2", title: "Diversify revenue streams", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Lead the regional market")).toBeInTheDocument());
    await expect(canvas.getByText("Diversify revenue streams")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No organisation-scoped Strategy recorded yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Strategy" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Strategy" }));
    await expect(within(document.body).getByRole("heading", { name: "New Strategy (organisation)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOrgStrategies };
export const DarkTheme: Story = { ...ListsOrgStrategies, globals: { theme: "dark" } };
