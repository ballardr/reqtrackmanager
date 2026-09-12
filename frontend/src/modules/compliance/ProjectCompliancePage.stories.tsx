import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectCompliancePage } from "./ProjectCompliancePage";
import type { ComplianceStandard, ComplianceStandardVersion, ProjectCompliance, ProjectComplianceStatus } from "./types";

const PROJECT_ID = "proj-1";
const ORG_ID = "org-1";

function project(): Project {
  return buildProject({ id: PROJECT_ID, organization_id: ORG_ID, name: "Atlas Platform" });
}

function assignment(overrides: Partial<ProjectCompliance> = {}): ProjectCompliance {
  return {
    id: "pc-1", project_id: PROJECT_ID, standard_version_id: "ver-1",
    assigned_at: "2026-01-01T00:00:00Z", assigned_by: "user-1", target_compliance_date: "2026-12-31",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

function status(overrides: Partial<ProjectComplianceStatus> = {}): ProjectComplianceStatus {
  return {
    project_compliance_id: "pc-1", project_id: PROJECT_ID, project_name: "Demo Project", standard_id: "std-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", standard_version_id: "ver-1", version_label: "v1.0",
    target_compliance_date: "2026-12-31", assigned_at: "2026-01-01T00:00:00Z",
    total_requirements: 10, applicable_count: 9, not_applicable_count: 1,
    counts_by_status: { compliant: 7, in_progress: 1, non_compliant: 1 },
    compliance_percentage: 77.8, has_non_compliant: true, not_yet_assessed: false,
    overall_compliance_state: "non_compliant", overall_approval_state: "assessed", ...overrides,
  };
}

/**
 * `ProjectCompliancePage` is the route component Phase 3's Tier A mechanism
 * mounts for the Compliance module — see `modules/registry.ts`. These
 * stories exercise the top-level Standards list and the "Assign standard"
 * flow; a drill-in into `ProjectComplianceDetail`'s own applicability
 * tree/reviews behaviour is exercised in that component's own story file,
 * not duplicated here — nested requirement/evidence/review fetches are
 * mocked to resolve empty so a drill-in story here settles cleanly, the
 * same "settle cleanly, don't duplicate coverage" approach
 * `StandardVersionsSection.stories.tsx` (the retired `StandardsPanel.
 * stories.tsx`'s successor, docs/compliance-module-plan.md Phase 18)
 * already established for its own `VersionWorkspace` drill-in.
 */
function mockApis(overrides: {
  assignments?: ProjectCompliance[];
  statuses?: ProjectComplianceStatus[];
  standards?: ComplianceStandard[];
  versions?: ComplianceStandardVersion[];
} = {}) {
  const assignments = overrides.assignments ?? [assignment()];
  const statuses = overrides.statuses ?? [status()];
  const standards = overrides.standards ?? [
    { id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001", description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in" as const, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  ];
  const versions = overrides.versions ?? [
    { id: "ver-2", standard_id: "std-1", version_number: 2, version_label: "v2.0", status: "published", effective_date: null, change_note: "", created_by: "user-1", published_at: "2026-01-01T00:00:00Z", published_by: "user-1", retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  ];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return project();
    if (path === `/api/v1/orgs/${ORG_ID}/users`) return [] as OrgUser[];
    if (path.includes("/project-compliance")) return assignments;
    if (path.endsWith("/status")) return statuses;
    if (path.endsWith("/non-compliant-requirements")) return [];
    if (path.endsWith("/pending-approvals")) return [];
    if (path.endsWith("/reviews-due")) return [];
    if (path.endsWith("/evidence")) return [];
    if (path.includes("/standards?")) return standards;
    if (path.includes("/versions")) return versions;
    if (path.includes("/requirements")) return [];
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/project-compliance")) {
      const payload = body as { standard_id: string; standard_version_id: string; target_compliance_date: string | null };
      return assignment({ id: "pc-new", standard_version_id: payload.standard_version_id, target_compliance_date: payload.target_compliance_date });
    }
    throw new Error(`unmocked POST: ${path}`);
  });
}

const meta: Meta<typeof ProjectCompliancePage> = {
  title: "Modules/Compliance/ProjectCompliancePage",
  component: ProjectCompliancePage,
  decorators: [withToast(), withRouter(`/projects/${PROJECT_ID}/modules/compliance`, "/projects/:projectId/modules/compliance")],
};
export default meta;

type Story = StoryObj<typeof ProjectCompliancePage>;

export const ListsAssignedStandards: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/ISO-27001/)).toBeInTheDocument());
    await expect(canvas.getByText(/77.8%/)).toBeInTheDocument();
  },
};

// Phase 31: a standard attached but never assessed must render "Unknown" in
// the Non-compliant column, never "No" (which would read as confirmed clean).
export const ListsUnassessedStandard: Story = {
  beforeEach: () =>
    mockApis({
      statuses: [
        status({
          has_non_compliant: false, not_yet_assessed: true, overall_compliance_state: "in_progress",
          compliance_percentage: 0, applicable_count: 9, counts_by_status: { not_started: 9 },
        }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Unknown")).toBeInTheDocument());
    expect(canvas.queryByText("No")).not.toBeInTheDocument();
  },
};

export const NoAssignmentsYet: Story = {
  beforeEach: () => mockApis({ assignments: [], statuses: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance standards assigned to this project yet.")).toBeInTheDocument());
  },
};

export const AssignStandardFlow: Story = {
  beforeEach: () => mockApis({ assignments: [], statuses: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("No compliance standards assigned to this project yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Assign standard" }));
    await waitFor(() => expect(body.getByLabelText("Standard")).toBeInTheDocument());
    await userEvent.selectOptions(body.getByLabelText("Standard"), "std-1");
    await waitFor(() => expect(body.getByLabelText("Standard version")).toBeInTheDocument());
    await userEvent.click(body.getByRole("button", { name: "Assign" }));

    // Phase 20: the default assignment path is now the project-scoped
    // endpoint (usable by a plain Project Manager), not the org-scoped
    // Compliance-Manager-only one.
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance`,
      { standard_id: "std-1", standard_version_id: "ver-2", target_compliance_date: null }
    ));
  },
};

export const DownloadReport: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["pdf"], { type: "application/pdf" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/ISO-27001/)).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/reports/pdf`
    ));
  },
};

export const LightTheme: Story = { ...ListsAssignedStandards };
export const DarkTheme: Story = { ...ListsAssignedStandards, globals: { theme: "dark" } };
