import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Category, Component, ProjectStage } from "../api/types";
import { buildProjectListItem, buildRequirement, buildUser, withRouter, withStatefulAuth, withTerminology } from "../testing/storybook-helpers";
import { RequirementsPage } from "./RequirementsPage";

const PROJECT_ID = "project-1";

const components: Component[] = [
  { id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 },
  { id: "c2", project_id: PROJECT_ID, name: "Reporting", prefix: "RPT", sort_order: 1 },
];
const categories: Category[] = [
  { id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 },
  { id: "cat2", project_id: PROJECT_ID, component_id: "c2", name: "Export", prefix: "EXP", sort_order: 0 },
];
const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Build", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];

function mockRequirementsListApis(myRoles: "manager" | "member", opts: { components?: Component[]; categories?: Category[] } = {}) {
  const comps = opts.components ?? components;
  const cats = opts.categories ?? categories;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("archived=false")) return [buildProjectListItem({ id: PROJECT_ID, my_roles: myRoles === "manager" ? ["project_manager"] : ["member"] })];
    if (path.includes("/components")) return comps;
    if (path.includes("/categories")) return cats;
    if (path.includes("/stages")) return stages;
    if (path.includes("custom-fields")) return [];
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1", name: "Atlas Platform" };
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockResolvedValue({
    items: [
      buildRequirement({ id: "r1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1", target_stage_id: "s1" }),
      buildRequirement({ id: "r2", unique_code: "RPT-EXP-002", name: "Nightly export", component_id: "c2", category_id: "cat2", target_stage_id: "s1", status: "approved" }),
    ],
    total: 2,
  });
}

const meta: Meta<typeof RequirementsPage> = {
  title: "Pages/RequirementsPage",
  component: RequirementsPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1" })),
    withTerminology(),
    withRouter(`/projects/${PROJECT_ID}/requirements`, "/projects/:projectId/requirements"),
  ],
};
export default meta;

type Story = StoryObj<typeof RequirementsPage>;

export const TilesView: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await expect(canvas.getByText("Nightly export")).toBeInTheDocument();
  },
};

export const ListView: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByRole("columnheader", { name: "ID" })).toBeInTheDocument();
  },
};

export const FilterByStatusBadge: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Reset password")).toBeInTheDocument());
    const [draftBadge] = canvas.getAllByText("Draft");
    await userEvent.click(draftBadge);
    const statusSelect = canvas.getByLabelText("Status");
    await expect(statusSelect).toHaveValue("draft");
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager");
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No requirements to show.")).toBeInTheDocument());
  },
};

/** No components/categories yet: a manager sees an inline quick-create
 * form directly on this page. */
export const NoComponentsManagerCanCreateInline: Story = {
  beforeEach: () => {
    mockRequirementsListApis("manager", { components: [], categories: [] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByText("This project has no components or categories yet.")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Prefix")).toBeInTheDocument();
  },
};

/** The same empty state for a plain member instead links to Project Admin
 * rather than offering an inline create form — `canManageProject` gates it. */
export const NoComponentsMemberSeesLinkToAdmin: Story = {
  beforeEach: () => {
    mockRequirementsListApis("member", { components: [], categories: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByRole("link", { name: "Add one in Project Admin before creating requirements." })).toBeInTheDocument());
    await expect(canvas.queryByPlaceholderText("Prefix")).not.toBeInTheDocument();
  },
};

/** Changing the component in the create form resets the category to the
 * first one belonging to the newly-selected component — the tree/cascade
 * rule from help/01-overview.md. */
export const CreateFormCascadesCategoryOnComponentChange: Story = {
  beforeEach: () => mockRequirementsListApis("manager"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByPlaceholderText("Name")).toBeInTheDocument());
    // "Category" also labels the filter sidebar's own select — the create
    // form's is the first of the two in DOM order.
    const componentSelect = canvas.getByLabelText("Component");
    const categorySelect = canvas.getAllByLabelText("Category")[0];
    await expect(categorySelect).toHaveValue("cat1");
    await userEvent.selectOptions(componentSelect, "c2");
    await expect(categorySelect).toHaveValue("cat2");
  },
};

export const LightTheme: Story = { ...TilesView, globals: { theme: "light" } };
export const DarkTheme: Story = { ...TilesView, globals: { theme: "dark" } };
