import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { ActivityPanel } from "./ActivityPanel";

const meta: Meta<typeof ActivityPanel> = {
  title: "Components/ActivityPanel",
  component: ActivityPanel,
};
export default meta;

type Story = StoryObj<typeof ActivityPanel>;

export const Entries: Story = {
  args: {
    entries: [
      buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" }),
      buildChangeEntry({
        entity_type: "change_request",
        entity_id: "cr-1",
        action: "submitted",
        actor_display_name: "Jamie Lee",
        detail: { change_note: "Clarified the reset link expiry window" },
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
    await expect(
      canvas.getByText("Jamie Lee submitted — Clarified the reset link expiry window")
    ).toBeInTheDocument();
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Change request")).toBeInTheDocument();
  },
};

export const NoActivity: Story = {
  args: { entries: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No activity yet.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Entries, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Entries, globals: { theme: "dark" } };

/** `getLink`/`fullWidth` (2026-08 UX audit roadmap row 515) — what
 * `ProjectHistoryPage.tsx` now passes: a project-wide list spans many
 * different requirements/change requests, so each row needs its own link
 * to say which item it's about, unlike the single-entity detail-page side
 * panels (`Entries` above) which omit `getLink` entirely. */
export const WithLinksToRelatedEntities: Story = {
  decorators: [withRouter("/")],
  args: {
    fullWidth: true,
    entries: [
      buildChangeEntry({
        entity_type: "requirement",
        entity_id: "req-1",
        action: "updated",
        actor_display_name: "Alex Morgan",
        detail: { unique_code: "SW-PERF-014", name: "Response time budget" },
      }),
      buildChangeEntry({
        entity_type: "change_request",
        entity_id: "cr-1",
        action: "submitted",
        actor_display_name: "Jamie Lee",
        detail: { proposed_name: "Loosen the response time budget" },
      }),
    ],
    getLink: (entry) => {
      if (entry.entity_type === "requirement") {
        return { to: `/projects/p1/requirements/${entry.entity_id}`, label: "SW-PERF-014 — Response time budget" };
      }
      if (entry.entity_type === "change_request") {
        return { to: `/projects/p1/change-requests/${entry.entity_id}`, label: "Loosen the response time budget" };
      }
      return null;
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "SW-PERF-014 — Response time budget" })).toHaveAttribute(
      "href",
      "/projects/p1/requirements/req-1"
    );
    await expect(canvas.getByRole("link", { name: "Loosen the response time budget" })).toBeInTheDocument();
  },
};

/** `bare` (2026-08 UX audit roadmap item 516) — skips the outer `.card`
 * and "Activity" heading for a caller that supplies its own, e.g.
 * `RequirementDetailPage`'s merged History/Activity card, whose heading
 * switches between "Version history" and "Activity" rather than always
 * reading "Activity". */
export const Bare: Story = {
  args: {
    bare: true,
    entries: [buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" })],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
    // No card wrapper, no "Activity" heading — the caller supplies both.
    await expect(canvas.queryByRole("heading", { name: "Activity" })).not.toBeInTheDocument();
  },
};
