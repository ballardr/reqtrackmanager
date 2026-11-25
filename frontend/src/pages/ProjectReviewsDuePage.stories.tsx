import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import type { Component, RequirementDueForReview } from "../api/types";
import { withRouter, withTerminology } from "../testing/storybook-helpers";
import { ProjectReviewsDuePage } from "./ProjectReviewsDuePage";

const components: Component[] = [
  { id: "c1", project_id: "project-1", name: "Authentication", prefix: "AUTH", sort_order: 0 },
  { id: "c2", project_id: "project-1", name: "Reporting", prefix: "RPT", sort_order: 1 },
];

const items: RequirementDueForReview[] = [
  {
    requirement_id: "req-1", project_id: "project-1", unique_code: "AUTH-LOG-001",
    name: "Users can reset a forgotten password", review_date: "2026-03-01",
    reviewer: { type: "user", id: "user-1", label: "Alex Morgan", member_count: null, exists: true }, component_id: "c1", component_name: "Authentication",
  },
  {
    requirement_id: "req-2", project_id: "project-1", unique_code: "RPT-EXP-004",
    name: "Nightly export job", review_date: "2026-03-05",
    reviewer: null, component_id: "c2", component_name: "Reporting",
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

/** A refused request shows what failed with Retry, not a spinner that never ends; Retry reads the list again. */
export const FailedLoadOffersRetry: Story = {
  beforeEach: () => {
    let reads = 0;
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/components")) return components;
      reads += 1;
      if (reads === 1) throw new Error("The server is down.");
      return items;
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The reviews due could not be loaded.");
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await expect(await canvas.findByText("AUTH-LOG-001")).toBeInTheDocument();
  },
};

/** C-C-03: the page heading (`strings.reviews.projectTitle`) and the component-filter heading and "All X" option
 * (`strings.admin.components`/`strings.reviews.allComponents`) follow the project's Terminology settings, not hardcoded words. */
export const TerminologyOverrideAppliesToHeadingAndFilters: Story = {
  decorators: [withTerminology({ requirement: "Spec", component: "Module" })],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Specs due for review" })).toBeInTheDocument();
    await expect(canvas.getByText("Modules")).toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "All Modules" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...DueReviewsWithFilters, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DueReviewsWithFilters, globals: { theme: "dark" } };
