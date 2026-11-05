import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildRequestScheme, buildScore } from "./requestFixtures";
import { RequestScorePreview } from "./RequestScorePreview";

const scheme = buildRequestScheme();

const meta: Meta<typeof RequestScorePreview> = {
  title: "Modules/ProductFeedback/RequestScorePreview",
  component: RequestScorePreview,
  args: { scheme, levels: {}, state: { preview: null, loading: true, failed: false } },
};
export default meta;

type Story = StoryObj<typeof RequestScorePreview>;

/** Before the first answer the panel says it is calculating. */
export const Calculating: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Calculating…")).toBeInTheDocument();
  },
};

/** A model scores once its levels are chosen; one still missing a level says so on hover. */
export const ScoredAndMissing: Story = {
  args: {
    levels: { impact: "impact-4", confidence: "conf-4", ease: "ease-4" },
    state: {
      preview: { scores: { ice: buildScore(), rice: null }, derived_levels: {}, weighted_demand: 0 },
      loading: false, failed: false,
    },
  },
  play: async ({ canvasElement }) => {
    const panel = within(canvasElement);
    await expect(panel.getByText("High · 48")).toBeInTheDocument();
    await expect(panel.getByLabelText("Not scored. Needs Reach, Effort to be scored")).toHaveTextContent("Not scored");
    await expect(panel.getByRole("columnheader", { name: "ICE" })).toBeInTheDocument(); // the formula is dropped from the visible name
  },
};

/** A failed ask keeps the page usable and says so. */
export const Failed: Story = {
  args: { state: { preview: null, loading: false, failed: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/could not be calculated/)).toBeInTheDocument();
  },
};
