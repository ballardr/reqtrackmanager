import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, type MockInstance, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import { buildFieldCatalogue, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { buildForm, buildPackDetail } from "../testing/reportPackFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ReportPackPage } from "./ReportPackPage";

/** The editor of one pack, opened by URL for a project or for an organisation. */
const meta: Meta<typeof ReportPackPage> = {
  title: "Pages/ReportPackPage",
  component: ReportPackPage,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportPackPage>;

let getSpy: MockInstance<typeof api.get>;

function mockApis() {
  getSpy = spyOn(api, "get");
  getSpy.mockImplementation(async (path: string) => {
    if (path.endsWith("/report-packs/pack-1")) return buildPackDetail();
    if (path.endsWith("/report-layouts")) return [buildLayoutSummary()];
    if (path.endsWith("/report-layouts/fields")) return buildFieldCatalogue();
    if (path.endsWith("/report-catalogue")) return [];
    if (path.endsWith("/form")) return buildForm();
    throw new Error(`unmocked path: ${path}`);
  });
}

export const OpensAProjectPackFromItsUrl: Story = {
  decorators: [withRouter("/projects/project-1/report-packs/pack-1", "/projects/:projectId/report-packs/:packId")],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("heading", { name: "Handover pack" })).toBeInTheDocument();
    await expect(getSpy).toHaveBeenCalledWith("/api/v1/projects/project-1/report-packs/pack-1");
  },
};

export const OpensAnOrganisationPackFromItsUrl: Story = {
  decorators: [withRouter("/orgs/org-1/report-packs/pack-1", "/orgs/:orgId/report-packs/:packId")],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("heading", { name: "Handover pack" });
    await expect(getSpy).toHaveBeenCalledWith("/api/v1/orgs/org-1/report-packs/pack-1");
  },
};
