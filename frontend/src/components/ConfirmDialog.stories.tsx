import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ConfirmDialog } from "./ConfirmDialog";

const meta: Meta<typeof ConfirmDialog> = {
  title: "Components/ConfirmDialog",
  component: ConfirmDialog,
  args: {
    title: "Archive this requirement?",
    message: "It can be restored later from its version history.",
    confirmLabel: "Archive",
    onConfirm: fn(),
    onCancel: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ConfirmDialog>;

/** Tier 1 — an ordinary, recoverable delete/archive: no typed confirmation,
 * the confirm button is enabled immediately. */
export const Tier1Ordinary: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "Archive this requirement?" })).toBeInTheDocument();
    const confirmButton = body.getByRole("button", { name: "Archive" });
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    await expect(args.onConfirm).toHaveBeenCalledOnce();
  },
};

export const Tier1Cancel: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("button", { name: "Cancel" }));
    await expect(args.onCancel).toHaveBeenCalledOnce();
  },
};

/** Tier 2 — irreversible, wide blast radius: the confirm button stays
 * disabled until the exact `requireTypedText` value is typed. */
export const Tier2TypeToConfirm: Story = {
  args: {
    title: "Permanently delete this organisation",
    message: 'This permanently deletes "Acme Corp" and everything it owns. This cannot be undone.',
    confirmLabel: "Permanently delete",
    requireTypedText: "Acme Corp",
  },
  play: async ({ args }) => {
    const body = within(document.body);
    const confirmButton = body.getByRole("button", { name: "Permanently delete" });
    const input = body.getByLabelText('Type "Acme Corp" to confirm');
    await expect(confirmButton).toBeDisabled();

    await userEvent.type(input, "Acme Cor");
    await expect(confirmButton).toBeDisabled();

    await userEvent.type(input, "p");
    await expect(confirmButton).toBeEnabled();

    await userEvent.click(confirmButton);
    await expect(args.onConfirm).toHaveBeenCalledOnce();
  },
};

export const LightTheme: Story = { ...Tier1Ordinary, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Tier1Ordinary, globals: { theme: "dark" } };
