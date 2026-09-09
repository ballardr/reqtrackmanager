import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import type {
  OrgExpiringEvidence,
  OrgNonCompliantRequirement,
  OrgPendingApproval,
  OrgReviewDue,
  OutstandingRequiredAction,
} from "./types";

const ORG_ID = "org-1";

function mockApis(overrides: {
  nonCompliant?: OrgNonCompliantRequirement[];
  pending?: OrgPendingApproval[];
  outstandingActions?: OutstandingRequiredAction[];
  expiringEvidence?: OrgExpiringEvidence[];
  reviewsDue?: OrgReviewDue[];
} = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return overrides.nonCompliant ?? [];
    if (path.endsWith("/pending-approvals")) return overrides.pending ?? [];
    if (path.endsWith("/outstanding-required-actions")) return overrides.outstandingActions ?? [];
    if (path.endsWith("/expiring-evidence")) return overrides.expiringEvidence ?? [];
    if (path.includes("/reviews-due")) return overrides.reviewsDue ?? [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgComplianceOutstandingPanel> = {
  title: "Modules/Compliance/OrgComplianceOutstandingPanel",
  component: OrgComplianceOutstandingPanel,
  decorators: [withRouter("/orgs/org-1/overview/compliance-outstanding"), withToast()],
  args: { orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OrgComplianceOutstandingPanel>;

const NON_COMPLIANT: OrgNonCompliantRequirement[] = [
  {
    project_id: "proj-1", project_name: "Alpha Bridge", project_compliance_id: "pc-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", justification: "Missing MFA on admin accounts.", notes: "",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const PENDING: OrgPendingApproval[] = [
  {
    project_id: "proj-2", project_name: "Beta Tunnel", project_compliance_id: "pc-2",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-2", requirement_id: "req-2", requirement_reference: "A.5.16",
    requirement_name: "Identity management", compliance_status: "compliant",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const OUTSTANDING_ACTIONS: OutstandingRequiredAction[] = [
  {
    project_id: "proj-1", project_name: "Alpha Bridge", project_compliance_id: "pc-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", required_action_assessment_id: "raa-1", required_action_id: "ra-1",
    required_action_name: "Enable MFA for admin accounts", is_mandatory: true,
    assignee_id: "user-1", due_date: "2026-10-01", notes: "",
  },
];

const EXPIRING_EVIDENCE: OrgExpiringEvidence[] = [
  {
    id: "ev-1", project_id: "proj-2", project_name: "Beta Tunnel", title: "Thermal test certificate",
    description: "", issuing_organisation: "Acme Labs", issued_date: "2025-01-01", expiry_date: "2026-08-01",
    provided_by: "user-1", provided_at: "2025-01-01T00:00:00Z", notes: "", validity_state: "expired",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2025-01-01T00:00:00Z", updated_at: "2025-01-01T00:00:00Z",
    linked_requirement_ids: [], linked_required_action_assessment_ids: [],
  },
];

const REVIEWS_DUE: OrgReviewDue[] = [
  {
    project_id: "proj-1", project_name: "Alpha Bridge",
    review: {
      id: "rev-1", standard_id: null, project_compliance_id: "pc-1", frequency_label: "Annual security review",
      recurrence_days: 365, next_due_date: "2026-09-01", owner_id: null, status: "scheduled", schedule_state: "overdue",
      notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [],
    },
  },
];

export const WithOutstandingItems: Story = {
  beforeEach: () =>
    mockApis({
      nonCompliant: NON_COMPLIANT, pending: PENDING, outstandingActions: OUTSTANDING_ACTIONS,
      expiringEvidence: EXPIRING_EVIDENCE, reviewsDue: REVIEWS_DUE,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Missing MFA on admin accounts/)).toBeInTheDocument());
    await expect(canvas.getAllByText("Alpha Bridge").length).toBeGreaterThan(0);
    await expect(canvas.getAllByText("Beta Tunnel").length).toBeGreaterThan(0);
    await expect(canvas.getByText(/Enable MFA for admin accounts/)).toBeInTheDocument();
    await expect(canvas.getByText(/Thermal test certificate/)).toBeInTheDocument();
    await expect(canvas.getByText(/Annual security review/)).toBeInTheDocument();
  },
};

export const NothingOutstanding: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("None.")).toHaveLength(5));
  },
};

export const LightTheme: Story = { ...WithOutstandingItems };
export const DarkTheme: Story = { ...WithOutstandingItems, globals: { theme: "dark" } };
