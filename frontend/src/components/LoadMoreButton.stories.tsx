import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LoadMoreButton } from "./LoadMoreButton";

const meta: Meta<typeof LoadMoreButton> = {
  title: "Components/LoadMoreButton",
  component: LoadMoreButton,
  args: { onClick: fn() },
};
export default meta;

type Story = StoryObj<typeof LoadMoreButton>;

export const MoreToLoad: Story = {
  args: { loaded: 20, total: 57 },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button");
    await expect(button).toHaveTextContent("20/57");
    await userEvent.click(button);
    await expect(args.onClick).toHaveBeenCalledOnce();
  },
};

/** `loaded >= total` renders nothing at all (U-P-06) — pinning that the
 * component itself hides, rather than every caller having to remember to
 * conditionally render it. */
export const AllLoaded: Story = {
  args: { loaded: 57, total: 57 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { args: { loaded: 20, total: 57 }, globals: { theme: "light" } };
export const DarkTheme: Story = { args: { loaded: 20, total: 57 }, globals: { theme: "dark" } };
