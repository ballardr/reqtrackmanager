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
    await expect(canvas.getByText("From Influence level")).toBeInTheDocument(); // where each weight comes from
    await expect(canvas.getByText("Set for this project")).toBeInTheDocument();
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
    await expect(within(canvasElement).getByText(/No one is recorded as having asked for this yet/)).toBeInTheDocument();
  },
};

export const MergedDuplicatesAreListedWithTheirHistory: Story = {
  args: {
    demand: buildDemand({ merged_duplicates: [{ id: "request-9", unique_code: "ENH-009", title: "Excel please" }] }),
    merges: [{
      id: "merge-1", canonical: { id: "request-1", unique_code: "ENH-001", title: "Export" },
      duplicate: { id: "request-9", unique_code: "ENH-009", title: "Excel please" }, prior_status: "new",
      merged_by: "user-1", merged_at: "2026-11-02T09:00:00Z", note: "Same ask, different words", unmerged_by: null, unmerged_at: null, active: true,
    }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "ENH-009 Excel please" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/product_feedback/requests/request-9`,
    );
    await expect(canvas.getByText("Merge history (1)")).toBeInTheDocument();
    // The note the triager gave when merging is shown as the reason.
    await expect(canvas.getByText("Same ask, different words")).toBeInTheDocument();
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

/** A long list shows what is loaded against the total and offers the next page; the headline still covers everyone. */
export const AShortPageOfALongListOffersShowMore: Story = {
  args: {
    demand: buildDemand({ requester_count: 120, weighted_demand: 131, requesters: [buildRequester(), buildRequester({ id: "stakeholder-2", label: "Sam Rivera" })] }),
    onShowMore: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("120 requesters · 131")).toBeInTheDocument();
    await expect(canvas.getByText("Showing 2 of 120 requesters")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show more" }));
    await expect(args.onShowMore).toHaveBeenCalled();
  },
};

/** Everyone loaded: no paging line. */
export const NoPagingWhenEveryoneIsLoaded: Story = {
  args: { demand: buildDemand(), onShowMore: fn() },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText(/Showing \d+ of/)).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  },
};

/** A triager gets Add requester, with or without anyone listed yet. */
export const ATriagerCanAddRequesters: Story = {
  args: { demand: buildDemand(), onAddRequesters: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add requester" }));
    await expect(args.onAddRequesters).toHaveBeenCalled();
  },
};

export const NobodyElseSeesAddRequester: Story = {
  args: { demand: buildDemand() },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Add requester" })).not.toBeInTheDocument();
  },
};

/** Only the request's own links can be removed: a requester reached through an Engagement has a dimmed button saying why. */
export const ADirectRequesterAndAnEngagementCanBeRemoved: Story = {
  args: { demand: buildDemand(), onRemoveRequester: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const dimmed = canvas.getByRole("button", { name: "Remove requester Power user" });
    await expect(dimmed).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(dimmed);
    await expect(args.onRemoveRequester).not.toHaveBeenCalled();
    await userEvent.hover(dimmed);
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent(/Remove that Engagement to remove them/);
    await userEvent.unhover(dimmed);
    await userEvent.click(canvas.getByRole("button", { name: "Remove requester Priya Shah" }));
    await expect(args.onRemoveRequester).toHaveBeenLastCalledWith("link-1", "Priya Shah", "requester");
    await userEvent.click(canvas.getByRole("button", { name: "Remove Engagement Customer workshop" }));
    await expect(args.onRemoveRequester).toHaveBeenLastCalledWith("link-e1", "Customer workshop", "engagement");
  },
};

/** A requester counted from a merged duplicate says to undo the merge; an enabled button says what it removes. */
export const EveryRemoveButtonExplainsItself: Story = {
  args: {
    demand: buildDemand({ requesters: [buildRequester(), buildRequester({ id: "stakeholder-2", label: "Sam Rivera", from_merge: true, link_id: null })] }),
    onRemoveRequester: fn(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(canvas.getByRole("button", { name: "Remove requester Sam Rivera" }));
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Undo that merge to remove them");
    await userEvent.unhover(canvas.getByRole("button", { name: "Remove requester Sam Rivera" }));
    await userEvent.hover(canvas.getByRole("button", { name: "Remove requester Priya Shah" }));
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Remove Priya Shah as a requester");
  },
};

export const NoRemoveButtonsWithoutTheRight: Story = {
  args: { demand: buildDemand() },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
  },
};
