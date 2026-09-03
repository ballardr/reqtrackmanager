import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ChangeEntry, ProjectMetrics } from "../api/types";
import { buildChangeEntry, buildProject, buildProjectListItem, withRouter, withTerminology } from "../testing/storybook-helpers";
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
      // No parent/children for this fixture — a plain top-level project,
      // so neither the breadcrumb nor the "Child of/Parent of" labels
      // render (see `WithHierarchy` below for the populated case).
      if (path.endsWith("/ancestors")) return [];
      if (path.endsWith("/children")) return [];
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

// Hierarchical projects (docs/decisions.md): a project with both a visible
// parent and visible children — pins the root-first ancestor breadcrumb
// (grandparent -> parent, this project's own name un-linked) and the
// reused `ProjectHierarchyLabels` "Child of"/"Parent of" lines rendering
// together on Project Overview for the first time.
export const WithHierarchy: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/metrics")) return metrics;
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors")) {
        return [
          { id: "grandparent-1", name: "Solstice Programme" },
          { id: "parent-1", name: "Atlas Platform" },
        ];
      }
      if (path.endsWith("/children")) {
        return [
          buildProjectListItem({ id: "child-1", name: "Atlas Mobile", parent_project_id: "project-1" }),
          buildProjectListItem({ id: "child-2", name: "Atlas Web", parent_project_id: "project-1" }),
        ];
      }
      return buildProject({
        id: "project-1", name: "Atlas Core", summary: "Core platform requirements.",
        parent_project_id: "parent-1", parent_project_name: "Atlas Platform",
      });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Atlas Core" legitimately renders twice — the `<h1>` and the
    // breadcrumb's own (un-linked) trailing segment.
    await expect(canvas.getAllByText("Atlas Core")).toHaveLength(2);
    // Breadcrumb: both ancestors linked, current project's own name last
    // and un-linked.
    await expect(canvas.getByRole("link", { name: "Solstice Programme" })).toBeInTheDocument();
    // "Atlas Platform" legitimately renders twice — once as the
    // breadcrumb's immediate-parent link, once as `ProjectHierarchyLabels`'
    // "Child of:" link just below the heading — both pointing at the same
    // parent project, so asserting the count confirms both spots render
    // rather than picking one arbitrarily via `getByRole`.
    await expect(canvas.getAllByRole("link", { name: "Atlas Platform" })).toHaveLength(2);
    // "Child of"/"Parent of" labels, reused from `ProjectHierarchyLabels`.
    await expect(canvas.getByText("Child of:")).toBeInTheDocument();
    await expect(canvas.getByText("Parent of:")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Atlas Mobile" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Atlas Web" })).toBeInTheDocument();
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
