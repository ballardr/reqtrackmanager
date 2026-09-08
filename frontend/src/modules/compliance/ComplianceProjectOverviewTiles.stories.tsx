import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter } from "../../testing/storybook-helpers";
import { ComplianceProjectOverviewTiles } from "./ComplianceProjectOverviewTiles";
import type { ProjectComplianceStatus } from "./types";

const meta: Meta<typeof ComplianceProjectOverviewTiles> = {
  title: "Modules/Compliance/ComplianceProjectOverviewTiles",
  component: ComplianceProjectOverviewTiles,
  args: { projectId: "project-1" },
  decorators: [withRouter("/projects/project-1", "/projects/:projectId")],
};
export default meta;

type Story = StoryObj<typeof ComplianceProjectOverviewTiles>;

const complianceStatus: ProjectComplianceStatus[] = [
  {
    project_compliance_id: "pc-1", project_id: "project-1", project_name: "Atlas Platform",
    standard_id: "standard-1", standard_reference: "ISO-27001", standard_name: "Corporate Security Standard",
    standard_version_id: "version-1", version_label: "v2.0", target_compliance_date: null,
    assigned_at: "2026-01-01T00:00:00Z", total_requirements: 20, applicable_count: 18, not_applicable_count: 2,
    counts_by_status: { compliant: 15, non_compliant: 1, in_progress: 2 }, compliance_percentage: 83,
    has_non_compliant: true, overall_compliance_state: "in_progress", overall_approval_state: "not_assessed",
  },
];

// The `ProjectOverviewPage.tsx` integration this used to live in as a
// `WithCompliance` story before the module boundary cleanup (2026-09-08) —
// moved here since fetching/rendering compliance status is now this
// component's own responsibility, registered generically via `module.ts`'s
// `projectOverviewTiles`.
export const OneStandard: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/modules/compliance/status")) return complianceStatus;
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Corporate Security Standard")).toBeInTheDocument();
    await expect(canvas.getByText("Corporate Security Standard").previousSibling).toHaveTextContent("83%");
    await expect(canvas.getByRole("link", { name: /Corporate Security Standard/ })).toHaveAttribute(
      "href", "/projects/project-1/modules/compliance"
    );
  },
};

// No standards assigned yet — renders nothing at all, rather than an
// empty/zero-value tile nobody asked to see.
export const NoStandardsAssigned: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/modules/compliance/status")) return [];
      throw new Error(`Unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};
