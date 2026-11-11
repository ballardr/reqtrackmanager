import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrganizationFileProject, ProjectFile, ProjectFileUploader } from "../api/types";
import { buildProjectFile, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgFilesPage } from "./OrgFilesPage";

const ORG_ID = "org-1";

const meta: Meta<typeof OrgFilesPage> = {
  title: "Pages/OrgFilesPage",
  component: OrgFilesPage,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter(`/orgs/${ORG_ID}/files`, "/orgs/:orgId/files")],
};
export default meta;

type Story = StoryObj<typeof OrgFilesPage>;

const UPLOADERS: ProjectFileUploader[] = [
  { id: "user-1", display_name: "Alex Morgan" },
  { id: "user-2", display_name: "Jamie Lee" },
];
const PROJECTS: OrganizationFileProject[] = [
  { id: "project-1", name: "Alpha", code: "ALPHA", is_archived: false },
  { id: "project-2", name: "Beta", code: "BETA", is_archived: false },
];

function asset(id: string, filename: string, created_at = "2026-08-20T09:00:00Z") {
  return { id, organization_id: ORG_ID, filename, content_type: "text/plain", size_bytes: 10, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at };
}

function row(id: string, filename: string, project: OrganizationFileProject, overrides: Partial<ProjectFile> = {}): ProjectFile {
  return buildProjectFile({
    file: asset(id, filename), requirement_id: `requirement-${id}`, requirement_unique_code: `REQ-${id}`, requirement_name: `Needs ${filename}`,
    from_project_id: project.id, from_project_name: project.name, from_project_code: project.code, ...overrides,
  });
}

type Reply = { items: ProjectFile[]; total: number; truncated?: boolean };

/** Answers the page's reads: the filtered list (`POST …/files/search`), the uploader choices and the project choices. */
function mockServer(reply: Reply | ((path: string, body: Record<string, unknown>) => Reply)) {
  spyOn(api, "postPage").mockImplementation((async (path: string, body: Record<string, unknown>) =>
    typeof reply === "function" ? reply(path, body) : reply) as never);
  spyOn(api, "get").mockImplementation((async (path: string) => {
    if (path.includes("/files/uploaders")) return UPLOADERS;
    if (path.includes("/files/projects")) return PROJECTS;
    throw new Error(`unmocked path: ${path}`);
  }) as never);
}

/** Each row names its project and links to its record inside that project, whichever project the file is in. */
export const FilesOfSeveralProjects: Story = {
  beforeEach: () => {
    mockServer({ items: [row("1", "alpha-spec.txt", PROJECTS[0]), row("2", "beta-spec.txt", PROJECTS[1])], total: 2 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("alpha-spec.txt")).toBeInTheDocument());
    await expect(canvas.getByRole("heading", { level: 1, name: "Organisation files" })).toBeInTheDocument();
    await expect(canvas.getByRole("columnheader", { name: "Project" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/projects/project-1");
    await expect(canvas.getByRole("link", { name: "Beta" })).toHaveAttribute("href", "/projects/project-2");
    await expect(canvas.getByRole("link", { name: "REQ-2 — Needs beta-spec.txt" })).toHaveAttribute("href", "/projects/project-2/requirements/requirement-2");
    // The Project column replaces the "From <project>" label of a widened project list.
    await expect(canvas.queryByText("From Beta")).toBeNull();
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockServer({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No files in the projects you can open yet.")).toBeInTheDocument());
  },
};

/** The server's project limit is stated, with what to do about it. */
export const TruncatedList: Story = {
  beforeEach: () => {
    mockServer({ items: [row("1", "alpha-spec.txt", PROJECTS[0])], total: 1, truncated: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("first 250 projects");
  },
};

/** The project filter and the archived switch go to the server as body fields; the typed file name is in no URL. */
export const FiltersAreSentInTheBody: Story = {
  beforeEach: () => {
    mockServer({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const postPage = api.postPage as unknown as { mock: { calls: [string, Record<string, unknown>][] } };
    const last = () => postPage.mock.calls[postPage.mock.calls.length - 1];
    await canvas.findByText("No files in the projects you can open yet.");
    await expect(last()[1]).toMatchObject({ project_ids: [], include_archived: false });

    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Project" }), "project-2");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Include archived projects" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Search file names" }), "payroll");

    await waitFor(() => expect(last()[1]).toMatchObject({ project_ids: ["project-2"], include_archived: true, search: "payroll" }));
    await expect(postPage.mock.calls.some(([path]) => path.includes("payroll"))).toBe(false);
    await expect(await canvas.findByText("No files match these filters.")).toBeInTheDocument();
  },
};

/** "Load more" appends the next page of the organisation list. */
export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    mockServer((path) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      return { items: [row(`${offset}`, offset === 0 ? "first.txt" : "second.txt", PROJECTS[0])], total: 2 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("first.txt")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await waitFor(() => expect(canvas.getByText("second.txt")).toBeInTheDocument());
    await expect(canvas.getByText("first.txt")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...FilesOfSeveralProjects, globals: { theme: "light" } };
export const DarkTheme: Story = { ...FilesOfSeveralProjects, globals: { theme: "dark" } };
