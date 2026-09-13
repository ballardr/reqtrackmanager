import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import type {
  ComplianceRequirement,
  ComplianceStandardVersion,
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
  versions?: ComplianceStandardVersion[];
  requirementsByVersion?: Record<string, ComplianceRequirement[]>;
} = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return overrides.nonCompliant ?? [];
    if (path.endsWith("/pending-approvals")) return overrides.pending ?? [];
    if (path.endsWith("/outstanding-required-actions")) return overrides.outstandingActions ?? [];
    if (path.endsWith("/expiring-evidence")) return overrides.expiringEvidence ?? [];
    if (path.includes("/reviews-due")) return overrides.reviewsDue ?? [];
    if (path.endsWith("/versions")) return overrides.versions ?? [];
    const requirementsMatch = /\/versions\/([^/]+)\/requirements$/.exec(path);
    if (requirementsMatch) return overrides.requirementsByVersion?.[requirementsMatch[1]] ?? [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

const DEFAULT_PATH = "/orgs/org-1/overview/compliance-outstanding";

const meta: Meta<typeof OrgComplianceOutstandingPanel> = {
  title: "Modules/Compliance/OrgComplianceOutstandingPanel",
  component: OrgComplianceOutstandingPanel,
  decorators: [withToast()],
  args: { orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OrgComplianceOutstandingPanel>;

const NON_COMPLIANT: OrgNonCompliantRequirement[] = [
  {
    project_id: "proj-1", project_name: "Alpha Bridge", project_compliance_id: "pc-1",
    standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", justification: "Missing MFA on admin accounts.", notes: "",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const PENDING: OrgPendingApproval[] = [
  {
    project_id: "proj-2", project_name: "Beta Tunnel", project_compliance_id: "pc-2",
    standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-2", requirement_id: "req-2", requirement_reference: "A.5.16",
    requirement_name: "Identity management", compliance_status: "compliant",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const OUTSTANDING_ACTIONS: OutstandingRequiredAction[] = [
  {
    project_id: "proj-1", project_name: "Alpha Bridge", project_compliance_id: "pc-1",
    standard_id: "std-1", standard_version_id: "ver-1",
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
      id: "rev-1", standard_id: "std-1", standard_version_id: "ver-1",
      standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
      project_compliance_id: "pc-1", frequency_label: "Annual security review",
      recurrence_days: 365, next_due_date: "2026-09-01", owner_id: null, status: "scheduled", schedule_state: "overdue",
      notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [],
    },
  },
];

export const WithOutstandingItems: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
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

/** Phase 36 — `OrgComplianceDashboard.tsx`'s "Projects with expired
 * evidence" tile links here with `?category=evidence&validity=expired`, so
 * only the Evidence section renders, narrowed to the expired row alone. */
export const CategoryFilteredViaUrl: Story = {
  decorators: [withRouter(`${DEFAULT_PATH}?category=evidence&validity=expired`)],
  beforeEach: () =>
    mockApis({
      nonCompliant: NON_COMPLIANT, pending: PENDING, outstandingActions: OUTSTANDING_ACTIONS,
      expiringEvidence: EXPIRING_EVIDENCE, reviewsDue: REVIEWS_DUE,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Thermal test certificate/)).toBeInTheDocument());
    await expect(canvas.getByText("Evidence expired (1)")).toBeInTheDocument();
    // The other four sections' own content is absent, not just collapsed.
    await expect(canvas.queryByText(/Missing MFA on admin accounts/)).not.toBeInTheDocument();
    await expect(canvas.queryByText(/Enable MFA for admin accounts/)).not.toBeInTheDocument();
    await expect(canvas.queryByText(/Annual security review/)).not.toBeInTheDocument();
  },
};

const VER_1: ComplianceStandardVersion = {
  id: "ver-1", standard_id: "std-1", version_number: 1, version_label: "v1.0", status: "published",
  effective_date: null, change_note: "", summary: "", created_by: "user-1", published_at: "2026-01-01T00:00:00Z",
  published_by: "user-1", retired_at: null, retired_by: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const REQUIREMENT_DEFAULTS = {
  description: "", reasoning: "", created_by: "user-1", clarification_count: 0, last_clarified_at: null,
  last_clarified_by: null, last_clarification_note: "", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const REQUIREMENTS_VER_1: ComplianceRequirement[] = [
  { id: "sec-4", standard_version_id: "ver-1", parent_requirement_id: null, reference: "Clause 4", name: "Context of the organization", sort_order: 0, ...REQUIREMENT_DEFAULTS },
  { id: "sec-5", standard_version_id: "ver-1", parent_requirement_id: null, reference: "Annex A.5", name: "Organizational controls", sort_order: 1, ...REQUIREMENT_DEFAULTS },
  { id: "req-1", standard_version_id: "ver-1", parent_requirement_id: "sec-5", reference: "A.5.15", name: "Access control", sort_order: 0, ...REQUIREMENT_DEFAULTS },
  { id: "req-2", standard_version_id: "ver-1", parent_requirement_id: "sec-5", reference: "A.5.16", name: "Identity management", sort_order: 1, ...REQUIREMENT_DEFAULTS },
];

/** Phase 40 — filtering by Project narrows every section that carries a
 * `project_id` (all five), and filtering by Standard then Sub-section
 * additionally narrows the three requirement-scoped sections (both
 * `req-1`/`req-2` sit under "Annex A.5," so picking "Clause 4" empties
 * them while Evidence and Reviews — not per-requirement — are unaffected
 * by the sub-section pick specifically). */
export const FilteredByProjectStandardAndSubSection: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
  beforeEach: () =>
    mockApis({
      nonCompliant: NON_COMPLIANT, pending: PENDING, outstandingActions: OUTSTANDING_ACTIONS,
      expiringEvidence: EXPIRING_EVIDENCE, reviewsDue: REVIEWS_DUE,
      versions: [VER_1], requirementsByVersion: { "ver-1": REQUIREMENTS_VER_1 },
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Missing MFA on admin accounts/)).toBeInTheDocument());

    await userEvent.selectOptions(canvas.getByLabelText("Project"), "proj-2");
    await waitFor(() => expect(canvas.queryByText(/Missing MFA on admin accounts/)).not.toBeInTheDocument());
    await expect(canvas.getByText(/Identity management/)).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Project"), "");

    await userEvent.selectOptions(canvas.getByLabelText("Standard"), "std-1");
    await waitFor(() => expect(canvas.getByLabelText("Sub-section")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Sub-section"), "sec-4");
    await waitFor(() => expect(canvas.queryByText(/Missing MFA on admin accounts/)).not.toBeInTheDocument());
    await expect(canvas.getByText(/Thermal test certificate/)).toBeInTheDocument();
    await expect(canvas.getByText(/Annual security review/)).toBeInTheDocument();
  },
};

export const NothingOutstanding: Story = {
  decorators: [withRouter(DEFAULT_PATH)],
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("None.")).toHaveLength(5));
  },
};

export const LightTheme: Story = { ...WithOutstandingItems };
export const DarkTheme: Story = { ...WithOutstandingItems, globals: { theme: "dark" } };
