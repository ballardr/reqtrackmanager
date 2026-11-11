import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { InlineMessage } from "./InlineMessage";

const meta: Meta<typeof InlineMessage> = {
  title: "Components/InlineMessage",
  component: InlineMessage,
};
export default meta;

type Story = StoryObj<typeof InlineMessage>;

/** An error is announced as an alert. */
export const ErrorTone: Story = {
  args: { children: "Could not save the settings." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveTextContent("Could not save the settings.");
  },
};

/** A success note is announced as a status. */
export const SuccessTone: Story = {
  args: { tone: "success", children: "Logo uploaded." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent("Logo uploaded.");
  },
};

/** An empty message draws nothing, so a caller can pass its error state unconditionally. */
export const EmptyDrawsNothing: Story = {
  args: { children: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("alert")).toBeNull();
    await expect(within(canvasElement).queryByRole("status")).toBeNull();
  },
};
