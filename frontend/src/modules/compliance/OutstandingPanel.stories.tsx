import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OutstandingPanel } from "./OutstandingPanel";
import type {
  ComplianceRequirement,
  ComplianceReview,
  ComplianceStandardVersion,
  NonCompliantRequirement,
  OutstandingRequiredAction,
  PendingApproval,
} from "./types";

const PROJECT_ID = "proj-1";
const ORG_ID = "org-1";

/**
 * §21's "make it easy... to determine what remains outstanding" — the
 * four cross-assignment listings (Non-Compliant, Pending Approval,
 * Outstanding Required Actions — added Phase 14 — and Reviews Due/Overdue)
 * gathered in one read-only view. Acting on a row happens via the
 * Standards tab (`ApplicabilityTree`/`ReviewsPanel`), not here.
 *
 * Phase 40's Standard/Standard version/Sub-section filters additionally
 * fetch `listStandardVersions`/`listRequirements` once a standard is
 * picked — `versions`/`requirementsByVersion` let a story supply that data
 * only when it needs the filters to actually resolve something (most
 * stories below never select a standard, so those two endpoints stay
 * unmocked/unused for them).
 */
function mockApis(
  nonCompliant: NonCompliantRequirement[],
  pending: PendingApproval[],
  outstandingActions: OutstandingRequiredAction[],
  reviewsDue: ComplianceReview[],
  versions: ComplianceStandardVersion[] = [],
  requirementsByVersion: Record<string, ComplianceRequirement[]> = {}
) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return nonCompliant;
    if (path.endsWith("/pending-approvals")) return pending;
    if (path.endsWith("/outstanding-required-actions")) return outstandingActions;
    if (path.endsWith("/reviews-due")) return reviewsDue;
    if (path.endsWith("/versions")) return versions;
    const requirementsMatch = /\/versions\/([^/]+)\/requirements$/.exec(path);
    if (requirementsMatch) return requirementsByVersion[requirementsMatch[1]] ?? [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OutstandingPanel> = {
  title: "Modules/Compliance/OutstandingPanel",
  component: OutstandingPanel,
  decorators: [withToast()],
  args: { projectId: PROJECT_ID, orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OutstandingPanel>;

const NON_COMPLIANT: NonCompliantRequirement[] = [
  {
    project_compliance_id: "pc-1", standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", justification: "Missing MFA on admin accounts.", notes: "",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const PENDING: PendingApproval[] = [
  {
    project_compliance_id: "pc-1", standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-2", requirement_id: "req-2", requirement_reference: "A.5.16",
    requirement_name: "Identity management", compliance_status: "compliant",
    assessed_at: "2026-01-01T00:00:00Z", assessed_by: "user-1",
  },
];

const OUTSTANDING_ACTIONS: OutstandingRequiredAction[] = [
  {
    project_id: PROJECT_ID, project_name: "Demo Project", project_compliance_id: "pc-1",
    standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", required_action_assessment_id: "raa-1", required_action_id: "ra-1",
    required_action_name: "Enable MFA for admin accounts", is_mandatory: true,
    assignee_id: "user-1", due_date: "2026-10-01", notes: "",
  },
];

const REVIEWS_DUE: ComplianceReview[] = [
  {
    id: "rev-1", standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_id: "pc-1", frequency_label: "Annual security review",
    recurrence_days: 365, next_due_date: "2026-09-01", owner_id: null, status: "scheduled", schedule_state: "overdue",
    notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [],
  },
];

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

/** Phase 40 — selecting "ISO-27001" surfaces a "Standard version" and
 * "Sub-section" filter; both `req-1`/`req-2` (behind every row below) sit
 * under "Annex A.5," so filtering to "Clause 4" (which has no requirements
 * of its own here) narrows the three requirement-scoped sections to
 * "None." while the standard/version-only Reviews section is unaffected. */
export const FilteredByStandardAndSubSection: Story = {
  beforeEach: () => mockApis(NON_COMPLIANT, PENDING, OUTSTANDING_ACTIONS, REVIEWS_DUE, [VER_1], { "ver-1": REQUIREMENTS_VER_1 }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Missing MFA on admin accounts/)).toBeInTheDocument());

    await userEvent.selectOptions(canvas.getByLabelText("Standard"), "std-1");
    await waitFor(() => expect(canvas.getByLabelText("Sub-section")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Sub-section"), "sec-4");

    await waitFor(() => expect(canvas.getAllByText("None.")).toHaveLength(3));
    await expect(canvas.getByText(/Annual security review/)).toBeInTheDocument();
  },
};

/** Phase 43: the "Export" trigger scopes its download to this panel's
 * current Standard/Standard version/Sub-section filters — no Project filter
 * to pass through, since this page is already scoped to one project. */
export const ExportPassesActiveFiltersAsQueryParams: Story = {
  beforeEach: () => {
    mockApis(NON_COMPLIANT, PENDING, OUTSTANDING_ACTIONS, REVIEWS_DUE, [VER_1], { "ver-1": REQUIREMENTS_VER_1 });
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["csv"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Missing MFA on admin accounts/)).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Standard"), "std-1");
    await waitFor(() => expect(canvas.getByLabelText("Sub-section")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Sub-section"), "sec-5");

    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/reports/csv?standard_id=std-1&requirement_id=sec-5`
    ));
  },
};

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
