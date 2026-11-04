import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ProjectFile, ProjectFileUploader } from "../api/types";
import { localDayWindow } from "../utils/localDate";
import { buildProjectFile, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { ProjectFilesPage } from "./ProjectFilesPage";

const PROJECT_ID = "project-1";

const meta: Meta<typeof ProjectFilesPage> = {
  title: "Pages/ProjectFilesPage",
  component: ProjectFilesPage,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter(`/projects/${PROJECT_ID}/files`, "/projects/:projectId/files")],
};
export default meta;

type Story = StoryObj<typeof ProjectFilesPage>;

const UPLOADERS: ProjectFileUploader[] = [
  { id: "user-2", display_name: "Jamie Lee" },
  { id: "user-1", display_name: "Alex Morgan" },
];

function asset(id: string, filename: string, content_type: string, created_at = "2026-08-20T09:00:00Z", size_bytes = 10) {
  return { id, organization_id: "org-1", filename, content_type, size_bytes, uploaded_by: "user-1", is_org_resource: false, confidential: false, created_at };
}

/** Answers the page's three reads: the filtered list (`POST .../files/search`), the uploader choices and a picture's details. */
function mockServer(rows: ProjectFile[] | ((path: string, body: Record<string, unknown>) => { items: ProjectFile[]; total: number }), extraGet?: (path: string) => unknown) {
  spyOn(api, "postPage").mockImplementation((async (path: string, body: Record<string, unknown>) => {
    if (typeof rows === "function") return rows(path, body);
    return { items: rows, total: rows.length };
  }) as never);
  spyOn(api, "get").mockImplementation((async (path: string) => {
    if (path.includes("/files/uploaders")) return UPLOADERS;
    if (path.endsWith("/scope-options")) return { has_parents: false, has_children: false, truncated: false };
    const extra = extraGet?.(path);
    if (extra !== undefined) return extra;
    throw new Error(`unmocked path: ${path}`);
  }) as never);
}

/** The list shows every source in one list, each with an "Origin" link back to where the file came from, and a preview beside each name. */
export const MixedSources: Story = {
  beforeEach: () => {
    mockServer([
      buildProjectFile({
        file: asset("file-1", "spec.pdf", "application/pdf", "2026-08-20T09:00:00Z", 204800),
        source: "requirement_attachment", requirement_id: "requirement-1", requirement_unique_code: "SW-PERF-001", requirement_name: "Ship the widget",
      }),
      buildProjectFile({
        file: asset("file-2", "review-notes.docx", "application/msword", "2026-08-21T09:00:00Z", 51200),
        uploaded_by_display_name: "Jamie Lee", source: "action_attachment",
        requirement_id: null, requirement_unique_code: null, requirement_name: null,
        action_id: "action-1", action_unique_code: "ACT-001", action_title: "Review password reset flow",
      }),
      buildProjectFile({
        file: asset("file-3", "screenshot.png", "image/png", "2026-08-22T09:00:00Z", 1024),
        source: "comment_attachment", requirement_id: "requirement-2", requirement_unique_code: "SW-PERF-002", requirement_name: "Log all transitions", comment_id: "comment-1",
      }),
      buildProjectFile({
        file: asset("file-4", "company-logo.svg", "image/svg+xml", "2026-08-23T09:00:00Z", 2048),
        source: "report_image", requirement_id: null, requirement_unique_code: null, requirement_name: null,
      }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("spec.pdf")).toBeInTheDocument());
    await expect(canvas.getByText("review-notes.docx")).toBeInTheDocument();

    await expect(canvas.getByRole("link", { name: "SW-PERF-001 — Ship the widget" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/requirements/requirement-1`
    );
    await expect(canvas.getByRole("link", { name: "ACT-001 — Review password reset flow" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/actions/action-1`
    );
    await expect(canvas.getByRole("link", { name: "SW-PERF-002 — Log all transitions" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/requirements/requirement-2`
    );

    // A library picture is labelled by its source, links to report setup and is the one row with a preview.
    await expect(within(canvas.getByRole("table")).getByText("Report image library")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Report setup" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/admin/reportSetup`);

    // Pictures show a preview with the file name as its alt text; other files show an icon, not a picture.
    const logo = canvas.getByRole("img", { name: "company-logo.svg" });
    await expect(logo.getAttribute("src")).toContain("/api/v1/files/file-4");
    await expect(logo.getAttribute("loading")).toBe("lazy");
    await expect(canvas.getByRole("img", { name: "screenshot.png" })).toBeInTheDocument();
    await expect(canvas.queryByRole("img", { name: "spec.pdf" })).toBeNull();

    // Uploader and human-readable size are shown per row.
    await expect(canvas.getByText("Jamie Lee", { selector: "td" })).toBeInTheDocument();
    await expect(canvas.getByText("200.0 KB")).toBeInTheDocument();
  },
};

const PHOTO_DETAILS = {
  width_px: 4032, height_px: 3024, taken: "2026-10-12 14:03:11", camera: "Canon EOS 5D", description: "North gate, pump house",
  latitude: -33.866667, longitude: 151.21,
};

/** A picture's row has an info button that shows when it was taken, the camera, its description and where; other files have none. */
export const APictureShowsItsExifDetails: Story = {
  beforeEach: () => {
    mockServer(
      [
        buildProjectFile({
          file: asset("file-3", "gate.jpg", "image/jpeg", "2026-08-22T09:00:00Z", 2048000),
          source: "requirement_attachment", requirement_id: "requirement-2", requirement_unique_code: "SW-PERF-002", requirement_name: "Log all transitions",
        }),
        buildProjectFile({
          file: asset("file-1", "spec.pdf", "application/pdf", "2026-08-20T09:00:00Z", 204800),
          source: "requirement_attachment", requirement_id: "requirement-1", requirement_unique_code: "SW-PERF-001", requirement_name: "Ship the widget",
        }),
      ],
      (path) => (path.endsWith("/details") ? PHOTO_DETAILS : undefined),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "gate.jpg" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Details of spec.pdf" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Details of gate.jpg" }));
    const popover = within(await within(document.body).findByRole("dialog"));
    await expect(await popover.findByText("Canon EOS 5D")).toBeInTheDocument();
    await expect(popover.getByText("-33.86667, 151.21000")).toBeInTheDocument();
  },
};

/** A picture the browser cannot draw falls back to the file icon instead of a broken image. */
export const AnUnreadablePictureFallsBackToAnIcon: Story = {
  beforeEach: () => {
    mockServer([buildProjectFile({ file: asset("file-9", "broken.png", "image/png"), source: "report_image", requirement_id: null })]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const picture = await canvas.findByRole("img", { name: "broken.png" });
    picture.dispatchEvent(new Event("error"));
    await waitFor(() => expect(canvas.queryByRole("img", { name: "broken.png" })).toBeNull());
    await expect(canvas.getByRole("link", { name: "broken.png" })).toBeInTheDocument();
  },
};

/** A very long file name wraps inside its cell rather than widening the page. */
export const ALongFileNameWraps: Story = {
  beforeEach: () => {
    mockServer([
      buildProjectFile({ file: asset("file-8", `${"quarterly-site-inspection-photographs-".repeat(4)}final.pdf`, "application/pdf") }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: /quarterly-site-inspection-photographs-.*final\.pdf/ });
    await expect(getComputedStyle(link).overflowWrap).toBe("anywhere");
  },
};

/** U-P-06 pagination convention (same as `ProjectHistoryPage`'s "Load more") — clicking it appends the next page rather than replacing the first. */
export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    mockServer((path) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      const name = offset === 0 ? "first.txt" : "second.txt";
      return { items: [buildProjectFile({ file: asset(`file-${offset}`, name, "text/plain") })], total: 2 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("first.txt")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await waitFor(() => expect(canvas.getByText("second.txt")).toBeInTheDocument());
    await expect(canvas.getByText("first.txt")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockServer([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No files in this project yet.")).toBeInTheDocument());
  },
};

/** Each filter goes to the server as a body field, the typed file name is in no URL, and the filter panel sits level with the title. */
export const FiltersAreSentInTheBodyAndKeptInTheUrl: Story = {
  beforeEach: () => {
    mockServer((_path, body) => {
      const hit = body.search === "logo";
      const items = hit ? [buildProjectFile({ file: asset("file-4", "company-logo.png", "image/png"), source: "report_image", requirement_id: null })] : [];
      return { items, total: items.length };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const postPage = api.postPage as unknown as { mock: { calls: [string, Record<string, unknown>][] } };
    const last = () => postPage.mock.calls[postPage.mock.calls.length - 1];
    await canvas.findByText("No files in this project yet.");

    await userEvent.type(canvas.getByRole("textbox", { name: "Search file names" }), "logo");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Source" }), "report_image");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "File type" }), "image");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Uploaded by" }), "user-2");
    await userEvent.type(canvas.getByLabelText("Uploaded from"), "2026-11-03");
    await userEvent.type(canvas.getByLabelText("Uploaded to"), "2026-11-04");

    await waitFor(() => expect(last()[1]).toMatchObject({ search: "logo", sources: ["report_image"], kind: "image", uploaded_by: "user-2" }));
    const window = localDayWindow("2026-11-03", "2026-11-04");
    await expect(last()[1].uploaded_from).toBe(window.from);
    await expect(last()[1].uploaded_before).toBe(window.before);
    // The text typed is in the body only: no request URL carries it.
    await expect(postPage.mock.calls.some(([path]) => path.includes("logo"))).toBe(false);
    await expect(await canvas.findByText("company-logo.png")).toBeInTheDocument();

    // Clearing the search shows the "no match" wording for the remaining filters.
    await userEvent.clear(canvas.getByRole("textbox", { name: "Search file names" }));
    await expect(await canvas.findByText("No files match these filters.")).toBeInTheDocument();
  },
};

/** The upload window covers whole local days: from the first moment of the first day to the first moment of the day after the last. */
export const TheUploadWindowIsWholeLocalDays: Story = {
  render: () => <p>Local-day window</p>,
  play: async () => {
    const { from, before } = localDayWindow("2026-11-04", "2026-11-04");
    const start = new Date(from ?? "");
    const end = new Date(before ?? "");
    await expect([start.getFullYear(), start.getMonth(), start.getDate(), start.getHours(), start.getMinutes()]).toEqual([2026, 10, 4, 0, 0]);
    await expect([end.getFullYear(), end.getMonth(), end.getDate(), end.getHours(), end.getMinutes()]).toEqual([2026, 10, 5, 0, 0]);
    await expect(from).toMatch(/Z$/);
    await expect(localDayWindow("", "")).toEqual({ from: undefined, before: undefined });
  },
};

export const LightTheme: Story = { ...MixedSources, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MixedSources, globals: { theme: "dark" } };

/** Widening the list to the parent adds its files, labelled with the project, linking to the origin in that project. */
export const WidenedToTheParent: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation((async (path: string) => {
      if (path.endsWith("/scope-options")) return { has_parents: true, has_children: false, truncated: false };
      if (path.includes("/files/uploaders")) return UPLOADERS;
      throw new Error(`unmocked path: ${path}`);
    }) as never);
    spyOn(api, "postPage").mockImplementation((async (path: string) => {
      const own = buildProjectFile({
        file: asset("file-1", "own.pdf", "application/pdf"), requirement_id: "requirement-1", requirement_unique_code: "SW-001", requirement_name: "Own requirement",
      });
      const parent = buildProjectFile({
        file: asset("file-2", "parent.pdf", "application/pdf", "2026-08-21T09:00:00Z"),
        requirement_id: "requirement-9", requirement_unique_code: "SW-009", requirement_name: "Parent requirement",
        from_project_id: "project-parent", from_project_name: "Platform", from_project_code: "PLAT",
      });
      const items = path.includes("project_scope=parents") ? [own, parent] : [own];
      return { items, total: items.length };
    }) as never);
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
