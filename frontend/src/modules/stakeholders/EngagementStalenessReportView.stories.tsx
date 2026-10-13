import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, within } from "storybook/test";

import { withRouter } from "../../testing/storybook-helpers";
import { projectStakeholderGroupApi } from "./api";
import { buildStakeholderGroup } from "./fixtures";
import { EngagementStalenessReportView } from "./EngagementStalenessReportView";
import { stalenessEntry, stalenessResult } from "./reportFixtures";

const meta: Meta<typeof EngagementStalenessReportView> = {
  title: "Modules/Stakeholders/Reports/EngagementStalenessReportView",
  component: EngagementStalenessReportView,
  decorators: [withRouter("/projects/project-1/reports")],
  args: {
    entry: stalenessEntry(), result: stalenessResult(), scope: { kind: "project", id: "project-1" }, values: {}, onValueChange: fn(),
  },
  beforeEach: () => {
    spyOn(projectStakeholderGroupApi, "list").mockResolvedValue([buildStakeholderGroup({ id: "g-client", name: "Client" })]);
  },
};
export default meta;

type Story = StoryObj<typeof EngagementStalenessReportView>;

/** The three gap tables render as the generic viewer does, with the group controls above. */
export const ShowsGapTablesAndGroupControls: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const overdue = within(canvas.getByRole("region", { name: "Overdue for engagement" }));
    await expect(overdue.getByText("75 days")).toBeInTheDocument();
    await expect(overdue.getByText("Only Fridays")).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "No target cadence set" })).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: /Personas with no engagement/ })).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Group")).toBeInTheDocument();
  },
};

export const NoGroupsHidesTheControls: Story = {
  beforeEach: () => {
    spyOn(projectStakeholderGroupApi, "list").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByLabelText("Group")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ShowsGapTablesAndGroupControls, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ShowsGapTablesAndGroupControls, globals: { theme: "dark" } };
