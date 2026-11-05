import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildLoop, buildLoopRequester } from "./requestFixtures";
import { RequestLoopPanel } from "./RequestLoopPanel";

const meta: Meta<typeof RequestLoopPanel> = {
  title: "Modules/ProductFeedback/RequestLoopPanel",
  component: RequestLoopPanel,
  args: { loop: buildLoop(), onInformed: fn().mockResolvedValue(undefined) },
};
export default meta;

type Story = StoryObj<typeof RequestLoopPanel>;

/** Each requester has a Told checkbox, the date it was recorded and the note; the heading line counts who is left. */
export const ListsRequestersWithWhoWasTold: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("1 of 2 still to be told.")).toBeInTheDocument();
    const table = within(canvas.getByRole("table", { name: "Requesters to tell" }));
    await expect(table.getByLabelText("Told Priya Shah")).not.toBeChecked();
    await expect(table.getByLabelText("Told Sam Rivera")).toBeChecked();
    await expect(table.getByText("Emailed on release")).toBeInTheDocument();
  },
};

/** The channel each requester used is shown so the person doing the telling knows how to reach them. */
export const ShowsTheChannelEachRequesterUsed: Story = {
  args: {
    loop: buildLoop({
      requesters: [
        buildLoopRequester({ channel: { id: "channel-ticket", name: "Support ticket" } }),
        buildLoopRequester({ id: "persona-1", artefact_type: "persona", label: "Power user", via_engagement: true }),
        buildLoopRequester({ id: "stakeholder-3", label: "Sam Rivera" }),
      ],
    }),
  },
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Requesters to tell" }));
    await expect(table.getByText("Support ticket")).toBeInTheDocument();
    await expect(table.getByText("Engagement")).toBeInTheDocument();
  },
};

/** Ticking a requester records it with the note typed in "How they were told". */
export const TickingARequesterRecordsItWithTheNote: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("How they were told"), "Phoned");
    await userEvent.click(canvas.getByLabelText("Told Priya Shah"));
    await waitFor(() => expect(args.onInformed).toHaveBeenCalledWith([{ artefact_type: "stakeholder", id: "stakeholder-1" }], true, "Phoned"));
  },
};

/** Mark all told sends only the requesters still open. */
export const MarkAllToldSendsTheOpenOnes: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Mark all told" }));
    await waitFor(() => expect(args.onInformed).toHaveBeenCalledWith([{ artefact_type: "stakeholder", id: "stakeholder-1" }], true, ""));
  },
};

/** Once everyone is told there is nothing left to mark. */
export const EveryoneToldDisablesMarkAll: Story = {
  args: { loop: buildLoop({ requesters: [buildLoopRequester({ informed: true, informed_at: "2026-11-03T10:00:00Z" })], informed_count: 1, open_count: 0 }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Everyone who asked has been told.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Mark all told" })).toBeDisabled();
  },
};

/** Before the request is delivered or declined there is no outcome to tell anyone, so nothing can be ticked. */
export const NothingCanBeRecordedBeforeTheOutcome: Story = {
  args: { loop: buildLoop({ status: "accepted", can_record: false }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/can be recorded once the request is delivered or declined/)).toBeInTheDocument();
    await expect(canvas.getByLabelText("Told Priya Shah")).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: "Mark all told" })).not.toBeInTheDocument();
  },
};

/** A declined request shows the reason, and a requester the viewer may not see still gets a row, unnamed. */
export const DeclinedShowsTheReasonAndAHiddenRequesterStillHasARow: Story = {
  args: {
    loop: buildLoop({
      status: "declined", decline_reason: "Out of scope",
      requesters: [buildLoopRequester({ hidden: true, label: null })],
      informed_count: 0, open_count: 1,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Out of scope")).toBeInTheDocument();
    await expect(canvas.getByText("A requester you can’t view")).toBeInTheDocument();
  },
};

export const NoRequestersMeansNoOneToTell: Story = {
  args: { loop: buildLoop({ requesters: [], informed_count: 0, open_count: 0 }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/no one to tell/)).toBeInTheDocument();
  },
};
