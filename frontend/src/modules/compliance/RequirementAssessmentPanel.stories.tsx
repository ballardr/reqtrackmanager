import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { RequirementAssessmentPanel } from "./RequirementAssessmentPanel";
import type { ComplianceRequiredAction, ComplianceRequiredActionAssessment, ComplianceRequirementNode, ProjectComplianceRequirement } from "./types";

const ORG_ID = "org-1";
const PROJECT_ID = "proj-1";
const STANDARD_ID = "std-1";
const VERSION_ID = "ver-1";
const PC_ID = "pc-1";

const REQUIREMENT: ComplianceRequirementNode = {
  id: "req-1", standard_version_id: VERSION_ID, parent_requirement_id: null,
  reference: "A.5.15", name: "Access control", description: "Restrict access to information.", reasoning: "", sort_order: 0,
  created_by: "u1", clarification_count: 0, last_clarified_at: null, last_clarified_by: null, last_clarification_note: "",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", depth: 0, children: [],
};

function pcr(overrides: Partial<ProjectComplianceRequirement> = {}): ProjectComplianceRequirement {
  return {
    id: "pcr-1", project_compliance_id: PC_ID, requirement_id: "req-1",
    explicit_applicability: null, effective_applicability: "applicable", applicability_source: "explicit",
    justification: "", notes: "", compliance_status: "in_progress", assessed_at: null, assessed_by: null,
    applicability_set_at: null, applicability_set_by: null, approval_state: "not_assessed",
    approval_decided_at: null, approval_decided_by: null, decision_note: "",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

const ACTION_DEF: ComplianceRequiredAction = {
  id: "act-1", requirement_id: "req-1", action_type_id: "at-1", name: "Complete access review", description: "",
  is_mandatory: true, sort_order: 0, created_by: "u1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

function actionAssessment(overrides: Partial<ComplianceRequiredActionAssessment> = {}): ComplianceRequiredActionAssessment {
  return {
    id: "aa-1", project_compliance_requirement_id: "pcr-1", required_action_id: "act-1",
    assignee_id: null, due_date: null, is_completed: false, completed_at: null, completed_by: null, notes: "",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * The per-requirement assessment `SidePanel` — §9 applicability, §10/§16
 * assessment, §6 required actions, §13 evidence linkage, and §12 approval/
 * sign-off, all for one requirement. Each section's own mandatory-
 * justification UI convenience (disabling Save until filled) is exercised
 * alongside the underlying API call each control makes.
 */
function mockApis(pcrRow: ProjectComplianceRequirement, assessments: ComplianceRequiredActionAssessment[] = [actionAssessment()]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/required-action-assessments")) return assessments;
    if (path.includes("/required-actions")) return [ACTION_DEF];
    if (path.endsWith("/evidence")) return [];
    if (path.endsWith("/history")) return [
      { id: "ev-1", entity_type: "project_compliance_requirement", entity_id: "pcr-1", action: "assessed", actor_id: "user-1", detail: null, created_at: "2026-01-05T00:00:00Z" },
    ];
    return [];
  });
  spyOn(api, "patch").mockImplementation(async () => pcrRow);
  spyOn(api, "post").mockImplementation(async (path: string) => {
    if (path.endsWith("/submit-for-approval")) return { ...pcrRow, approval_state: "pending_approval" };
    if (path.endsWith("/approve")) return { ...pcrRow, approval_state: "approved" };
    if (path.endsWith("/reject")) return { ...pcrRow, approval_state: "rejected" };
    return pcrRow;
  });
}

const meta: Meta<typeof RequirementAssessmentPanel> = {
  title: "Modules/Compliance/RequirementAssessmentPanel",
  component: RequirementAssessmentPanel,
  decorators: [withToast()],
  args: {
    orgId: ORG_ID, projectId: PROJECT_ID, standardId: STANDARD_ID, versionId: VERSION_ID, projectComplianceId: PC_ID,
    requirement: REQUIREMENT, orgUsers: [], onClose: () => {}, onChanged: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof RequirementAssessmentPanel>;

export const NotAssessedYet: Story = {
  beforeEach: () => mockApis(pcr()),
  args: { pcr: pcr() },
  play: async ({ canvasElement }) => {
    const body = within(document.body);
    void canvasElement;
    await expect(body.getByRole("heading", { name: /Access control/ })).toBeInTheDocument();
    await expect(body.getByText("Complete access review")).toBeInTheDocument();
  },
};

export const MarkNonCompliantRequiresJustification: Story = {
  beforeEach: () => mockApis(pcr()),
  args: { pcr: pcr() },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Compliance status"), "non_compliant");
    const saveButton = body.getByRole("button", { name: "Update assessment" });
    await expect(saveButton).toBeDisabled();
    await userEvent.type(body.getByLabelText("Justification (required)"), "Missing MFA on admin accounts.");
    await expect(saveButton).toBeEnabled();
    await userEvent.click(saveButton);
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/requirements/pcr-1/assessment`,
      { compliance_status: "non_compliant", justification: "Missing MFA on admin accounts.", notes: "" }
    ));
  },
};

export const PendingApprovalCanApproveOrReject: Story = {
  beforeEach: () => mockApis(pcr({ approval_state: "pending_approval" })),
  args: { pcr: pcr({ approval_state: "pending_approval" }) },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    await expect(body.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/requirements/pcr-1/approve`,
      { decision_note: "" }
    ));
  },
};

export const RejectRequiresDecisionNote: Story = {
  beforeEach: () => mockApis(pcr({ approval_state: "pending_approval" })),
  args: { pcr: pcr({ approval_state: "pending_approval" }) },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);
    await userEvent.click(body.getByRole("button", { name: "Reject" }));
    const dialog = await waitFor(() => body.getByRole("dialog", { name: "Reject this assessment?" }));
    const dialogScope = within(dialog);
    const rejectButton = dialogScope.getByRole("button", { name: "Reject" });
    await expect(rejectButton).toBeDisabled();
    await userEvent.type(dialogScope.getByLabelText("Decision note (required)"), "Evidence does not support this control.");
    await expect(rejectButton).toBeEnabled();
    await userEvent.click(rejectButton);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/requirements/pcr-1/reject`,
      { decision_note: "Evidence does not support this control." }
    ));
  },
};

export const LightTheme: Story = { ...NotAssessedYet };
export const DarkTheme: Story = { ...NotAssessedYet, globals: { theme: "dark" } };
