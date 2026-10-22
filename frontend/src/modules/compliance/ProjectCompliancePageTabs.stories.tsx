import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectCompliancePage } from "./ProjectCompliancePage";

const PROJECT_ID = "proj-1";
const ROUTE = "/projects/:projectId/modules/compliance";

function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform" });
    if (path.endsWith("/users")) return [];
    if (path.includes("/project-compliance") || path.endsWith("/status") || path.endsWith("/evidence")) return [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

/** Which tab the Compliance page opens on, from the `?tab=` link (the evidence page's Back link uses it). */
const meta: Meta<typeof ProjectCompliancePage> = {
  title: "Modules/Compliance/ProjectCompliancePage/Tabs",
  component: ProjectCompliancePage,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectCompliancePage>;

export const TabParamOpensTheEvidenceTab: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/compliance?tab=evidence`, ROUTE)],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Evidence", selected: true })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Add evidence" })).toBeInTheDocument();
  },
};

export const UnknownTabParamFallsBackToStandards: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/compliance?tab=bogus`, ROUTE)],
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Standards", selected: true })).toBeInTheDocument());
  },
};
