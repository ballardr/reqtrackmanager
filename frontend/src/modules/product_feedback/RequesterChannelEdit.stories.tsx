import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { CHANNEL_CHOICES } from "./requestFixtures";
import { RequesterChannelEdit } from "./RequesterChannelEdit";

const meta: Meta<typeof RequesterChannelEdit> = {
  title: "Modules/ProductFeedback/RequesterChannelEdit",
  component: RequesterChannelEdit,
  args: { who: "Priya Shah", current: null, channels: CHANNEL_CHOICES, onSave: fn().mockResolvedValue(undefined) },
};
export default meta;

type Story = StoryObj<typeof RequesterChannelEdit>;

/** Choosing a channel and saving records it; the popover then closes. */
export const ChoosingAChannelSavesIt: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Set channel for Priya Shah" }));
    const popover = within(document.body);
    await userEvent.selectOptions(popover.getByLabelText("Channel for Priya Shah"), "channel-call");
    await userEvent.click(popover.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("channel-call"));
  },
};

/** Going back to "Not recorded" clears the channel. */
export const ClearingSendsNull: Story = {
  args: { current: { id: "channel-call", name: "Call" } },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Set channel for Priya Shah" }));
    const popover = within(document.body);
    await expect(popover.getByLabelText("Channel for Priya Shah")).toHaveValue("channel-call");
    await userEvent.selectOptions(popover.getByLabelText("Channel for Priya Shah"), "");
    await userEvent.click(popover.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(null));
  },
};
