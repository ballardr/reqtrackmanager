import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { SubscribeButton } from "./SubscribeButton";

const meta: Meta<typeof SubscribeButton> = {
  title: "Components/SubscribeButton",
  component: SubscribeButton,
  args: { onToggle: fn() },
};
export default meta;

type Story = StoryObj<typeof SubscribeButton>;

export const NotSubscribed: Story = {
  args: { subscribed: false },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Subscribe")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button"));
    await expect(args.onToggle).toHaveBeenCalledOnce();
  },
};

export const Subscribed: Story = {
  args: { subscribed: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Subscribed")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { args: { subscribed: true }, globals: { theme: "light" } };
export const DarkTheme: Story = { args: { subscribed: true }, globals: { theme: "dark" } };
