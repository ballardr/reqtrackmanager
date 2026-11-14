import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withRouter } from "../../testing/storybook-helpers";
import { AllocationCoverageTiles } from "./AllocationCoverageTiles";
import { PROJECT_ID } from "./architectureFixtures";

const meta: Meta<typeof AllocationCoverageTiles> = {
  title: "Modules/Architecture/AllocationCoverageTiles",
  component: AllocationCoverageTiles,
  args: { projectId: PROJECT_ID },
  decorators: [withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof AllocationCoverageTiles>;

/** The tiles show the percentage allocated, the requirements left and the suggestions awaiting a decision. */
export const ShowsTheCoverageCounts: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ requirements: 8, allocated_requirements: 6, elements: 4, allocated_elements: 3, suggestions: 5 } as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("75%")).toBeInTheDocument();
    await expect(canvas.getByText("Requirements not allocated").parentElement).toHaveTextContent("2");
    await expect(canvas.getByText("Suggested allocations").parentElement).toHaveTextContent("5");
  },
};

/** A project with no requirement shows 0% rather than an undefined figure. */
export const NoRequirementsShowsZeroPercent: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ requirements: 0, allocated_requirements: 0, elements: 0, allocated_elements: 0, suggestions: 0 } as never);
  },
  play: async ({ canvasElement }) => { await expect(await within(canvasElement).findByText("0%")).toBeInTheDocument(); },
};

/** A person who cannot read the counts sees nothing. */
export const NothingIsDrawnWithoutAccess: Story = {
  beforeEach: () => { spyOn(api, "get").mockRejectedValue(new ApiError(403, "No access.")); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(canvasElement.querySelector(".grid-metrics")).toBeNull();
  },
};
