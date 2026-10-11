import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { LinkTraceLegend } from "./LinkTraceLegend";

/** The trace map's key (shown in a popover): one entry per symbol the map draws. */
const meta: Meta<typeof LinkTraceLegend> = {
  title: "Components/LinkTraceLegend",
  component: LinkTraceLegend,
  parameters: { a11y: { test: "error" } },
};
export default meta;

type Story = StoryObj<typeof LinkTraceLegend>;

export const NamesEverySymbol: Story = {
  play: async ({ canvasElement }) => {
    const key = within(within(canvasElement).getByRole("list", { name: "Key" }));
    for (const entry of [
      "This record", "Upstream", "Downstream", "Related (no direction)", "Arrow points downstream",
      "In another project", "Archived",
    ]) {
      await expect(key.getByText(entry)).toBeInTheDocument();
    }
  },
};
