import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { StandardProjectsPanel } from "./StandardProjectsPanel";
import type { ComplianceStandard, ProjectComplianceStatus } from "./types";

const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
  description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
  creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const ROWS: ProjectComplianceStatus[] = [
  {
    project_compliance_id: "pc-1", project_id: "proj-1", project_name: "Alpha Bridge", standard_id: STANDARD.id,
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 10, not_applicable_count: 0,
    counts_by_status: { compliant: 10 }, compliance_percentage: 100,
    has_non_compliant: false, not_yet_assessed: false, overall_compliance_state: "compliant", overall_approval_state: "approved",
  },
  {
    project_compliance_id: "pc-2", project_id: "proj-2", project_name: "Beta Tunnel", standard_id: STANDARD.id,
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: null, assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 10, not_applicable_count: 0,
    counts_by_status: { compliant: 6, non_compliant: 2, in_progress: 2 }, compliance_percentage: 60,
    has_non_compliant: true, not_yet_assessed: false, overall_compliance_state: "non_compliant", overall_approval_state: "assessed",
  },
];

function mockApis(rows: ProjectComplianceStatus[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/project-summary")) return rows;
    throw new Error(`unmocked GET: ${path}`);
  });
}

/**
 * The standard workspace's "Projects" section (docs/compliance-module-
 * plan.md Phase 23) — reached from the Overview's "Projects"/"Compliant"
 * `MetricTile`s. A single standard's own project-assignment list, each row
 * drilling through to that project's own Compliance page.
 */
const meta: Meta<typeof StandardProjectsPanel> = {
  title: "Modules/Compliance/StandardProjectsPanel",
  component: StandardProjectsPanel,
  decorators: [withRouter(`/standards/${STANDARD.id}/projects`, "/standards/:standardId/projects"), withToast()],
  args: { orgId: STANDARD.organization_id, standard: STANDARD },
};
export default meta;

type Story = StoryObj<typeof StandardProjectsPanel>;

export const ListsAssignedProjects: Story = {
  beforeEach: () => mockApis(ROWS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Alpha Bridge" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Beta Tunnel" })).toBeInTheDocument();
  },
};

export const FilterByComplianceState: Story = {
  beforeEach: () => mockApis(ROWS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Beta Tunnel" })).toBeInTheDocument());

    await userEvent.selectOptions(canvas.getByLabelText("Compliance state"), "compliant");
    await waitFor(() => expect(canvas.queryByRole("link", { name: "Beta Tunnel" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Alpha Bridge" })).toBeInTheDocument();
  },
};

export const NoProjectsAssigned: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No projects match this filter.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsAssignedProjects };
export const DarkTheme: Story = { ...ListsAssignedProjects, globals: { theme: "dark" } };
