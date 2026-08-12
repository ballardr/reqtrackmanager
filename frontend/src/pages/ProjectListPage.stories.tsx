import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { buildProjectListItem, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { ProjectListPage } from "./ProjectListPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    ...overrides,
  };
}

const singleOrgProjects = [
  buildProjectListItem({ id: "p1", name: "Atlas Platform", organization_id: "org-1", organization_name: "Acme Corp" }),
  buildProjectListItem({ id: "p2", name: "Beacon Mobile", organization_id: "org-1", organization_name: "Acme Corp", is_favorite: true }),
];

function mockProjectListApis(opts: { orgs: Organization[]; projects: ReturnType<typeof buildProjectListItem>[] }) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/orgs?mine=true")) return opts.orgs;
    if (path.startsWith("/api/v1/projects?archived=false") && !path.includes("limit")) return opts.projects;
    return opts.projects;
  });
  spyOn(api, "getPage").mockResolvedValue({ items: opts.projects, total: opts.projects.length });
}

const meta: Meta<typeof ProjectListPage> = {
  title: "Pages/ProjectListPage",
  component: ProjectListPage,
  decorators: [withStatefulAuth(buildUser({ is_server_admin: false })), withRouter("/projects")],
};
export default meta;

type Story = StoryObj<typeof ProjectListPage>;

export const SingleOrgTilesView: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    // A single org: the org filter dropdown and per-card org name are both hidden.
    await expect(canvas.queryByText("Acme Corp")).not.toBeInTheDocument();
  },
};

export const MultipleOrgsShowOrgColumnAndFilter: Story = {
  beforeEach: () =>
    mockProjectListApis({
      orgs: [org({ id: "org-1", name: "Acme Corp" }), org({ id: "org-2", name: "Beta Inc" })],
      projects: singleOrgProjects,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("Acme Corp").length).toBeGreaterThan(0));
    await expect(canvas.getByText("All organisations")).toBeInTheDocument();
  },
};

export const ListView: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockProjectListApis({ orgs: [org({})], projects: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No projects to show.")).toBeInTheDocument());
  },
};

export const CreateProjectFormOpens: Story = {
  beforeEach: () => {
    mockProjectListApis({ orgs: [org({})], projects: singleOrgProjects });
    spyOn(api, "post").mockResolvedValue({ id: "new-project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Atlas Platform")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New project/ }));
    const createButton = canvas.getByRole("button", { name: "Create" });
    await expect(createButton).toBeDisabled();
    await userEvent.type(canvas.getByPlaceholderText("Name"), "New Project");
    await expect(createButton).toBeEnabled();
  },
};

export const LightTheme: Story = { ...SingleOrgTilesView, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SingleOrgTilesView, globals: { theme: "dark" } };
