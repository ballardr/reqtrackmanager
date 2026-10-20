import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

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
    await expect(canvas.getByText("Jamie Lee submitted")).toBeInTheDocument();
    // The note typed with the change is a quoted block under the sentence, not part of it.
    await expect(canvas.getByText("Clarified the reset link expiry window")).toBeInTheDocument();
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Change request")).toBeInTheDocument();
  },
};

/** The comment given at a workflow step (`detail.comment`) shows under the sentence, once, as text. */
export const TransitionComments: Story = {
  args: {
    entries: [
      buildChangeEntry({
        entity_type: "pain_point", action: "addressed", actor_display_name: "Sam Park",
        detail: { comment: "Fixed in release 2.1.\nVerified with the field team." },
      }),
      // A comment and a change note that say the same thing are shown once.
      buildChangeEntry({
        entity_type: "strategy", action: "approved", actor_display_name: "Sam Park",
        detail: { comment: "Approved at the board", change_note: "Approved at the board" },
      }),
      // User text is never interpreted as HTML.
      buildChangeEntry({
        entity_type: "decision", action: "rejected", actor_display_name: "Sam Park",
        detail: { comment: "<b>not bold</b>" },
      }),
      // A change request decided before the key was unified stored its comment as `note`.
      buildChangeEntry({
        entity_type: "change_request", entity_id: "cr-9", action: "rejected", actor_display_name: "Jo Lin",
        detail: { note: "Out of scope this quarter" },
      }),
      buildChangeEntry({ entity_type: "pain_point", action: "triaged", actor_display_name: "No Comment", detail: null }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Sam Park addressed")).toBeInTheDocument();
    const note = canvas.getByText(/Fixed in release 2\.1\./);
    await expect(note.tagName).toBe("BLOCKQUOTE");
    await expect(note).toHaveTextContent("Verified with the field team.");
    await expect(canvas.getAllByText("Approved at the board")).toHaveLength(1);
    await expect(canvas.getByText("<b>not bold</b>")).toBeInTheDocument();
    await expect(canvas.getByText("Out of scope this quarter")).toBeInTheDocument();
    await expect(canvas.getByText("No Comment triaged")).toBeInTheDocument();
  },
};

/** A long comment is cut at three lines until "Show more" is pressed. */
export const LongCommentCollapses: Story = {
  decorators: [(Story) => <div style={{ width: 260 }}><Story /></div>],
  args: {
    entries: [
      buildChangeEntry({
        entity_type: "pain_point", action: "closed", actor_display_name: "Sam Park",
        detail: { comment: "Closing this after a long review. ".repeat(20) },
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const more = await canvas.findByRole("button", { name: "Show more" });
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    await expect(canvas.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
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

/** `getLink`/`fullWidth` — what
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

/** `bare` — skips the outer `.card`
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
