import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { FutureStateDetailPage } from "./FutureStateDetailPage";
import type { FutureState } from "./types";

const PROJECT_ID = "project-1";
const FUTURE_STATE_ID = "future-state-1";

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: FUTURE_STATE_ID, scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
    current_state: "We are #3 in the region.", desired_state: "We are #1 in the region.", target_date: "2028-06-30",
    outcomes: "Revenue up 20%.", success_measures: "Market share.", constraints: "Limited hiring budget.",
    assumptions: "Market conditions stay favourable.", status: "under_review", version_number: 2, is_locked: false,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockDetailApis(current: FutureState) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/future-states/${FUTURE_STATE_ID}`)) return current;
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
 * than passing props directly, mirroring `StrategyDetailPage.stories.tsx`'s
 * own identical convention.
 */
const meta: Meta<typeof FutureStateDetailPage> = {
  title: "Modules/ContextStrategy/FutureStateDetailPage",
  component: FutureStateDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/context_strategy/future-states/${FUTURE_STATE_ID}`,
      "/projects/:projectId/modules/context_strategy/future-states/:futureStateId"
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof FutureStateDetailPage>;

export const UnderReviewShowsApproveAndSendBack: Story = {
  beforeEach: () => mockDetailApis(futureState()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Regional #1 by 2028" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Send back" })).toBeInTheDocument();
    await expect(canvas.getByText(/Target date 2028-06-30/)).toBeInTheDocument();
  },
};

export const DraftShowsPropose: Story = {
  beforeEach: () => mockDetailApis(futureState({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Propose" })).toBeInTheDocument());
  },
};

export const ActiveShowsSupersedeAndRetire: Story = {
  beforeEach: () => mockDetailApis(futureState({ status: "active", is_locked: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Supersede" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/new attachments can no longer be added/)).toBeInTheDocument();
  },
};

export const NoTargetDateOmitsPrefix: Story = {
  beforeEach: () => mockDetailApis(futureState({ target_date: null })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Regional #1 by 2028" })).toBeInTheDocument());
    await expect(canvas.queryByText(/Target date/)).not.toBeInTheDocument();
  },
};

export const SendBackRequiresComment: Story = {
  beforeEach: () => mockDetailApis(futureState()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Send back" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send back" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Send this Future State back to Draft?" }));
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Send-back comment"), "Needs a firmer target date first.");
    await expect(dialog.getByRole("button", { name: "Send back" })).toBeEnabled();
  },
};

export const ApproveFutureState: Story = {
  beforeEach: () => {
    mockDetailApis(futureState());
    spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/approve")) return futureState({ status: "approved" });
      throw new Error(`Unmocked POST: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Approve" }));
    await userEvent.click(canvas.getByRole("button", { name: "Approve" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Approve this Future State?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/future-states/${FUTURE_STATE_ID}/approve`,
      { comment: null }
    ));
    await waitFor(() => expect(canvas.getByText("Approved")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...UnderReviewShowsApproveAndSendBack };
export const DarkTheme: Story = { ...UnderReviewShowsApproveAndSendBack, globals: { theme: "dark" } };
