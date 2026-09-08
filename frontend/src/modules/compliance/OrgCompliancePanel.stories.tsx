import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgCompliancePanel } from "./OrgCompliancePanel";
import type { ProjectComplianceStatus } from "./types";

const ORG_ID = "org-1";

const STATUS_ROWS: ProjectComplianceStatus[] = [
  {
    project_compliance_id: "pc-1", project_id: "proj-1", project_name: "Alpha Bridge", standard_id: "std-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 10, not_applicable_count: 0,
    counts_by_status: { compliant: 10 }, compliance_percentage: 100,
    has_non_compliant: false, overall_compliance_state: "compliant", overall_approval_state: "approved",
  },
];

/**
 * Integration-style stories exercising the three-tab shell (Dashboard /
 * Compliance by standard / Outstanding) end to end — mirrors `Compliance
 * AdminPanel.stories.tsx`'s own composed-panel coverage. Every child
 * component below also has its own dedicated, isolated story file
 * (`OrgComplianceDashboard.stories.tsx`/`OrgComplianceStandardsPanel.
 * stories.tsx`/`OrgComplianceOutstandingPanel.stories.tsx`), so this file's
 * own job is just proving the tabs compose and switch correctly, not
 * re-covering each child's own internal behaviour.
 */
function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return [];
    if (path.endsWith("/pending-approvals")) return [];
    if (path.endsWith("/outstanding-required-actions")) return [];
    if (path.endsWith("/expiring-evidence")) return [];
    if (path.includes("/reviews-due")) return [];
    if (path.includes("/recent-activity")) return [];
    if (path.includes("/project-compliance")) return STATUS_ROWS;
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgCompliancePanel> = {
  title: "Modules/Compliance/OrgCompliancePanel",
  component: OrgCompliancePanel,
  decorators: [withRouter("/orgs/org-1/overview/compliance-overview"), withToast()],
  args: { orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OrgCompliancePanel>;

export const SwitchesBetweenTabs: Story = {
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Active compliance standards")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("tab", { name: "Compliance by standard" }));
    await waitFor(() => expect(canvas.getByRole("table")).toBeInTheDocument());
    await expect(within(canvas.getByRole("table")).getByText(/ISO-27001/)).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("tab", { name: "Outstanding" }));
    await waitFor(() => expect(canvas.getByText(/Non-compliant requirements/)).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("tab", { name: "Dashboard" }));
    await waitFor(() => expect(canvas.getByText("Active compliance standards")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...SwitchesBetweenTabs };
export const DarkTheme: Story = { ...SwitchesBetweenTabs, globals: { theme: "dark" } };
