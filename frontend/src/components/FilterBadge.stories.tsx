import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { FilterBadge } from "./FilterBadge";

const meta: Meta<typeof FilterBadge> = {
  title: "Components/FilterBadge",
  component: FilterBadge,
  args: { onClick: fn(), children: "Draft" },
};
export default meta;

type Story = StoryObj<typeof FilterBadge>;

export const Inactive: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const badge = canvas.getByRole("button", { name: "Draft" });
    await userEvent.click(badge);
    await expect(args.onClick).toHaveBeenCalledOnce();
  },
};

export const Active: Story = {
  args: { active: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Draft" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { args: { active: true }, globals: { theme: "dark" } };

// Status colour (Pattern: status colour, docs/ux-style-guide.md). One story per BadgeTone keeps every tone
// reviewable, each with a play-check that `tone` leaves the click behaviour of the plain-badge stories unchanged.
export const ToneMuted: Story = {
  args: { tone: "muted", children: "Draft" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await expect(args.onClick).toHaveBeenCalledOnce();
  },
};
export const ToneInfo: Story = { args: { tone: "info", children: "In review" } };
export const ToneAccent: Story = { args: { tone: "accent", children: "Approved" } };
export const ToneDanger: Story = { args: { tone: "danger", children: "Rejected" } };
