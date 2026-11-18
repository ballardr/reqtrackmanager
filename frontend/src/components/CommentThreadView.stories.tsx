import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { userEvent as pointer } from "vitest/browser";

import { buttonHeightViolations } from "../testing/buttonHeights";
import { orphanedControlViolations } from "../testing/orphanedControls";
import { buildComment, buildPin } from "../testing/recordCommentsFake";
import { CommentThreadView } from "./CommentThreadView";

/**
 * One pinned thread (style guide "Pattern: actions revealed on hover"): a comment's Edit and Delete are small icon
 * buttons revealed on row hover or keyboard focus (always visible on a device with no hover), and the thread's
 * Resolve and Delete sit as icons beside one Reply button.
 */
const meta: Meta<typeof CommentThreadView> = {
  title: "Components/CommentThreadView",
  component: CommentThreadView,
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ width: 320 }}><Story /></div>],
};
export default meta;

type Story = StoryObj<typeof CommentThreadView>;

const LONG = "A long comment that runs over several lines of a narrow pop-over so that the row's actions are put under pressure "
  + "to stay beside the author line and never push the text around when they appear.";

const args = {
  pin: buildPin({ id: "p-1" }),
  comments: [
    buildComment({ id: "c-1", pin_id: "p-1", body: LONG }),
    buildComment({ id: "c-2", pin_id: "p-1", author_display_name: "Sam Owner", body: "Agreed.", can_edit: false, can_delete: false }),
  ],
  onReply: fn(async () => true),
  onEdit: fn(async () => true),
  onRemove: fn(async () => true),
  onResolve: fn(async () => true),
  onRemoveThread: fn(async () => true),
};

/** A comment's actions are icon buttons, each named, and another person's comment offers none. */
export const ActionsAreNamedIconButtons: Story = {
  args,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of ["Edit", "Delete comment", "Resolve", "Delete thread"]) {
      const button = canvas.getByRole("button", { name });
      await expect(button).toHaveClass("btn-icon");
      await expect(button).toHaveClass("btn-sm");
      await expect(button).toHaveTextContent("");
    }
    await expect(canvas.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
    await expect(canvas.getByRole("button", { name: "Reply" })).toHaveClass("btn-sm");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** A comment's actions are hidden until the row is hovered, and the row keeps its size either way. */
export const RowActionsAppearOnHover: Story = {
  args,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByText(LONG).closest(".comment-row") as HTMLElement;
    const header = row.querySelector(".item-row") as HTMLElement;
    const actions = row.querySelector(".item-row__actions") as HTMLElement;
    const before = row.getBoundingClientRect().height;
    // A real pointer move: the testing library's synthetic events do not set the `:hover` state.
    await pointer.unhover(canvasElement);
    await expect(getComputedStyle(actions).opacity).toBe("0");
    await pointer.hover(header);
    await waitFor(() => expect(getComputedStyle(actions).opacity).toBe("1"));
    await expect(row.getBoundingClientRect().height).toBe(before);
  },
};

/** Keyboard focus on an action reveals the row's actions, so nobody who cannot hover loses them. */
export const RowActionsAppearOnFocus: Story = {
  args,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByText(LONG).closest(".comment-row") as HTMLElement;
    const actions = row.querySelector(".item-row__actions") as HTMLElement;
    await pointer.unhover(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Edit" })).toHaveFocus();
    await expect(getComputedStyle(actions).opacity).toBe("1");
  },
};

/** The icon actions work: edit opens the text with Save and Cancel, delete confirms, resolve reports and flips to Reopen. */
export const EditDeleteAndResolve: Story = {
  args,
  play: async ({ canvasElement, args: a }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(a.onEdit).toHaveBeenCalledWith("c-1", LONG));
    await userEvent.click(canvas.getByRole("button", { name: "Delete comment" }));
    const confirm = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(confirm.getByRole("button", { name: "Delete comment" }));
    await waitFor(() => expect(a.onRemove).toHaveBeenCalledWith("c-1"));
    await userEvent.click(canvas.getByRole("button", { name: "Resolve" }));
    await expect(a.onResolve).toHaveBeenCalledWith(true);
  },
};

/** A resolved thread offers Reopen in the same place. */
export const ResolvedThreadOffersReopen: Story = {
  args: { ...args, pin: buildPin({ id: "p-1", resolved: true }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Reopen" })).toHaveClass("btn-icon");
  },
};
