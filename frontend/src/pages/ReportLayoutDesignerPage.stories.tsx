import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, type MockInstance, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import { buildFieldCatalogue, buildLayoutDetail, buildWidgets, LAYOUT_TEXT, treeOf } from "../testing/reportLayoutFixtures";
import { buildProjectListItem, withRouter } from "../testing/storybook-helpers";
import { ReportLayoutDesignerPage } from "./ReportLayoutDesignerPage";

/** The designer of one layout, opened by URL for a project or for an organisation. */
const meta: Meta<typeof ReportLayoutDesignerPage> = {
  title: "Pages/ReportLayoutDesignerPage",
  component: ReportLayoutDesignerPage,
};
export default meta;

type Story = StoryObj<typeof ReportLayoutDesignerPage>;

/** The spy on `api.get` of the story running, for its play function to inspect. */
let getSpy: MockInstance<typeof api.get>;

function mockApis() {
  getSpy = spyOn(api, "get");
  getSpy.mockImplementation(async (path: string) => {
    if (path.endsWith("/report-layouts/layout-1")) return buildLayoutDetail();
    if (path.endsWith("/report-layouts/fields")) return buildFieldCatalogue();
    if (path.endsWith("/report-layouts/widgets")) return buildWidgets();
    if (path.startsWith("/api/v1/projects?")) return [buildProjectListItem({ id: "p1", name: "Atlas" })];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/text/format")) return { text: String((body as { tree: { source_text?: string } }).tree.source_text ?? "") };
    if (path.endsWith("/text/parse")) return { ok: true, tree: treeOf((body as { text: string }).text), errors: [] };
    throw new Error(`unmocked path: ${path}`);
  });
}

export const OpensAProjectLayoutFromItsUrl: Story = {
  decorators: [withRouter("/projects/project-1/report-layouts/layout-1", "/projects/:projectId/report-layouts/:layoutId")],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const editor = (await within(canvasElement).findByRole("textbox", { name: "Layout text" })) as HTMLTextAreaElement;
    await expect(editor.value).toBe(LAYOUT_TEXT);
    await expect(getSpy).toHaveBeenCalledWith("/api/v1/projects/project-1/report-layouts/layout-1");
  },
};

export const OpensAnOrganisationLayoutFromItsUrl: Story = {
  decorators: [withRouter("/orgs/org-1/report-layouts/layout-1", "/orgs/:orgId/report-layouts/:layoutId")],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("textbox", { name: "Layout text" });
    await expect(getSpy).toHaveBeenCalledWith("/api/v1/orgs/org-1/report-layouts/layout-1");
    // An organisation layout previews across the organisation's projects, so it lists them to choose from.
    await expect(getSpy).toHaveBeenCalledWith("/api/v1/projects?archived=false&organization_id=org-1");
  },
};
