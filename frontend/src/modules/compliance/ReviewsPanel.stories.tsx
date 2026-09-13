import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ReviewsPanel } from "./ReviewsPanel";
import type { ComplianceReview } from "./types";

const PROJECT_ID = "proj-1";
const PC_ID = "pc-1";

function review(overrides: Partial<ComplianceReview> = {}): ComplianceReview {
  return {
    id: "rev-1", standard_id: "std-1", standard_version_id: "ver-1",
    standard_reference: "ISO-27001", standard_name: "ISO 27001", version_label: "v1.0",
    project_compliance_id: PC_ID, frequency_label: "Annual security review",
    recurrence_days: 365, next_due_date: "2026-12-01", owner_id: null, status: "scheduled", schedule_state: "upcoming",
    notes: "", outcome: null, completed_at: null, completed_by: null, created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", linked_evidence_ids: [], ...overrides,
  };
}

/** §17's project-level scheduled-review CRUD + complete, for one standard
 * assignment — a review can only be edited/deleted while `scheduled`
 * (retained history must not be edited in place once completed). */
function mockApis(initial: ComplianceReview[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/reviews")) {
      const payload = body as { frequency_label: string; recurrence_days: number | null; next_due_date: string; owner_id: string | null; notes: string };
      const created = review({ id: "rev-new", ...payload });
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

const meta: Meta<typeof ReviewsPanel> = {
  title: "Modules/Compliance/ReviewsPanel",
  component: ReviewsPanel,
  decorators: [withToast()],
  args: { projectId: PROJECT_ID, projectComplianceId: PC_ID, orgUsers: [] },
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
      { frequency_label: "Six-monthly environmental review", recurrence_days: null, next_due_date: "2026-11-01", owner_id: null, notes: "" }
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
