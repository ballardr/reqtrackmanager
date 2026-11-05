import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildRequest, buildRequestScheme, buildUnscoredRequest } from "./requestFixtures";
import { RequestScoresPanel } from "./RequestScoresPanel";

const meta: Meta<typeof RequestScoresPanel> = {
  title: "Modules/ProductFeedback/RequestScoresPanel",
  component: RequestScoresPanel,
  args: { scheme: buildRequestScheme(), showDemand: true },
};
export default meta;

type Story = StoryObj<typeof RequestScoresPanel>;

/** Each model scored sits side by side with the demand, and the derived criterion says it was worked out. */
export const ShowsEveryModelAndTheWorkedOutDemandLevel: Story = {
  args: { request: buildRequest() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ICE")).toBeInTheDocument();
    await expect(canvas.getByText("RICE")).toBeInTheDocument();
    await expect(canvas.getByText("High · 48")).toHaveClass("badge--accent");
    await expect(canvas.getByText("1 requester")).toBeInTheDocument();
    await expect(canvas.getByText(/\(worked out from demand\)/)).toBeInTheDocument();
  },
};

/** A model missing a level reads Not scored, never zero. */
export const AMissingLevelReadsNotScored: Story = {
  args: { request: buildUnscoredRequest() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText("Not scored")).toHaveLength(2);
    await expect(canvas.getAllByText("Not set").length).toBeGreaterThan(0);
  },
};

/** An inbox request has no requesters, so no demand is shown. */
export const InboxHidesDemand: Story = {
  args: { request: buildRequest({ scope: "organization" }), showDemand: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Demand", { selector: "span" })).not.toBeInTheDocument();
  },
};
