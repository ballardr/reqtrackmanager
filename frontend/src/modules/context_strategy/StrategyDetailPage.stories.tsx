import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { StrategyDetailPage } from "./StrategyDetailPage";
import type { Strategy } from "./types";

const PROJECT_ID = "project-1";
const STRATEGY_ID = "strategy-1";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: STRATEGY_ID, scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
    objective: "Become the top provider in our region.", current_state: "We are #3 in the region.",
    desired_future_state: "We are #1 in the region.", rationale: "Market analysis shows a clear opening.",
    expected_outcomes: "Revenue up 20%.", constraints: "Limited hiring budget.", measures_of_success: "Market share.",
    priority: "high", time_horizon: "long_term", status: "under_review", version_number: 2, is_locked: false,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockDetailApis(current: Strategy) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/strategies/${STRATEGY_ID}`)) return current;
    if (path.endsWith("/versions")) return [];
    if (path.includes("/comments")) return [];
    if (path.includes("/files")) return [];
    if (path.includes("/relationships")) return [];
    if (path.endsWith("/requirements")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/**
 * A real routed page — stories go through `withRouter`/`withAuth` rather
 * than passing props directly, mirroring `modules/decisions/
 * DecisionDetailPage.stories.tsx`'s own identical convention.
 */
const meta: Meta<typeof StrategyDetailPage> = {
  title: "Modules/ContextStrategy/StrategyDetailPage",
  component: StrategyDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/context_strategy/strategies/${STRATEGY_ID}`,
      "/projects/:projectId/modules/context_strategy/strategies/:strategyId"
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof StrategyDetailPage>;

export const UnderReviewShowsApproveAndSendBack: Story = {
  beforeEach: () => mockDetailApis(strategy()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Lead the regional market" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Send back" })).toBeInTheDocument();
  },
};

export const DraftShowsPropose: Story = {
  beforeEach: () => mockDetailApis(strategy({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Propose" })).toBeInTheDocument());
  },
};

export const ActiveShowsSupersedeAndRetire: Story = {
  beforeEach: () => mockDetailApis(strategy({ status: "active", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Supersede" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/new attachments can no longer be added/)).toBeInTheDocument();
  },
};

export const SendBackRequiresComment: Story = {
  beforeEach: () => mockDetailApis(strategy()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Send back" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send back" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Send this Strategy back to Draft?" }));
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Send-back comment"), "Needs a stronger market analysis first.");
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeEnabled();
  },
};

export const ApproveStrategy: Story = {
  beforeEach: () => {
    mockDetailApis(strategy());
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/approve")) return strategy({ status: "approved" });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Approve" }));
    await userEvent.click(canvas.getByRole("button", { name: "Approve" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Approve this Strategy?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/strategies/${STRATEGY_ID}/approve`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Approved")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...UnderReviewShowsApproveAndSendBack };
export const DarkTheme: Story = { ...UnderReviewShowsApproveAndSendBack, globals: { theme: "dark" } };
