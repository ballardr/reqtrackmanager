import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { RequirementDueForReview } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { MyReviewsDuePage } from "./MyReviewsDuePage";

function reviewItem(overrides: Partial<RequirementDueForReview>): RequirementDueForReview {
  return {
    requirement_id: "req-1", project_id: "project-1", project_name: "Atlas Platform", unique_code: "AUTH-LOG-001",
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
    spyOn(api, "getPage").mockResolvedValue({
      items: [
        reviewItem({}),
        reviewItem({ requirement_id: "req-2", unique_code: "AUTH-LOG-002", name: "Session expiry", project_id: "project-2", project_name: "Beacon Mobile" }),
      ],
      total: 2,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("AUTH-LOG-001")).toBeInTheDocument();
    await expect(canvas.getByText("Session expiry")).toBeInTheDocument();
    // Spans every project the reviewer has a role on, so each row shows
    // which one it belongs to — the project-scoped sibling page doesn't
    // need this column since it's already in that page's own URL.
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    await expect(canvas.getByText("Beacon Mobile")).toBeInTheDocument();
  },
};

export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: Array.from({ length: 30 }, (_, i) => reviewItem({ requirement_id: `req-${i}`, unique_code: `AUTH-LOG-${i}` })),
      total: 35,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: /30\/35/ })).toBeInTheDocument();
  },
};

export const NoDueReviews: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Nothing due for review.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...DueReviews, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DueReviews, globals: { theme: "dark" } };
