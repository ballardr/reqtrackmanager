import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ProjectScopeLabel } from "./ProjectScopeLabel";

/**
 * The muted "From <project>" label on a row of a widened list. A row of the project being viewed
 * carries no `from_project_*` fields and shows nothing.
 */
const meta: Meta<typeof ProjectScopeLabel> = {
  title: "Components/ProjectScopeLabel",
  component: ProjectScopeLabel,
};
export default meta;

type Story = StoryObj<typeof ProjectScopeLabel>;

export const RowFromAnotherProject: Story = {
  args: { row: { from_project_id: "p-1", from_project_name: "Platform", from_project_code: "PLAT" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("From Platform")).toBeInTheDocument();
  },
};

export const RowFromThisProjectShowsNothing: Story = {
  args: { row: {} },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.textContent).toBe("");
  },
};

/** A very long project name wraps instead of pushing the row's controls. */
export const LongProjectName: Story = {
  args: { row: { from_project_id: "p-1", from_project_name: "A programme with a very long name ".repeat(4), from_project_code: "LONG" } },
};
