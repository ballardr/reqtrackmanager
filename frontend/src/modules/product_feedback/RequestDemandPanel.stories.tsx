import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withRouter } from "../../testing/storybook-helpers";
import { buildDemand, buildRequester, CHANNEL_CHOICES, PROJECT_ID } from "./requestFixtures";
import { RequestDemandPanel } from "./RequestDemandPanel";

const meta: Meta<typeof RequestDemandPanel> = {
  title: "Modules/ProductFeedback/RequestDemandPanel",
  component: RequestDemandPanel,
  args: { projectId: PROJECT_ID, merges: [] },
  decorators: [withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof RequestDemandPanel>;

export const ListsRequestersWeightsAndEngagements: Story = {
  args: { demand: buildDemand() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = canvas.getByRole("table", { name: "Requesters" });
    await expect(within(table).getByText("Priya Shah")).toBeInTheDocument();
    await expect(within(table).getByText("Persona")).toBeInTheDocument();
    await expect(within(table).getAllByText("Engagement").length).toBeGreaterThan(0);
    await expect(canvas.getByText("2 requesters · 4.5")).toBeInTheDocument();
    await expect(canvas.getByText("Customer workshop")).toBeInTheDocument();
  },
};

/** A requester the viewer may not see is counted but not named. */
export const AHiddenRequesterIsCountedNotNamed: Story = {
  args: { demand: buildDemand({ requesters: [buildRequester({ hidden: true, label: null })], requester_count: 1, weighted_demand: 3 }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("A requester you can’t view")).toBeInTheDocument();
  },
};

export const EmptyDemandSaysHowToAddARequester: Story = {
  args: { demand: buildDemand({ requesters: [], engagements: [], requester_count: 0, weighted_demand: 0 }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/“Requested by” in the Links panel/)).toBeInTheDocument();
  },
};

export const MergedDuplicatesAreListedWithTheirHistory: Story = {
  args: {
    demand: buildDemand({ merged_duplicates: [{ id: "request-9", unique_code: "ENH-009", title: "Excel please" }] }),
    merges: [{
      id: "merge-1", canonical: { id: "request-1", unique_code: "ENH-001", title: "Export" },
      duplicate: { id: "request-9", unique_code: "ENH-009", title: "Excel please" }, prior_status: "new",
      merged_by: "user-1", merged_at: "2026-11-02T09:00:00Z", unmerged_by: null, unmerged_at: null, active: true,
    }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "ENH-009 Excel please" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/product_feedback/requests/request-9`,
    );
    await expect(canvas.getByText("Merge history (1)")).toBeInTheDocument();
  },
};

/** A requester shows how they asked; one reached through an Engagement reads as an Engagement and has nothing to set. */
export const ShowsTheChannelEachRequesterUsed: Story = {
  args: {
    demand: buildDemand({
      requesters: [
        buildRequester({ channel: { id: "channel-ticket", name: "Support ticket" } }),
        buildRequester({ artefact_type: "persona", id: "persona-1", label: "Power user", via_engagement: true }),
        buildRequester({ id: "stakeholder-3", label: "Sam Rivera" }),
      ],
    }),
    canSetChannel: true, channels: CHANNEL_CHOICES, onSetChannel: fn().mockResolvedValue(undefined),
  },
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Requesters" }));
    await expect(table.getByText("Support ticket")).toBeInTheDocument();
    await expect(table.getByText("Not recorded")).toBeInTheDocument();
    await expect(table.getByRole("button", { name: "Set channel for Priya Shah" })).toBeInTheDocument();
    await expect(table.queryByRole("button", { name: "Set channel for Power user" })).not.toBeInTheDocument();
  },
};

/** A triager records a channel from the pencil; the panel hands the requester and channel up. */
export const ATriagerSetsAChannel: Story = {
  args: {
    demand: buildDemand({ requesters: [buildRequester()] }),
    canSetChannel: true, channels: CHANNEL_CHOICES, onSetChannel: fn().mockResolvedValue(undefined),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Set channel for Priya Shah" }));
    const popover = within(document.body);
    await userEvent.selectOptions(popover.getByLabelText("Channel for Priya Shah"), "channel-email");
    await userEvent.click(popover.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSetChannel).toHaveBeenCalledWith(expect.objectContaining({ id: "stakeholder-1" }), "channel-email"));
  },
};

/** Someone who may not triage sees the channel but no pencil. */
export const AReaderSeesNoChannelControls: Story = {
  args: { demand: buildDemand({ requesters: [buildRequester({ channel: { id: "channel-call", name: "Call" } })] }), canSetChannel: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Call")).toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("button", { name: /Set channel/ })).not.toBeInTheDocument();
  },
};
