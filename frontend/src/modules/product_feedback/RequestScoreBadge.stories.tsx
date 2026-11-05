import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildScore } from "./requestFixtures";
import { RequestScoreBadge } from "./RequestScoreBadge";

const meta: Meta<typeof RequestScoreBadge> = { title: "Modules/ProductFeedback/RequestScoreBadge", component: RequestScoreBadge };
export default meta;

type Story = StoryObj<typeof RequestScoreBadge>;

export const BandAndRawScoreInTheBandsTone: Story = {
  args: { score: buildScore({ raw: 7.5, label: "Medium", tone: "info" }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Medium · 7.5")).toHaveClass("badge--info");
  },
};

export const NoScoreReadsNotScored: Story = {
  args: { score: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Not scored")).toHaveClass("badge--muted");
  },
};
