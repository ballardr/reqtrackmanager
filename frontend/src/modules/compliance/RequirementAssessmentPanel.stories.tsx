import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildFileAsset, withToast } from "../../testing/storybook-helpers";
import { RequirementAssessmentPanel } from "./RequirementAssessmentPanel";
import type {
  ComplianceEvidence,
  ComplianceRequiredAction,
  ComplianceRequiredActionAssessment,
  ComplianceRequirementNode,
  ProjectComplianceRequirement,
} from "./types";

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
    if (path.includes("/users/search")) {
      const needle = new URLSearchParams(path.split("?")[1]).get("q")?.toLowerCase() ?? "";
      return { members: ORG_USERS.filter((u) => u.display_name.toLowerCase().includes(needle)), external: null };
    }
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

function evidence(overrides: Partial<ComplianceEvidence> = {}): ComplianceEvidence {
  return {
    id: "ev-1", project_id: PROJECT_ID, title: "Existing Access Review", description: "",
    issuing_organisation: null, issued_date: null, expiry_date: null,
    provided_by: "user-1", provided_at: "2026-01-01T00:00:00Z", notes: "", validity_state: "valid",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    linked_requirement_ids: [], linked_required_action_assessment_ids: [], ...overrides,
  };
}

/** Phase 33: the Evidence section's "link existing" `<select>` alongside its
 * new "Upload new evidence" create-and-link-and-attach flow. Distinct from
 * `mockApis` above since it needs to track evidence state (linked vs.
 * library-only) across requests, the same way `EvidencePanel.stories.tsx`'s
 * own `mockApis` does for its create flow. */
function mockEvidenceApis(pcrRow: ProjectComplianceRequirement) {
  let library: ComplianceEvidence[] = [evidence()];
  let linked: ComplianceEvidence[] = [];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/required-action-assessments")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.includes("/requirements/") && path.endsWith("/evidence")) return linked;
    if (path.endsWith("/evidence")) return library;
    if (path.endsWith("/history")) return [];
    return [];
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/evidence")) {
      const payload = body as { title: string };
      const created = evidence({ id: `ev-${library.length + 1}`, title: payload.title });
      library = [...library, created];
      return created;
    }
    if (path.endsWith("/requirement-links")) {
      const evidenceId = path.split("/evidence/")[1].split("/requirement-links")[0];
      const found = library.find((e) => e.id === evidenceId)!;
      const updated = { ...found, linked_requirement_ids: [...found.linked_requirement_ids, (body as { project_compliance_requirement_id: string }).project_compliance_requirement_id] };
      library = library.map((e) => (e.id === evidenceId ? updated : e));
      linked = [...linked, updated];
      return updated;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "postFile").mockImplementation(async (path: string) => {
    if (path.endsWith("/files")) return buildFileAsset({ id: "file-1", filename: "certificate.pdf" });
    throw new Error(`unmocked postFile: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async () => pcrRow);
}

const ORG_USERS: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
];

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

/** Phase 32 (compliance-module-plan.md): the required action's assignee
 * field is `AssigneePicker` (a `UserAutocomplete`, not a plain unfiltered
 * `<select>`) — searching narrows the org's users and picking one saves via
 * the same `updateRequiredActionAssessment` PATCH the old `<select>` used. */
export const RequiredActionAssigneeSearchAndAssign: Story = {
  beforeEach: () => mockApis(pcr()),
  args: { pcr: pcr(), orgUsers: ORG_USERS },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);
    const input = body.getByRole("combobox", { name: /Assignee for Complete access review/ });
    await userEvent.type(input, "jamie");
    await waitFor(() => expect(body.getByText("Jamie Lee")).toBeInTheDocument());
    await userEvent.click(body.getByText("Jamie Lee"));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/requirements/pcr-1/required-action-assessments/aa-1`,
      { assignee_id: "u2", due_date: null, notes: "" }
    ));
  },
};

/** Unassigning an already-assigned required action clears it the same way
 * the old `<select>`'s empty "Unassigned" option did. */
export const RequiredActionUnassign: Story = {
  beforeEach: () => mockApis(pcr(), [actionAssessment({ assignee_id: "u1" })]),
  args: { pcr: pcr(), orgUsers: ORG_USERS },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);
    await expect(body.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: /Unassign: Assignee for Complete access review/ }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/requirements/pcr-1/required-action-assessments/aa-1`,
      { assignee_id: null, due_date: null, notes: "" }
    ));
  },
};

/** Phase 33 (compliance-module-plan.md): the Evidence section's two paths
 * side by side — linking an already-existing library item via the
 * "Link existing evidence" `<select>`, and the new "Upload new evidence"
 * flow, which creates a fresh `Evidence` record (`EvidencePanel.tsx`'s own
 * reused `EvidenceFormModal`), auto-links it to this assessment with no
 * separate manual link step, then attaches a file to it via the same
 * `FileAttachmentList` mechanism `EvidencePanel.tsx` itself uses. */
export const EvidenceLinkExistingAndUploadNew: Story = {
  beforeEach: () => mockEvidenceApis(pcr()),
  args: { pcr: pcr() },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);

    await waitFor(() => expect(body.getByText("No evidence linked yet.")).toBeInTheDocument());

    // --- Link existing.
    await userEvent.selectOptions(body.getByLabelText("Link existing evidence"), "ev-1");
    await userEvent.click(body.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-1/requirement-links`,
      { project_compliance_requirement_id: "pcr-1" }
    ));
    await waitFor(() => expect(body.getByText("Existing Access Review")).toBeInTheDocument());

    // --- Upload new: create + auto-link + attach, one flow, no separate
    //     manual "link existing" step for the newly-created record.
    await userEvent.click(body.getByRole("button", { name: "Upload new evidence" }));
    const createDialog = await waitFor(() => body.getByRole("dialog", { name: "Add evidence" }));
    await userEvent.type(within(createDialog).getByLabelText("Evidence title"), "New Access Report");
    await userEvent.click(within(createDialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence`,
      expect.objectContaining({ title: "New Access Report" })
    ));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-2/requirement-links`,
      { project_compliance_requirement_id: "pcr-1" }
    ));

    const filesDialog = await waitFor(() => body.getByRole("dialog", { name: 'Attach files to "New Access Report"' }));
    const filesDialogScope = within(filesDialog);
    const file = new File(["data"], "certificate.pdf", { type: "application/pdf" });
    const input = filesDialog.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() => expect(api.postFile).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-2/files`, file
    ));
    await waitFor(() => expect(filesDialogScope.getByText("certificate.pdf")).toBeInTheDocument());
    await userEvent.click(filesDialogScope.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(body.getByText("New Access Report")).toBeInTheDocument());
  },
};

/** Phase 41 (compliance-module-plan.md): `EvidenceFormModal`'s create form
 * itself now stages a file before save, so attaching one there uploads it in
 * the same step and skips the old follow-up "Attach files to..." modal
 * entirely — a user who already attached a file at creation isn't asked
 * again, unlike `EvidenceLinkExistingAndUploadNew` above (no file staged),
 * which still falls back to that modal. */
export const EvidenceUploadNewWithFileSkipsFollowUpModal: Story = {
  beforeEach: () => mockEvidenceApis(pcr()),
  args: { pcr: pcr() },
  play: async ({ canvasElement }) => {
    void canvasElement;
    const body = within(document.body);

    await userEvent.click(body.getByRole("button", { name: "Upload new evidence" }));
    const createDialog = await waitFor(() => body.getByRole("dialog", { name: "Add evidence" }));
    const createDialogScope = within(createDialog);
    await userEvent.type(createDialogScope.getByLabelText("Evidence title"), "New Access Report");

    const file = new File(["data"], "certificate.pdf", { type: "application/pdf" });
    const input = createDialog.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(createDialogScope.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence`,
      expect.objectContaining({ title: "New Access Report" })
    ));
    await waitFor(() => expect(api.postFile).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-2/files`, file
    ));
    await expect(body.queryByRole("dialog", { name: 'Attach files to "New Access Report"' })).not.toBeInTheDocument();
    await waitFor(() => expect(body.getByText("New Access Report")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...NotAssessedYet };
export const DarkTheme: Story = { ...NotAssessedYet, globals: { theme: "dark" } };
