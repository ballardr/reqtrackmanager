import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildRisk } from "./riskFixtures";
import { RiskRatingBadge } from "./RiskRatingBadge";

const meta: Meta<typeof RiskRatingBadge> = {
  title: "Modules/RiskManagement/RiskRatingBadge",
  component: RiskRatingBadge,
};
export default meta;

type Story = StoryObj<typeof RiskRatingBadge>;

export const BandInItsTone: Story = {
  args: { rating: buildRisk().inherent_rating },
  play: async ({ canvasElement }) => {
    const badge = within(canvasElement).getByText("High");
    await expect(badge).toHaveClass("badge--warning");
  },
};

export const NotRatedWhenLevelsAreMissing: Story = {
  args: { rating: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Not rated")).toHaveClass("badge--muted");
  },
};

/** The review history stores a band label, not a rating, so the label and tone arrive separately. */
export const FromAStoredLabel: Story = {
  args: { label: "Critical", tone: "danger" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Critical")).toHaveClass("badge--danger");
  },
};

export const DarkTheme: Story = { ...BandInItsTone, globals: { theme: "dark" } };
