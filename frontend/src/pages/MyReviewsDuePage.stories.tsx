import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { RequirementDueForReview } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { MyReviewsDuePage } from "./MyReviewsDuePage";

function reviewItem(overrides: Partial<RequirementDueForReview>): RequirementDueForReview {
  return {
    requirement_id: "req-1", project_id: "project-1", unique_code: "AUTH-LOG-001",
    name: "Users can reset a forgotten password", review_date: "2026-03-01",
    reviewer_id: "user-1", reviewer_name: "Alex Morgan", component_id: "component-1", component_name: "Authentication",
    ...overrides,
  };
}

const meta: Meta<typeof MyReviewsDuePage> = {
  title: "Pages/MyReviewsDuePage",
  component: MyReviewsDuePage,
  decorators: [withRouter("/my-reviews")],
};
export default meta;

type Story = StoryObj<typeof MyReviewsDuePage>;

export const DueReviews: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([reviewItem({}), reviewItem({ requirement_id: "req-2", unique_code: "AUTH-LOG-002", name: "Session expiry" })]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("AUTH-LOG-001")).toBeInTheDocument();
    await expect(canvas.getByText("Session expiry")).toBeInTheDocument();
  },
};

export const NoDueReviews: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Nothing due for review.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...DueReviews, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DueReviews, globals: { theme: "dark" } };
