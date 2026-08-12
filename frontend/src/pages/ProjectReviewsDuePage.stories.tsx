import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import type { Component, RequirementDueForReview } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { ProjectReviewsDuePage } from "./ProjectReviewsDuePage";

const components: Component[] = [
  { id: "c1", project_id: "project-1", name: "Authentication", prefix: "AUTH", sort_order: 0 },
  { id: "c2", project_id: "project-1", name: "Reporting", prefix: "RPT", sort_order: 1 },
];

const items: RequirementDueForReview[] = [
  {
    requirement_id: "req-1", project_id: "project-1", unique_code: "AUTH-LOG-001",
    name: "Users can reset a forgotten password", review_date: "2026-03-01",
    reviewer_id: "user-1", reviewer_name: "Alex Morgan", component_id: "c1", component_name: "Authentication",
  },
  {
    requirement_id: "req-2", project_id: "project-1", unique_code: "RPT-EXP-004",
    name: "Nightly export job", review_date: "2026-03-05",
    reviewer_id: null, reviewer_name: null, component_id: "c2", component_name: "Reporting",
  },
];

const meta: Meta<typeof ProjectReviewsDuePage> = {
  title: "Pages/ProjectReviewsDuePage",
  component: ProjectReviewsDuePage,
  decorators: [withRouter("/projects/project-1/reviews-due", "/projects/:projectId/reviews-due")],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/components")) return components;
      return items;
    });
  },
};
export default meta;

type Story = StoryObj<typeof ProjectReviewsDuePage>;

export const DueReviewsWithFilters: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("AUTH-LOG-001")).toBeInTheDocument();
    await expect(canvas.getByText("Unassigned")).toBeInTheDocument();
    const [componentFilter] = canvas.getAllByRole("combobox");
    await userEvent.selectOptions(componentFilter, "Authentication");
    await expect(componentFilter).toHaveValue("c1");
  },
};

export const LightTheme: Story = { ...DueReviewsWithFilters, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DueReviewsWithFilters, globals: { theme: "dark" } };
