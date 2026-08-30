import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ChangeEntry, ProjectMetrics } from "../api/types";
import { buildChangeEntry, buildProject, withRouter, withTerminology } from "../testing/storybook-helpers";
import { ProjectOverviewPage } from "./ProjectOverviewPage";

const metrics: ProjectMetrics = {
  requirement_count: 24,
  requirement_completed_percent: 62,
  change_requests_proposed: 5,
  change_requests_approved: 12,
  change_requests_rejected: 2,
  file_count: 8,
  // C-G-11: "completed" is no longer a `RequirementStatus` value (it's the
  // independent `Requirement.is_completed` overlay now) — sums to 24
  // (requirement_count) the same as before, just without that bucket.
  requirements_by_status: { draft: 4, reviewed: 3, approved: 15, archived: 2 },
  stage_progress: [
    { stage_id: "s1", name: "Scoping", status: "completed", requirement_count: 10, completed_percent: 100 },
    { stage_id: "s2", name: "Build", status: "scoping", requirement_count: 14, completed_percent: 30 },
  ],
};

const activity: ChangeEntry[] = [buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" })];

const meta: Meta<typeof ProjectOverviewPage> = {
  title: "Pages/ProjectOverviewPage",
  component: ProjectOverviewPage,
  decorators: [withRouter("/projects/project-1", "/projects/:projectId"), withTerminology()],
};
export default meta;

type Story = StoryObj<typeof ProjectOverviewPage>;

export const Dashboard: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/metrics")) return metrics;
      if (path.endsWith("/changes")) return activity;
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    // "24" (requirement_count) legitimately also appears as the donut
    // chart's centre total, since it equals the sum of
    // requirements_by_status — scope to the metrics tile specifically
    // rather than assuming a single match.
    await expect(canvas.getByText("Requirements").previousSibling).toHaveTextContent("24");
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
  },
};

export const LoadError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(403, "You do not have access to this project."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("You do not have access to this project.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Dashboard, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Dashboard, globals: { theme: "dark" } };
