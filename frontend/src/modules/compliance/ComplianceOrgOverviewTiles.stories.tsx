import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { ComplianceOrgOverviewTiles } from "./ComplianceOrgOverviewTiles";
import type { ProjectComplianceStatus } from "./types";

const meta: Meta<typeof ComplianceOrgOverviewTiles> = {
  title: "Modules/Compliance/ComplianceOrgOverviewTiles",
  component: ComplianceOrgOverviewTiles,
};
export default meta;

type Story = StoryObj<typeof ComplianceOrgOverviewTiles>;

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
];

// `useOrgComplianceStatus`'s cache is keyed per `orgId` and shared at the
// module level (mirroring `useComplianceNavVisibility.ts`'s own identical
// per-key cache) — each story below uses its own distinct `orgId` rather
// than sharing one, the same reason that sibling hook's own story file
// gives every story a fresh user id: two stories sharing one key would have
// the second silently reuse the first's cached result instead of
// exercising its own mock.

export const Populated: Story = {
  args: { orgId: "org-tiles-populated" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/project-compliance")) return STATUS_ROWS;
      throw new Error(`unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Overall org compliance")).toBeInTheDocument());
    // Weighted: (10*100% + 10*60%) / 20 applicable = 80%.
    await expect(canvas.getByText("80%")).toBeInTheDocument();
    await expect(canvas.getByText("Compliance standards in use")).toBeInTheDocument();
    await expect(canvas.getByText("Projects out of compliance")).toBeInTheDocument();
  },
};

// No project-compliance assignments at all — renders nothing, rather than
// an empty/zero-value tile nobody asked to see (same rule
// `ComplianceProjectOverviewTiles.tsx` already follows).
export const NoComplianceActivity: Story = {
  args: { orgId: "org-tiles-empty" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/project-compliance")) return [];
      throw new Error(`unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Overall org compliance")).not.toBeInTheDocument();
  },
};
