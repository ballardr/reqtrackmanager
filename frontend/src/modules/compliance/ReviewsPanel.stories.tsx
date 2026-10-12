import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ReviewsPanel } from "./ReviewsPanel";
import type { OrgGroup, Principal, ProjectGroup } from "../../api/types";
import type { ComplianceReview } from "./types";

const PROJECT_ID = "proj-1";
const PC_ID = "pc-1";
const ORG_ID = "org-1";

const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Compliance Office", member_user_ids: ["user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [
  { id: "pgroup-1", name: "Release board", roles: [], member_user_ids: ["user-2"], member_org_group_ids: [], member_source_project_ids: [] },
];
const OFFICE: Principal = { type: "org_group", id: "group-1", label: "Compliance Office", member_count: 4, exists: true };

function review(overrides: Partial<ComplianceReview> = {}): ComplianceReview {
  return {
    id: "rev-1", standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_id: PC_ID, frequency_label: "Annual security review",
    recurrence_days: 365, next_due_date: "2026-12-01", owner: null, status: "scheduled", schedule_state: "upcoming",
    notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [], ...overrides,
  };
}

/** §17's project-level scheduled-review CRUD + complete, for one standard
 * assignment — a review can only be edited/deleted while `scheduled`
 * (retained history must not be edited in place once completed). */
function mockApis(initial: ComplianceReview[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}/groups`) return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    return items;
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/reviews")) {
      const payload = body as { frequency_label: string; recurrence_days: number | null; next_due_date: string; owner: { type: string; id: string } | null; notes: string };
      const created = review({ id: "rev-new", ...payload, owner: payload.owner ? principalFor(payload.owner) : null });
      items = [...items, created];
      return created;
    }
    if (path.endsWith("/complete")) {
      const id = path.split("/reviews/")[1].split("/complete")[0];
      const payload = body as { outcome: ComplianceReview["outcome"] };
      items = items.map((r) => (r.id === id ? { ...r, status: "completed", outcome: payload.outcome } : r));
      return items.find((r) => r.id === id);
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/reviews/")[1];
    items = items.map((r) => (r.id === id ? { ...r, ...(body as object) } : r));
    return items.find((r) => r.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/reviews/")[1];
    items = items.filter((r) => r.id !== id);
  });
}

/** The resolved view of a picked principal, as the server would return it. */
function principalFor(ref: { type: string; id: string }): Principal {
  if (ref.id === OFFICE.id) return OFFICE;
  if (ref.id === "pgroup-1") return { type: "project_group", id: "pgroup-1", label: "Release board", member_count: 1, exists: true };
  return { type: "user", id: ref.id, label: "Jamie Lee", member_count: null, exists: true };
}

const meta: Meta<typeof ReviewsPanel> = {
  title: "Modules/Compliance/ReviewsPanel",
  component: ReviewsPanel,
  decorators: [withToast()],
  args: { projectId: PROJECT_ID, projectComplianceId: PC_ID, organizationId: ORG_ID, orgUsers: [] },
};
export default meta;

type Story = StoryObj<typeof ReviewsPanel>;

export const ListsScheduledReviews: Story = {
  beforeEach: () => mockApis([review()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Annual security review/)).toBeInTheDocument());
  },
};

export const ScheduleReview: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("No reviews scheduled for this assignment yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Schedule review" }));
    await userEvent.type(body.getByLabelText("Frequency / description"), "Six-monthly environmental review");
    await userEvent.type(body.getByLabelText("Next due date"), "2026-11-01");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/reviews`,
      { frequency_label: "Six-monthly environmental review", recurrence_days: null, next_due_date: "2026-11-01", owner: null, notes: "" }
    ));
  },
};

/** A team can own a review: the list names the group and its kind, not a guessed person. */
export const GroupOwnerIsNamed: Story = {
  beforeEach: () => mockApis([review({ owner: OFFICE })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Compliance Office")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 4 members")).toBeInTheDocument();
  },
};

/** The review form offers the project's groups as well as the organisation's. */
export const ScheduleReviewOwnedByAProjectGroup: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("No reviews scheduled for this assignment yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Schedule review" }));
    await userEvent.type(body.getByLabelText("Frequency / description"), "Quarterly board review");
    await userEvent.type(body.getByLabelText("Next due date"), "2026-11-01");
    await userEvent.type(body.getByLabelText("Review owner"), "release");
    await userEvent.click(await body.findByText("Release board"));
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/project-compliance/${PC_ID}/reviews`,
      { frequency_label: "Quarterly board review", recurrence_days: null, next_due_date: "2026-11-01", owner: { type: "project_group", id: "pgroup-1" }, notes: "" }
    ));
  },
};

export const CompleteReview: Story = {
  beforeEach: () => mockApis([review()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Complete" }));
    const dialog = await waitFor(() => body.getByRole("dialog", { name: "Complete review" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Complete" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/reviews/rev-1/complete`,
      { outcome: "satisfactory", notes: "" }
    ));
  },
};

export const CompletedReviewIsReadOnly: Story = {
  beforeEach: () => mockApis([review({ id: "rev-2", status: "completed", schedule_state: null, outcome: "satisfactory" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Satisfactory")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsScheduledReviews };
export const DarkTheme: Story = { ...ListsScheduledReviews, globals: { theme: "dark" } };
