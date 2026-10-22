import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { CommentConfirmDialog } from "./CommentConfirmDialog";

const meta: Meta<typeof CommentConfirmDialog> = {
  title: "Components/CommentConfirmDialog",
  component: CommentConfirmDialog,
  args: {
    title: "Approve this Decision?",
    intro: "This records a formal approval in the audit trail. A comment is optional.",
    confirmLabel: "Approve",
    commentLabel: "Approval comment",
    onConfirm: fn(),
    onCancel: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof CommentConfirmDialog>;

/** The comment is optional: confirm works with the box empty and passes an empty string. */
export const OptionalCommentEmpty: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "Approve this Decision?" })).toBeInTheDocument();
    await expect(requiredCaptions(document.body)).toEqual([]);
    await userEvent.click(body.getByRole("button", { name: "Approve" }));
    await expect(args.onConfirm).toHaveBeenCalledWith("");
  },
};

export const OptionalCommentTyped: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Approval comment"), "Agreed in review");
    await userEvent.click(body.getByRole("button", { name: "Approve" }));
    await expect(args.onConfirm).toHaveBeenCalledWith("Agreed in review");
  },
};

/** A required comment marks the box and keeps confirm disabled until it holds text (blanks do not count). */
export const RequiredCommentBlocksConfirm: Story = {
  args: {
    title: "Reject this Decision?",
    intro: "A comment explaining the rejection is required.",
    commentLabel: "Rejection comment",
    commentRequired: true,
    confirmLabel: "Reject",
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(requiredCaptions(document.body)).toEqual(["Rejection comment"]);
    const confirm = body.getByRole("button", { name: "Reject" });
    await expect(confirm).toBeDisabled();

    await userEvent.type(body.getByLabelText("Rejection comment"), "   ");
    await expect(confirm).toBeDisabled();

    await userEvent.type(body.getByLabelText("Rejection comment"), "Too costly");
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await expect(args.onConfirm).toHaveBeenCalledWith("   Too costly");
  },
};

export const Cancel: Story = {
  play: async ({ args }) => {
    await userEvent.click(within(document.body).getByRole("button", { name: "Cancel" }));
    await expect(args.onCancel).toHaveBeenCalledOnce();
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};
