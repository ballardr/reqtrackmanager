import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildReview, buildRisk, buildRiskScheme, PROJECT_ID, RISK_ID } from "./riskFixtures";
import { RiskReviewsPanel } from "./RiskReviewsPanel";

const REVIEWS_URL = `/api/v1/projects/${PROJECT_ID}/modules/risk_management/risks/${RISK_ID}/reviews`;

const meta: Meta<typeof RiskReviewsPanel> = {
  title: "Modules/RiskManagement/RiskReviewsPanel",
  component: RiskReviewsPanel,
  args: { risk: buildRisk(), scheme: buildRiskScheme(), userNames: { "user-1": "Alex Morgan" }, onRecorded: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof RiskReviewsPanel>;

export const ListsPastReviewsWithTheirRatings: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildReview(), buildReview({ id: "review-0", outcome: "reassessed", notes: "Raised the consequence.", inherent_rating_label: "Critical" })]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Supplier confirmed the date.")).toBeInTheDocument());
    await expect(canvas.getByText("Confirmed")).toHaveClass("badge--accent");
    await expect(canvas.getByText("Reassessed")).toHaveClass("badge--info");
    // Stored labels are re-toned from the project's bands.
    await expect(canvas.getByText("Critical")).toHaveClass("badge--danger");
    await expect(canvas.getAllByText("Alex Morgan")).toHaveLength(2);
    await expect(canvas.getByText(/Next review: 2099-01-15/)).toBeInTheDocument();
  },
};

export const OverdueReviewIsFlagged: Story = {
  args: { risk: buildRisk({ review_date: "2020-01-01", is_review_overdue: true }) },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Overdue")).toHaveClass("badge--danger"));
  },
};

export const NoScheduleSaysSo: Story = {
  args: { risk: buildRisk({ review_date: null }) },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No review scheduled.")).toBeInTheDocument());
  },
};

export const RecordingNeedsNotesAndSendsTheNextDate: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
    spyOn(api, "post").mockResolvedValue(buildReview());
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Record review" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Save review" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Review notes"), "Still holds.");
    await userEvent.type(dialog.getByLabelText("Next review date"), "2099-06-01");
    await userEvent.click(dialog.getByRole("button", { name: "Save review" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(REVIEWS_URL, { outcome: "confirmed", notes: "Still holds.", next_review_date: "2099-06-01" }));
    await waitFor(() => expect(args.onRecorded).toHaveBeenCalled());
  },
};

/** An empty date means "no further review" and is sent as an explicit null. */
export const EmptyDateSchedulesNoFurtherReview: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
    spyOn(api, "post").mockResolvedValue(buildReview());
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Record review" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Review notes"), "Closing out.");
    await userEvent.click(dialog.getByRole("button", { name: "Save review" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(REVIEWS_URL, { outcome: "confirmed", notes: "Closing out.", next_review_date: null }));
  },
};

export const RefusedReviewShowsTheReason: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(409, "A treatment needs reassessment, so the review cannot confirm the assessment."));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Record review" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Review notes"), "Looks fine.");
    await userEvent.click(dialog.getByRole("button", { name: "Save review" }));
    await expect(await dialog.findByText(/needs reassessment, so the review cannot confirm/)).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ListsPastReviewsWithTheirRatings, globals: { theme: "dark" } };
