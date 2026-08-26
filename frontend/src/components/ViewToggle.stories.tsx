import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ViewToggle } from "./ViewToggle";

// Storied directly with controlled props, not through `useViewMode` (which
// needs `useUiPreference`'s server sync mocked) — see the QA inventory.
const meta: Meta<typeof ViewToggle> = {
  title: "Components/ViewToggle",
  component: ViewToggle,
  args: { onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof ViewToggle>;

export const TilesActive: Story = {
  args: { mode: "tiles" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Tile view" })).toHaveAttribute("aria-pressed", "true");
    await expect(canvas.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(args.onChange).toHaveBeenCalledWith("list");
  },
};

export const ListActive: Story = {
  args: { mode: "list" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
  },
};

export const LightTheme: Story = { ...TilesActive, globals: { theme: "light" } };
export const DarkTheme: Story = { ...TilesActive, globals: { theme: "dark" } };

export const TreeOptionHidden: Story = {
  args: { mode: "tiles", showTreeOption: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Tree view" })).not.toBeInTheDocument();
  },
};

export const TreeOptionShown: Story = {
  args: { mode: "tiles", showTreeOption: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Tree view" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Tree view" }));
    await expect(args.onChange).toHaveBeenCalledWith("tree");
  },
};

export const TreeActive: Story = {
  args: { mode: "tree", showTreeOption: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Tree view" })).toHaveAttribute("aria-pressed", "true");
  },
};
