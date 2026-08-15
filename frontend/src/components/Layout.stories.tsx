import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization, Project, ProjectListItem, ServerSettings } from "../api/types";
import { ThemeProvider } from "../context/ThemeContext";
import { buildProject, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { Layout } from "./Layout";

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569",
  default_logo_file_id: null,
  default_header_title: "ReqTrack Manager",
  default_login_background_file_id: null,
  email_footer_company_name: null,
  email_footer_website: null,
  email_footer_address: null,
};

const ORG: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
};

const PROJECT: Project = buildProject({ id: "project-1", organization_id: "org-1" });

/** Routes every `api.get` call Layout's provider tree can make (branding,
 * terminology, favourites probe, notifications) to fixture data by path
 * prefix — Layout composes several providers each with their own fetch, so
 * a single path-matching mock is far more maintainable than one spy per
 * story. */
function mockLayoutApis() {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return SERVER_SETTINGS;
    if (path === "/api/v1/orgs") return [ORG];
    if (path === `/api/v1/projects/${PROJECT.id}`) return PROJECT;
    if (path === `/api/v1/orgs/${ORG.id}`) return ORG;
    if (path.startsWith("/api/v1/projects?")) return [] as ProjectListItem[];
    if (path === "/api/v1/notifications") return [];
    throw new Error(`unmocked path in Layout story: ${path}`);
  });
}

const withThemeProvider: Decorator = (Story) => <ThemeProvider>{Story()}</ThemeProvider>;

const meta: Meta<typeof Layout> = {
  title: "Components/Layout",
  component: Layout,
  args: { children: <div>Page content</div> },
  decorators: [withThemeProvider],
};
export default meta;

type Story = StoryObj<typeof Layout>;

export const LoggedOut: Story = {
  decorators: [withAuth(null), withRouter("/login")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Page content")).toBeInTheDocument();
    await expect(canvas.queryByRole("navigation")).not.toBeInTheDocument();
  },
};

export const LoggedInNoProject: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan", is_server_admin: false })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("navigation")).toBeInTheDocument();
    await expect(canvas.queryByText("Project")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Administration")).not.toBeInTheDocument();
  },
};

export const LoggedInWithProjectRoute: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter(`/projects/${PROJECT.id}/requirements`)],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Project")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Requirements" })).toHaveClass("active");
  },
};

export const ServerAdmin: Story = {
  decorators: [withAuth(buildUser({ display_name: "Sam Admin", is_server_admin: true })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Administration")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /Server management/ })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "dark" } };
