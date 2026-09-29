import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectFutureStatesPage } from "./ProjectFutureStatesPage";
import type { FutureState } from "./types";

const PROJECT_ID = "project-1";

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: "future-state-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
    current_state: "", desired_state: "We are the top provider in our region.", target_date: "2028-06-30",
    outcomes: "", success_measures: "", constraints: "", assumptions: "",
    status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(futureStates: FutureState[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/future-states`)) return futureStates;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectFutureStatesPage> = {
  title: "Modules/ContextStrategy/ProjectFutureStatesPage",
  component: ProjectFutureStatesPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/context_strategy/future-states`, "/projects/:projectId/modules/context_strategy/future-states"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectFutureStatesPage>;

export const ListsFutureStates: Story = {
  beforeEach: () => mockPageApis([futureState(), futureState({ id: "future-state-2", title: "Zero paper re-keying", status: "draft", target_date: null })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Regional #1 by 2028")).toBeInTheDocument());
    await expect(canvas.getByText("Zero paper re-keying")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Future State recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Future State" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Future State" }));
    // `FutureStateFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Future State (project)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsFutureStates };
export const DarkTheme: Story = { ...ListsFutureStates, globals: { theme: "dark" } };
