import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildProjectFile, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { ProjectFilesPage } from "./ProjectFilesPage";

const PROJECT_ID = "project-1";

const meta: Meta<typeof ProjectFilesPage> = {
  title: "Pages/ProjectFilesPage",
  component: ProjectFilesPage,
  decorators: [withRouter(`/projects/${PROJECT_ID}/files`, "/projects/:projectId/files")],
};
export default meta;

type Story = StoryObj<typeof ProjectFilesPage>;

/** All three origin sources (`GET /projects/{id}/files`'s `ProjectFileOut`)
 * rendered in one list, each with an "Origin" link back to whichever
 * requirement/action the file came from — a flat file list with no way to
 * tell where each file came from is exactly the gap this page closes. */
const PHOTO_DETAILS = {
  width_px: 4032, height_px: 3024, taken: "2026-10-12 14:03:11", camera: "Canon EOS 5D", description: "North gate, pump house",
  latitude: -33.866667, longitude: 151.21,
};

/** A picture's row has an info button that shows when it was taken, the camera, its description and where; other files have none. */
export const APictureShowsItsExifDetails: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [
        buildProjectFile({
          file: { id: "file-3", organization_id: "org-1", filename: "gate.jpg", content_type: "image/jpeg", size_bytes: 2048000, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-22T09:00:00Z" },
          source: "requirement_attachment", requirement_id: "requirement-2", requirement_unique_code: "SW-PERF-002", requirement_name: "Log all transitions",
        }),
        buildProjectFile({
          file: { id: "file-1", organization_id: "org-1", filename: "spec.pdf", content_type: "application/pdf", size_bytes: 204800, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-20T09:00:00Z" },
          source: "requirement_attachment", requirement_id: "requirement-1", requirement_unique_code: "SW-PERF-001", requirement_name: "Ship the widget",
        }),
      ],
      total: 2,
    });
    spyOn(api, "get").mockResolvedValue(PHOTO_DETAILS);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("gate.jpg")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Details of spec.pdf" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Details of gate.jpg" }));
    const popover = within(await within(document.body).findByRole("dialog"));
    await expect(await popover.findByText("Canon EOS 5D")).toBeInTheDocument();
    await expect(popover.getByText("-33.86667, 151.21000")).toBeInTheDocument();
  },
};

export const MixedSources: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [
        buildProjectFile({
          file: { id: "file-1", organization_id: "org-1", filename: "spec.pdf", content_type: "application/pdf", size_bytes: 204800, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-20T09:00:00Z" },
          source: "requirement_attachment",
          requirement_id: "requirement-1", requirement_unique_code: "SW-PERF-001", requirement_name: "Ship the widget",
        }),
        buildProjectFile({
          file: { id: "file-2", organization_id: "org-1", filename: "review-notes.docx", content_type: "application/msword", size_bytes: 51200, uploaded_by: "user-2", is_org_resource: false, confidential: false, created_at: "2026-08-21T09:00:00Z" },
          uploaded_by_display_name: "Jamie Lee",
          source: "action_attachment",
          requirement_id: null, requirement_unique_code: null, requirement_name: null,
          action_id: "action-1", action_unique_code: "ACT-001", action_title: "Review password reset flow",
        }),
        buildProjectFile({
          file: { id: "file-3", organization_id: "org-1", filename: "screenshot.png", content_type: "image/png", size_bytes: 1024, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-22T09:00:00Z" },
          source: "comment_attachment",
          requirement_id: "requirement-2", requirement_unique_code: "SW-PERF-002", requirement_name: "Log all transitions",
          comment_id: "comment-1",
        }),
      ],
      total: 3,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("spec.pdf")).toBeInTheDocument());
    await expect(canvas.getByText("review-notes.docx")).toBeInTheDocument();
    await expect(canvas.getByText("screenshot.png")).toBeInTheDocument();

    // Each row links back to its origin.
    await expect(canvas.getByRole("link", { name: "SW-PERF-001 — Ship the widget" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/requirements/requirement-1`
    );
    await expect(canvas.getByRole("link", { name: "ACT-001 — Review password reset flow" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/actions/action-1`
    );
    await expect(canvas.getByRole("link", { name: "SW-PERF-002 — Log all transitions" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/requirements/requirement-2`
    );

    // Uploader and human-readable size are shown per row.
    await expect(canvas.getByText("Jamie Lee")).toBeInTheDocument();
    await expect(canvas.getByText("200.0 KB")).toBeInTheDocument();
  },
};

/** U-P-06 pagination convention (same as `ProjectHistoryPage`'s "Load
 * more") — clicking it appends the next page rather than replacing the
 * first. */
export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      if (offset === 0) {
        return { items: [buildProjectFile({ file: { id: "file-1", organization_id: "org-1", filename: "first.txt", content_type: "text/plain", size_bytes: 10, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-20T09:00:00Z" } })], total: 2 };
      }
      return { items: [buildProjectFile({ file: { id: "file-2", organization_id: "org-1", filename: "second.txt", content_type: "text/plain", size_bytes: 20, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-21T09:00:00Z" } })], total: 2 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("first.txt")).toBeInTheDocument());
    const loadMore = canvas.getByRole("button", { name: /Load more/ });
    await userEvent.click(loadMore);
    await waitFor(() => expect(canvas.getByText("second.txt")).toBeInTheDocument());
    await expect(canvas.getByText("first.txt")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No files in this project yet.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...MixedSources, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MixedSources, globals: { theme: "dark" } };

/** Widening the list to the parent adds its files, labelled with the project, linking to the origin in that project. */
export const WidenedToTheParent: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/scope-options")) return { has_parents: true, has_children: false, truncated: false };
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      const own = buildProjectFile({
        file: { id: "file-1", organization_id: "org-1", filename: "own.pdf", content_type: "application/pdf", size_bytes: 10, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-20T09:00:00Z" },
        requirement_id: "requirement-1", requirement_unique_code: "SW-001", requirement_name: "Own requirement",
      });
      const parent = buildProjectFile({
        file: { id: "file-2", organization_id: "org-1", filename: "parent.pdf", content_type: "application/pdf", size_bytes: 10, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at: "2026-08-21T09:00:00Z" },
        requirement_id: "requirement-9", requirement_unique_code: "SW-009", requirement_name: "Parent requirement",
        from_project_id: "project-parent", from_project_name: "Platform", from_project_code: "PLAT",
      });
      const items = path.includes("project_scope=parents") ? [own, parent] : [own];
      return { items, total: items.length };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("own.pdf")).toBeInTheDocument());
    await expect(canvas.queryByText("parent.pdf")).not.toBeInTheDocument();
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Show records from" }), "parents");
    await expect(await canvas.findByText("parent.pdf")).toBeInTheDocument();
    await expect(canvas.getByText("From Platform")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "SW-009 — Parent requirement" })).toHaveAttribute(
      "href", "/projects/project-parent/requirements/requirement-9"
    );
  },
};
