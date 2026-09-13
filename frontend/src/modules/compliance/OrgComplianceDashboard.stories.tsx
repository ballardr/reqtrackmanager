import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { OrgComplianceDashboard } from "./OrgComplianceDashboard";
import type {
  ComplianceRecentActivity,
  OrgExpiringEvidence,
  OrgNonCompliantRequirement,
  OrgPendingApproval,
  OrgReviewDue,
  OutstandingRequiredAction,
  ProjectComplianceStatus,
} from "./types";

const ORG_ID = "org-1";

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

const NON_COMPLIANT: OrgNonCompliantRequirement[] = [
  {
    project_id: "proj-2", project_name: "Beta Tunnel", project_compliance_id: "pc-2",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-1", requirement_id: "req-1", requirement_reference: "A.5.15",
    requirement_name: "Access control", justification: "Missing MFA.", notes: "",
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
    project_id: "proj-2", project_name: "Beta Tunnel", project_compliance_id: "pc-2",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_requirement_id: "pcr-2", requirement_id: "req-2", requirement_reference: "A.5.16",
    requirement_name: "Identity management", required_action_assessment_id: "raa-1", required_action_id: "ra-1",
    required_action_name: "Enable MFA", is_mandatory: true, assignee_id: null, due_date: null, notes: "",
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

const REVIEWS_DUE_ONLY: OrgReviewDue[] = [
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

const REVIEWS_INCLUDING_UPCOMING: OrgReviewDue[] = [
  ...REVIEWS_DUE_ONLY,
  {
    project_id: "proj-2", project_name: "Beta Tunnel",
    review: {
      id: "rev-2", standard_id: "std-1", project_compliance_id: null, frequency_label: "Standard audit",
      recurrence_days: 365, next_due_date: "2026-12-01", owner_id: null, status: "scheduled", schedule_state: "upcoming",
      notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [],
    },
  },
];

const RECENT_ACTIVITY: ComplianceRecentActivity[] = [
  {
    id: "ae-1", project_id: "proj-2", project_name: "Beta Tunnel", standard_reference: "ISO-27001",
    standard_name: "ISO 27001", version_label: "v1.0", requirement_reference: "A.5.15",
    requirement_name: "Access control", action: "assessed", actor_id: "user-1",
    created_at: "2026-09-01T00:00:00Z",
  },
];

function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/non-compliant-requirements")) return NON_COMPLIANT;
    if (path.endsWith("/pending-approvals")) return PENDING;
    if (path.endsWith("/outstanding-required-actions")) return OUTSTANDING_ACTIONS;
    if (path.endsWith("/expiring-evidence")) return EXPIRING_EVIDENCE;
    if (path.includes("/reviews-due")) return path.includes("include_upcoming=true") ? REVIEWS_INCLUDING_UPCOMING : REVIEWS_DUE_ONLY;
    if (path.includes("/recent-activity")) return RECENT_ACTIVITY;
    if (path.includes("/project-compliance")) return STATUS_ROWS;
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgComplianceDashboard> = {
  title: "Modules/Compliance/OrgComplianceDashboard",
  component: OrgComplianceDashboard,
  decorators: [withRouter("/orgs/org-1/overview/compliance-dashboard"), withToast()],
  args: { orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof OrgComplianceDashboard>;

export const Populated: Story = {
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Active compliance standards")).toBeInTheDocument());
    await expect(canvas.getByText("Projects subject to compliance")).toBeInTheDocument();
    await expect(canvas.getAllByText("Beta Tunnel").length).toBeGreaterThan(0);
    await expect(canvas.getByText(/Access control — assessed/)).toBeInTheDocument();
    await expect(canvas.getByText(/Standard audit/)).toBeInTheDocument();
    await expect(canvas.getByText(/ISO-27001 — 3 issues/)).toBeInTheDocument();
  },
};

/** Phase 25b — "Download PDF report"/"Download CSV report" moved behind a
 * single "Export" `Popover` trigger (Principle 11), the same shape
 * `CsvImportWizard.tsx`'s own Export/Download-template pair already uses,
 * rather than two permanently-visible adjacent buttons. */
export const DownloadReport: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["csv"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Active compliance standards")).toBeInTheDocument());
    await expect(canvas.queryByText("Download CSV report")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/reports/csv`
    ));
  },
};

/** Phase 25c — the four headline stats and five detail stats now render as
 * one single `.grid.grid-metrics` grid rather than three separately
 * `flex-wrap`-ped rows of uneven size (4/5). */
export const StatsRenderAsOneEqualSizeGrid: Story = {
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const activeStandardsCard = await waitFor(() => canvas.getByText("Active compliance standards").closest(".card"));
    const grid = activeStandardsCard?.closest(".grid.grid-metrics");
    await expect(grid).not.toBeNull();
    // All nine `StatCard`s (four headline + five detail) live in that same
    // grid container, not split across separate row wrappers.
    await expect(within(grid as HTMLElement).getByText("Assessments awaiting approval")).toBeInTheDocument();
  },
};

/** Phase 36 — the top grid's headline cards no longer embed a variable-
 * length project list as their own `children`; instead each is a
 * `MetricTile` link to a pre-filtered destination (`OrgComplianceStandardsPanel.tsx`'s
 * project pivot, or `OrgComplianceOutstandingPanel.tsx`'s category filter). */
export const HeadlineTilesLinkToFilteredViews: Story = {
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const nonCompliantTile = await waitFor(() => canvas.getByRole("link", { name: /Non-compliant projects/ }));
    await expect(nonCompliantTile).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/overview/compliance-by-standard?groupBy=project&state=non_compliant`
    );
    // No embedded project list inside the tile itself any more.
    await expect(within(nonCompliantTile).queryByRole("link", { name: "Beta Tunnel" })).not.toBeInTheDocument();

    await expect(canvas.getByRole("link", { name: /Projects with outstanding actions/ })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/overview/compliance-outstanding?category=actions`
    );
    await expect(canvas.getByRole("link", { name: /Projects with expired evidence/ })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/overview/compliance-outstanding?category=evidence&validity=expired`
    );
    await expect(canvas.getByRole("link", { name: /Assessments awaiting approval/ })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/overview/compliance-outstanding?category=pending`
    );
  },
};

/** Phase 38 — the second block's remaining two cards ("Standards with the
 * most outstanding issues" / "Upcoming compliance deadlines/reviews") sit
 * top-aligned in one row via an explicit `alignItems: "flex-start"` (never
 * `.row`'s own `align-items: center` default, which is what actually
 * produced the "not top justified" complaint — see this file's own Phase 38
 * note), while "Recently changed compliance assessments" now renders as its
 * own full-width card entirely outside that row. */
export const DetailCardsTopAlignedAndRecentActivityFullWidth: Story = {
  beforeEach: mockApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const standardsCard = await waitFor(() => canvas.getByText("Standards with the most outstanding issues").closest(".card"));
    const upcomingCard = canvas.getByText("Upcoming compliance deadlines/reviews").closest(".card");
    const recentActivityCard = canvas.getByText("Recently changed compliance assessments").closest(".card");

    const sharedRow = standardsCard?.closest(".row");
    await expect(sharedRow).not.toBeNull();
    // Both remaining detail cards share one explicitly top-aligned row.
    await expect(upcomingCard?.closest(".row")).toBe(sharedRow);
    await expect((sharedRow as HTMLElement).style.alignItems).toBe("flex-start");

    // "Recently changed" is no longer inside that row at all.
    await expect(recentActivityCard?.closest(".row")).not.toBe(sharedRow);
    await expect(within(recentActivityCard as HTMLElement).getByText(/Access control — assessed/)).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Populated };
export const DarkTheme: Story = { ...Populated, globals: { theme: "dark" } };
