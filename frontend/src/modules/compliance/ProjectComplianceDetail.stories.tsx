import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ProjectComplianceDetail } from "./ProjectComplianceDetail";
import type { ProjectCompliance, ProjectComplianceStatus } from "./types";

const PROJECT_ID = "proj-1";
const ORG_ID = "org-1";

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
    total_requirements: 3, applicable_count: 3, not_applicable_count: 0,
    counts_by_status: { compliant: 2, in_progress: 1 },
    compliance_percentage: 66.7, has_non_compliant: false,
    overall_compliance_state: "in_progress", overall_approval_state: "not_assessed", ...overrides,
  };
}

/**
 * `ProjectComplianceDetail` renders `ApplicabilityTree`/`ReviewsPanel`
 * underneath its own header/status summary — every nested fetch (the
 * requirement tree, per-requirement assessments, reviews) is mocked to
 * resolve empty here so the drill-in settles cleanly without duplicating
 * `ApplicabilityTree.stories.tsx`'s own, deeper coverage of that behaviour
 * — the same "settle cleanly, don't duplicate" precedent
 * `StandardVersionsSection.stories.tsx` (the retired `StandardsPanel.
 * stories.tsx`'s successor, docs/compliance-module-plan.md Phase 18) set
 * for its own `VersionWorkspace` drill-in.
 */
function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/standards?")) return [{ id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001", description: "", issuing_organisation: null, owner_id: "u1", creator_id: "u1", is_archived: false, archived_at: null, archived_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }];
    if (path.includes("/versions")) return [{ id: "ver-1", standard_id: "std-1", version_number: 1, version_label: "v1.0", status: "published", effective_date: null, change_note: "", created_by: "u1", published_at: "2026-01-01T00:00:00Z", published_by: "u1", retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }];
    if (path.includes("/requirements")) return [];
    if (path.endsWith("/reviews")) return [];
    return [];
  });
  spyOn(api, "post").mockImplementation(async () => assignment({ is_archived: true, archived_at: "2026-02-01T00:00:00Z", archived_by: "user-1" }));
}

const meta: Meta<typeof ProjectComplianceDetail> = {
  title: "Modules/Compliance/ProjectComplianceDetail",
  component: ProjectComplianceDetail,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectComplianceDetail>;

export const ActiveAssignment: Story = {
  beforeEach: () => mockApis(),
  args: {
    orgId: ORG_ID, projectId: PROJECT_ID, assignment: assignment(), status: status(), orgUsers: [],
    onBack: () => {}, onArchiveToggled: () => {},
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/ISO-27001/)).toBeInTheDocument();
    await expect(canvas.getByText(/66.7%/)).toBeInTheDocument();
  },
};

export const ArchivedAssignment: Story = {
  beforeEach: () => mockApis(),
  args: {
    orgId: ORG_ID, projectId: PROJECT_ID,
    assignment: assignment({ is_archived: true, archived_at: "2026-02-01T00:00:00Z", archived_by: "user-1" }),
    status: null, orgUsers: [], onBack: () => {}, onArchiveToggled: () => {},
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/archived/i)).toBeInTheDocument());
  },
};

export const ArchiveFlow: Story = {
  beforeEach: () => mockApis(),
  args: {
    orgId: ORG_ID, projectId: PROJECT_ID, assignment: assignment(), status: status(), orgUsers: [],
    onBack: () => {}, onArchiveToggled: () => {},
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    const confirmDialog = await waitFor(() => body.getByRole("dialog"));
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/projects/${PROJECT_ID}/project-compliance/pc-1/archive`
    ));
  },
};

export const LightTheme: Story = { ...ActiveAssignment };
export const DarkTheme: Story = { ...ActiveAssignment, globals: { theme: "dark" } };
