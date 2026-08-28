import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ResultCount } from "./ResultCount";

const meta: Meta<typeof ResultCount> = {
  title: "Components/ResultCount",
  component: ResultCount,
};
export default meta;

type Story = StoryObj<typeof ResultCount>;

/** No filter/search narrowing the result set (`matching === total`,
 * 2026-08 UX audit roadmap: persistent "showing X of Y" result count) —
 * shows just the total, e.g. on first load of a list page before any
 * filter/search is applied. */
export const TotalOnly: Story = {
  args: { matching: 57, total: 57 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("57 total")).toBeInTheDocument();
  },
};

/** A filter or search term is active (`matching < total`) — shows both
 * counts, the narrowed count first, so the total stays visible as
 * context for how much of the list a filter is hiding. */
export const MatchingAndTotal: Story = {
  args: { matching: 12, total: 57 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Showing 12 matching · 57 total")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...TotalOnly, globals: { theme: "light" } };
export const DarkTheme: Story = { ...TotalOnly, globals: { theme: "dark" } };
