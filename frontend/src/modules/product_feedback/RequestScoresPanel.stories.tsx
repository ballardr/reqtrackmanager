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

/** Each model scored sits side by side, and the derived criterion says it was worked out and from what. */
export const ShowsEveryModelAndTheWorkedOutDemandLevel: Story = {
  args: { request: buildRequest() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("columnheader", { name: "ICE" })).toBeInTheDocument();
    await expect(canvas.getByRole("columnheader", { name: "RICE" })).toBeInTheDocument();
    await expect(canvas.getByText("High · 48")).toHaveClass("badge--accent");
    await expect(canvas.getByText(/Calculated from 1 requester/)).toBeInTheDocument(); // the icon button's accessible name
  },
};

/** A level a person chose for the derived criterion says so, rather than claiming it was worked out. */
export const AChosenDemandLevelSaysSo: Story = {
  args: { request: buildRequest({ levels: { demand: "demand-3" } }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/Chosen manually from 1 requester/)).toBeInTheDocument();
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

/** An inbox request has no requesters, so the Demand note names no one. */
export const InboxHidesDemand: Story = {
  args: { request: buildRequest({ scope: "organization" }), showDemand: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/requester/)).not.toBeInTheDocument();
    await expect(canvas.getByText(/Calculated from demand/)).toBeInTheDocument();
  },
};
