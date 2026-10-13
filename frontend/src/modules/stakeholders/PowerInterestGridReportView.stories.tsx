import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { withRouter } from "../../testing/storybook-helpers";
import { projectStakeholderGroupApi } from "./api";
import { buildStakeholderGroup } from "./fixtures";
import { PowerInterestGridReportView } from "./PowerInterestGridReportView";
import { gridData, gridEntry, gridResult } from "./reportFixtures";

const meta: Meta<typeof PowerInterestGridReportView> = {
  title: "Modules/Stakeholders/Reports/PowerInterestGridReportView",
  component: PowerInterestGridReportView,
  decorators: [withRouter("/projects/project-1/reports")],
  args: {
    entry: gridEntry(), result: gridResult(), scope: { kind: "project", id: "project-1" }, values: {}, onValueChange: fn(),
  },
  beforeEach: () => {
    spyOn(projectStakeholderGroupApi, "list").mockResolvedValue([
      buildStakeholderGroup({ id: "g-client", name: "Client" }),
      buildStakeholderGroup({ id: "g-acme", name: "Acme", parent_group_id: "g-client" }),
    ]);
  },
};
export default meta;

type Story = StoryObj<typeof PowerInterestGridReportView>;

/** Each Stakeholder sits in the quadrant its Influence and Interest give it, labelled by name, never the wire key. */
export const PlacesStakeholdersInQuadrants: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const manage = canvas.getByRole("region", { name: "Manage closely" });
    await expect(within(manage).getByRole("link", { name: "Sam Sponsor" })).toHaveAttribute(
      "href", "/projects/project-1/modules/stakeholders/stakeholders/sh-1",
    );
    await expect(within(canvas.getByRole("region", { name: "Keep satisfied" })).getByText("Pat Regulator")).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: "Keep informed" })).getByText("Uma User")).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: "Monitor" })).getByText("Nobody here.")).toBeInTheDocument();
    await expect(canvas.getByText("Higher influence")).toBeInTheDocument();
    await expect(canvas.getByText("Higher interest")).toBeInTheDocument();
  },
};

/** Stakeholders with no position are not lost: they are listed as a gap table beneath the grid. */
export const ListsTheUnscored: Story = {
  play: async ({ canvasElement }) => {
    const unscored = within(within(canvasElement).getByRole("region", { name: "Not scored" }));
    await expect(unscored.getByText("Newly Added")).toBeInTheDocument();
  },
};

/** Choosing a group re-runs the report with its id; blank clears it. */
export const GroupFilterReRuns: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Group")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Group"), "g-acme");
    await expect(args.onValueChange).toHaveBeenCalledWith("group_id", "g-acme");
    await userEvent.selectOptions(canvas.getByLabelText("Group by"), "g-client");
    await expect(args.onValueChange).toHaveBeenCalledWith("group_by", "g-client");
    // "Group by" offers only top-level groups.
    await expect(within(canvas.getByLabelText("Group by")).queryByRole("option", { name: "Acme" })).not.toBeInTheDocument();
  },
};

export const NothingToReport: Story = {
  args: { result: gridResult({ eligible_projects: 0, data: gridData() }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent("Nothing to report on");
  },
};

export const LightTheme: Story = { ...PlacesStakeholdersInQuadrants, globals: { theme: "light" } };
export const DarkTheme: Story = { ...PlacesStakeholdersInQuadrants, globals: { theme: "dark" } };
