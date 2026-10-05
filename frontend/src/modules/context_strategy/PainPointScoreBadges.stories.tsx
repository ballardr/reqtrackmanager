import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import { scoreValue } from "./painPointScoringFixtures";

const meta: Meta<typeof PainPointScoreBadge> = {
  title: "Modules/ContextStrategy/PainPointScoreBadges",
  component: PainPointScoreBadge,
};
export default meta;

type Story = StoryObj<typeof PainPointScoreBadge>;

export const BandAndValue: Story = {
  args: { score: scoreValue({ raw: 12.5, band_label: "Critical", band_tone: "danger" }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Critical · 12.5")).toBeInTheDocument();
  },
};

export const WholeNumberDropsDecimals: Story = {
  args: { score: scoreValue({ raw: 8 }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("High · 8")).toBeInTheDocument();
  },
};

export const NotScored: Story = {
  args: { score: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Not scored")).toBeInTheDocument();
  },
};

export const BlockerNamesWhoIsBlocked: Story = {
  render: () => <BlockerBadge summary={{ is_blocker: true, blocker_labels: ["Field Technician"] }} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Blocker")).toHaveAttribute("title", "Unusable for: Field Technician");
  },
};

export const NoBlockerRendersNothing: Story = {
  render: () => <BlockerBadge summary={{ is_blocker: false, blocker_labels: [] }} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Blocker")).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...BandAndValue, globals: { theme: "dark" } };
