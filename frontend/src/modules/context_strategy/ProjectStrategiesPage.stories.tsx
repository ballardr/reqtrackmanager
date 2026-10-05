import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectStrategiesPage } from "./ProjectStrategiesPage";
import type { Strategy } from "./types";

const PROJECT_ID = "project-1";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "strategy-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
    objective: "Become the top provider in our region.", current_state: "", desired_future_state: "",
    rationale: "", expected_outcomes: "", constraints: "", measures_of_success: "", priority: "high",
    time_horizon: "long_term", status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(strategies: Strategy[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/strategies`)) return strategies;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectStrategiesPage> = {
  title: "Modules/ContextStrategy/ProjectStrategiesPage",
  component: ProjectStrategiesPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/context_strategy/strategies`, "/projects/:projectId/modules/context_strategy/strategies"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectStrategiesPage>;

export const ListsStrategies: Story = {
  beforeEach: () => mockPageApis([strategy(), strategy({ id: "strategy-2", title: "Modernise the delivery pipeline", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Lead the regional market")).toBeInTheDocument());
    await expect(canvas.getByText("Modernise the delivery pipeline")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Strategy recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Strategy" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Strategy" }));
    // `StrategyFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Strategy (project)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsStrategies };
export const DarkTheme: Story = { ...ListsStrategies, globals: { theme: "dark" } };
