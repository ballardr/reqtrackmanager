import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgComplianceStandardsPanel } from "./OrgComplianceStandardsPanel";
import type { ProjectComplianceStatus } from "./types";

const ORG_ID = "org-1";

const STATUS_ROWS: ProjectComplianceStatus[] = [
  {
    project_compliance_id: "pc-1", project_id: "proj-1", project_name: "Alpha Bridge", standard_id: "std-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 10, not_applicable_count: 0,
    counts_by_status: { compliant: 10 }, compliance_percentage: 100,
    has_non_compliant: false, not_yet_assessed: false, overall_compliance_state: "compliant", overall_approval_state: "approved",
  },
  {
    project_compliance_id: "pc-2", project_id: "proj-2", project_name: "Beta Tunnel", standard_id: "std-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 10, not_applicable_count: 0,
    counts_by_status: { compliant: 6, non_compliant: 2, in_progress: 2 }, compliance_percentage: 60,
    has_non_compliant: true, not_yet_assessed: false, overall_compliance_state: "non_compliant", overall_approval_state: "assessed",
  },
  {
    project_compliance_id: "pc-3", project_id: "proj-2", project_name: "Beta Tunnel", standard_id: "std-2",
    standard_reference: "EMC-1", standard_name: "EMC/EMF Standard", standard_version_id: "ver-2", version_label: "v2.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 5, applicable_count: 5, not_applicable_count: 0,
    counts_by_status: { in_progress: 5 }, compliance_percentage: 40,
    has_non_compliant: false, not_yet_assessed: false, overall_compliance_state: "in_progress", overall_approval_state: "not_assessed",
  },
];

function mockApis(rows: ProjectComplianceStatus[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/project-compliance")) return rows;
    throw new Error(`unmocked GET: ${path}`);
  });
}

const DEFAULT_PATH = "/orgs/org-1/overview/compliance-by-standard";

const meta: Meta<typeof OrgComplianceStandardsPanel> = {
  title: "Modules/Compliance/OrgComplianceStandardsPanel",
  component: OrgComplianceStandardsPanel,
  decorators: [withToast()],
  args: { orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OrgComplianceStandardsPanel>;

export const GroupedByStandard: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
  beforeEach: () => mockApis(STATUS_ROWS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("table")).toBeInTheDocument());
    const table = within(canvas.getByRole("table"));
    await expect(table.getByText(/ISO-27001 — ISO 27001/)).toBeInTheDocument();
    await expect(table.getByText(/EMC-1 — EMC\/EMF Standard/)).toBeInTheDocument();

    // Drilling down expands the underlying projects.
    await userEvent.click(canvas.getByRole("button", { name: /Expand projects for ISO-27001/ }));
    await waitFor(() => expect(table.getByRole("link", { name: "Alpha Bridge" })).toBeInTheDocument());
    await expect(table.getByRole("link", { name: "Beta Tunnel" })).toBeInTheDocument();
  },
};

export const FilterByProject: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
  beforeEach: () => mockApis(STATUS_ROWS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("table")).toBeInTheDocument());
    let table = within(canvas.getByRole("table"));
    await expect(table.getByText(/ISO-27001/)).toBeInTheDocument();

    await userEvent.selectOptions(canvas.getByLabelText("Project"), "proj-1");
    table = within(canvas.getByRole("table"));
    await waitFor(() => expect(table.queryByText(/EMC-1/)).not.toBeInTheDocument());
    await expect(table.getByText(/ISO-27001/)).toBeInTheDocument();
  },
};

/** Phase 36 — the "Group by" pivot, and its URL-driven initial state
 * (`?groupBy=project&state=non_compliant`) so `OrgComplianceDashboard.tsx`'s
 * "Non-compliant projects" tile can link straight into a pre-filtered,
 * project-pivoted view. */
export const GroupedByProjectViaUrl: Story = {
  decorators: [withRouter(`${DEFAULT_PATH}?groupBy=project&state=non_compliant`)],
  beforeEach: () => mockApis(STATUS_ROWS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("table")).toBeInTheDocument());
    const table = within(canvas.getByRole("table"));
    // Only Beta Tunnel has a non-compliant row (its ISO-27001 assignment) —
    // Alpha Bridge (compliant) and Beta Tunnel's own EMC-1 (in-progress) are
    // filtered out, and the grouping key is the project, not the standard.
    await expect(table.getByText(/Beta Tunnel/)).toBeInTheDocument();
    await expect(table.queryByText(/Alpha Bridge/)).not.toBeInTheDocument();
    await expect(table.queryByText(/EMC-1/)).not.toBeInTheDocument();
    await expect(canvas.getByRole("columnheader", { name: "Project" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: /Expand standards for Beta Tunnel/ }));
    await waitFor(() => expect(table.getByText(/ISO-27001 — ISO 27001/)).toBeInTheDocument());
  },
};

export const NoAssignments: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/No compliance assignments match/)).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...GroupedByStandard };
export const DarkTheme: Story = { ...GroupedByStandard, globals: { theme: "dark" } };
