import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { ProjectHistoryPage } from "./ProjectHistoryPage";

const meta: Meta<typeof ProjectHistoryPage> = {
  title: "Pages/ProjectHistoryPage",
  component: ProjectHistoryPage,
  decorators: [withRouter("/projects/project-1/history", "/projects/:projectId/history")],
};
export default meta;

type Story = StoryObj<typeof ProjectHistoryPage>;

export const ChangeHistory: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" }),
      buildChangeEntry({
        entity_type: "change_request",
        entity_id: "cr-1",
        action: "approved",
        actor_display_name: "Jamie Lee",
      }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
    await expect(canvas.getByText("Jamie Lee approved")).toBeInTheDocument();
  },
};

export const FilterByEntityType: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No changes in this range.")).toBeInTheDocument();
    const select = canvas.getByLabelText("Type");
    await userEvent.selectOptions(select, "Requirement");
    await expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining("entity_type=requirement"));
  },
};

export const LightTheme: Story = { ...ChangeHistory, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ChangeHistory, globals: { theme: "dark" } };
