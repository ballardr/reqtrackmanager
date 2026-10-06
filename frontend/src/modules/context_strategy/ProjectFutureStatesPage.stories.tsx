import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectFutureStatesPage } from "./ProjectFutureStatesPage";
import type { FutureState } from "./types";

const PROJECT_ID = "project-1";
const daysFromNow = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: "fs-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Certified for populated corridors",
    current_state: "Test routes only.", desired_state: "Certified.", target_date: daysFromNow(200), outcomes: "",
    success_measures: "Certification date", constraints: "", assumptions: "", status: "active", version_number: 1,
    is_locked: false, created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(states: FutureState[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/future-states`)) return states;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const STATES = [
  futureState({ id: "ok", title: "On track" }),
  futureState({ id: "missed", title: "Missed target", status: "draft", target_date: daysFromNow(-45), success_measures: "" }),
  futureState({ id: "active-past", title: "Active past its date", status: "active", target_date: daysFromNow(-10) }),
  futureState({ id: "retired", title: "Retired vision", status: "retired", target_date: daysFromNow(-90), success_measures: "" }),
];

const meta: Meta<typeof ProjectFutureStatesPage> = {
  title: "Modules/ContextStrategy/ProjectFutureStatesPage",
  component: ProjectFutureStatesPage,
  decorators: [
    // `parameters.query` opens the page the way a report figure's link does (`?roadmap=1&target_passed=1`).
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/context_strategy/future-states${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/context_strategy/future-states",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectFutureStatesPage>;

export const ListsFutureStates: Story = {
  beforeEach: () => mockPageApis(STATES),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("On track")).toBeInTheDocument());
  },
};

/** The report's "Target date passed": still expected, date passed, and not yet Active (an Active one is excluded). */
export const OpensTargetDatePassedFromAReportFigure: Story = {
  parameters: { query: "?roadmap=1&target_passed=1" },
  beforeEach: () => mockPageApis(STATES),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Missed target")).toBeInTheDocument());
    await expect(canvas.queryByText("On track")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Active past its date")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Retired vision")).not.toBeInTheDocument(); // off the roadmap
    await expect(canvas.getByRole("checkbox", { name: "Target date passed" })).toBeChecked();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Target date passed" }));
    await expect(canvas.getByText("On track")).toBeInTheDocument();
  },
};

/** The report's "Without success measures". */
export const OpensWithoutSuccessMeasuresFromAReportFigure: Story = {
  parameters: { query: "?roadmap=1&no_measures=1" },
  beforeEach: () => mockPageApis(STATES),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Missed target")).toBeInTheDocument());
    await expect(canvas.queryByText("On track")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Retired vision")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Without success measures" })).toBeChecked();
  },
};
