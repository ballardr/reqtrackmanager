import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildRequest, buildRequestScheme, buildUnscoredRequest, ORG_USERS, PROJECT_ID } from "./requestFixtures";
import { ProjectRequestsPage } from "./ProjectRequestsPage";
import type { EnhancementRequest, FeedbackAccess } from "./types";

const REQUESTS: EnhancementRequest[] = [
  buildRequest(),
  buildUnscoredRequest(),
  buildRequest({
    id: "request-3", unique_code: "ENH-003", title: "Bulk edit", status: "accepted", pain_point_count: 2, requester_count: 3,
    weighted_demand: 7.5, loop_open_count: 0,
  }),
  buildRequest({ id: "request-4", unique_code: "ENH-004", title: "Old idea", status: "delivered", pain_point_count: 1, loop_open_count: 2 }),
  buildRequest({
    id: "request-5", unique_code: "ENH-005", title: "Excel please", status: "duplicate", allowed_next_statuses: [],
    merged_into: { id: "request-1", unique_code: "ENH-001", title: "Export" },
  }),
];

function mockApis(requests: EnhancementRequest[] = REQUESTS, access: FeedbackAccess = { can_submit: true, can_triage: false }) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/enhancement_request/columns")) return buildRecordColumns({ label: "Enhancement requests" });
    if (path.includes("/scoring-schemes/enhancement_request")) return buildRequestScheme();
    if (path.endsWith("/product_feedback/access")) return access;
    if (path.split("?")[0].endsWith("/modules/product_feedback/requests")) return requests;
    if (path.includes("/users")) return ORG_USERS;
    if (path.endsWith("/groups")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectRequestsPage> = {
  title: "Modules/ProductFeedback/ProjectRequestsPage",
  component: ProjectRequestsPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/product_feedback/requests${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/product_feedback/requests",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectRequestsPage>;

/** Open requests only by default; a delivered or duplicate one is hidden until Open only is unticked. */
export const OpensOnOpenRequestsWithScoreDemandAndWarnings: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Enhancement requests" });
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    const row = within(within(table).getByRole("link", { name: "ENH-001" }).closest("tr")!);
    await expect(row.getByText("High · 48")).toHaveClass("badge--accent");
    await expect(row.getByText("1 requester")).toBeInTheDocument();
    await expect(row.getByText("No Pain Point")).toHaveClass("badge--warning");
    await expect(within(table).queryByRole("link", { name: "ENH-004" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Open only" }));
    const duplicateRow = within((await within(table).findByRole("link", { name: "ENH-005" })).closest("tr")!);
    await expect(duplicateRow.getByText("Duplicate of ENH-001")).toBeInTheDocument();
    await expect(duplicateRow.queryByText("No Pain Point")).not.toBeInTheDocument();
    await expect(within(within(table).getByRole("link", { name: "ENH-004" }).closest("tr")!).getByText("2 to tell")).toBeInTheDocument();
  },
};

/** The score columns follow the enabled models, ICE and RICE here. */
export const ShowsAScoreColumnPerEnabledModel: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Enhancement requests" });
    await expect(within(table).getByRole("columnheader", { name: /Score \(ICE\)/ })).toBeInTheDocument();
    await expect(within(table).getByRole("columnheader", { name: /Score \(RICE\)/ })).toBeInTheDocument();
  },
};

/** The Unscored filter counts the requests missing a level and narrows the list to them. */
export const UnscoredFilterCountsAndNarrows: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Enhancement requests" });
    const scoring = canvas.getByLabelText("Scoring");
    await expect(within(scoring).getByRole("option", { name: "Unscored (1)" })).toBeInTheDocument();
    await userEvent.selectOptions(scoring, "unscored");
    await expect(within(table).getByRole("link", { name: "ENH-002" })).toBeInTheDocument();
    await expect(within(table).queryByRole("link", { name: "ENH-001" })).not.toBeInTheDocument();
  },
};

/** A link naming a status starts on that status, not on the open-only default. */
export const ALinkNamingAStatusOpensOnIt: Story = {
  parameters: { query: "?status=delivered" },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Enhancement requests" });
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
    await expect(within(table).getByRole("link", { name: "ENH-004" })).toBeInTheDocument();
    await expect(within(table).queryByRole("link", { name: "ENH-001" })).not.toBeInTheDocument();
  },
};

/** Where the project restricted submission and the viewer is not a triager, no New button and no Grid view. */
export const NoNewButtonWhenSubmissionIsRestricted: Story = {
  beforeEach: () => mockApis(REQUESTS, { can_submit: false, can_triage: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Enhancement requests" });
    await expect(canvas.queryByRole("button", { name: "New request" })).not.toBeInTheDocument();
  },
};

/** A triager is offered the Grid view; a member is not. */
export const TriagersGetTheGridView: Story = {
  beforeEach: () => mockApis(REQUESTS, { can_submit: true, can_triage: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Enhancement requests" });
    await expect(await canvas.findByRole("button", { name: /grid/i })).toBeInTheDocument();
  },
};

export const NewRequestOpensTheFormLayeredOverTheList: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Enhancement requests" });
    await userEvent.click(canvas.getByRole("button", { name: "New request" }));
    await expect(within(document.body).getByRole("dialog", { name: /New enhancement request/ })).toBeInTheDocument();
  },
};
