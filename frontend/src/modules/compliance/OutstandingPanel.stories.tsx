import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OutstandingPanel } from "./OutstandingPanel";
import type { ComplianceReview, NonCompliantRequirement, OutstandingRequiredAction, PendingApproval } from "./types";

const PROJECT_ID = "proj-1";

/**
 * §21's "make it easy... to determine what remains outstanding" — the
 * four cross-assignment listings (Non-Compliant, Pending Approval,
 * Outstanding Required Actions — added Phase 14 — and Reviews Due/Overdue)
 * gathered in one read-only view. Acting on a row happens via the
 * Standards tab (`ApplicabilityTree`/`ReviewsPanel`), not here.
 */
function mockApis(
  nonCompliant: NonCompliantRequirement[],
  pending: PendingApproval[],
  outstandingActions: OutstandingRequiredAction[],
  reviewsDue: ComplianceReview[]
) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return nonCompliant;
    if (path.endsWith("/pending-approvals")) return pending;
    if (path.endsWith("/outstanding-required-actions")) return outstandingActions;
    if (path.endsWith("/reviews-due")) return reviewsDue;
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OutstandingPanel> = {
  title: "Modules/Compliance/OutstandingPanel",
  component: OutstandingPanel,
  decorators: [withToast()],
  args: { projectId: PROJECT_ID },
};
export default meta;

type Story = StoryObj<typeof OutstandingPanel>;

const NON_COMPLIANT: NonCompliantRequirement[] = [
  {
    project_compliance_id: "pc-1", standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", justification: "Missing MFA on admin accounts.", notes: "",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const PENDING: PendingApproval[] = [
  {
    project_compliance_id: "pc-1", standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-2", requirement_id: "req-2", requirement_reference: "A.5.16",
    requirement_name: "Identity management", compliance_status: "compliant",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const OUTSTANDING_ACTIONS: OutstandingRequiredAction[] = [
  {
    project_id: PROJECT_ID, project_name: "Demo Project", project_compliance_id: "pc-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", required_action_assessment_id: "raa-1", required_action_id: "ra-1",
    required_action_name: "Enable MFA for admin accounts", is_mandatory: true,
    assignee_id: "user-1", due_date: "2026-10-01", notes: "",
  },
];

const REVIEWS_DUE: ComplianceReview[] = [
  {
    id: "rev-1", standard_id: null, project_compliance_id: "pc-1", frequency_label: "Annual security review",
    recurrence_days: 365, next_due_date: "2026-09-01", owner_id: null, status: "scheduled", schedule_state: "overdue",
    notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [],
  },
];

export const WithOutstandingItems: Story = {
  beforeEach: () => mockApis(NON_COMPLIANT, PENDING, OUTSTANDING_ACTIONS, REVIEWS_DUE),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Missing MFA on admin accounts/)).toBeInTheDocument());
    await expect(canvas.getByText(/Identity management/)).toBeInTheDocument();
    await expect(canvas.getByText(/Enable MFA for admin accounts/)).toBeInTheDocument();
    await expect(canvas.getByText(/Annual security review/)).toBeInTheDocument();
    await expect(canvas.getByText("Overdue")).toBeInTheDocument();
  },
};

export const NothingOutstanding: Story = {
  beforeEach: () => mockApis([], [], [], []),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("None.")).toHaveLength(4));
  },
};

export const LightTheme: Story = { ...WithOutstandingItems };
export const DarkTheme: Story = { ...WithOutstandingItems, globals: { theme: "dark" } };
