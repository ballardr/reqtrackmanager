import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, within } from "storybook/test";

import type { ProjectListItem } from "../api/types";
import { ProjectHierarchyLabels } from "./ProjectHierarchyLabels";

function project(overrides: Partial<ProjectListItem>): ProjectListItem {
  return {
    id: "p1", organization_id: "org-1", name: "Project", summary: "", created_at: "", updated_at: "",
    is_archived: false, is_template: false, allow_member_change_requests: true, visibility: "only_specified",
    terminology: {}, status_id: "s1", parent_project_id: null, role_inheritance_mode: "none",
    role_inheritance_filter_role: null, can_be_parent: false, current_stage_name: null, current_stage_status: null,
    my_roles: [], is_favorite: false, organization_name: "Acme", requirement_count: 0, children: [],
    ...overrides,
  };
}

const meta: Meta<typeof ProjectHierarchyLabels> = {
  title: "Components/ProjectHierarchyLabels",
  component: ProjectHierarchyLabels,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof ProjectHierarchyLabels>;

export const NoRelationship: Story = {
  args: { project: project({}) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/Child of|Parent of/)).not.toBeInTheDocument();
  },
};

export const ChildOfVisibleParent: Story = {
  args: { project: project({ parent_project_id: "parent-1", parent_project_name: "Platform" }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Child of:")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Platform" })).toHaveAttribute("href", "/projects/parent-1");
  },
};

/** Server-side visibility redaction: a project can structurally have a
 * parent while the caller can't view it — parent_project_name/id are both
 * null in that case, and no "Child of:" line renders at all (no hint that
 * a hidden parent exists). */
export const HiddenParentRendersNothing: Story = {
  args: { project: project({ parent_project_id: null, parent_project_name: null }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Child of:")).not.toBeInTheDocument();
  },
};

export const ParentOfFewChildren: Story = {
  args: {
    project: project({
      children: [
        { id: "c1", name: "Authentication" },
        { id: "c2", name: "Billing" },
      ],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Parent of:")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Authentication" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Billing" })).toBeInTheDocument();
    await expect(canvas.queryByText(/view all/)).not.toBeInTheDocument();
  },
};

export const ParentOfManyChildrenTruncates: Story = {
  args: {
    project: project({
      id: "p1",
      children: Array.from({ length: 6 }, (_, i) => ({ id: `c${i}`, name: `Workstream ${i + 1}` })),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Workstream 1" })).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Workstream 4" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "(view all)" })).toHaveAttribute("href", "/projects/p1");
  },
};

export const BothChildAndParent: Story = {
  args: {
    project: project({
      parent_project_id: "parent-1", parent_project_name: "Platform",
      children: [{ id: "c1", name: "Sub-workstream" }],
    }),
  },
};

export const LightTheme: Story = { ...ChildOfVisibleParent, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ChildOfVisibleParent, globals: { theme: "dark" } };
