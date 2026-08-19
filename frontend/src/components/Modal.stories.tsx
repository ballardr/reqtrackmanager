import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { Modal } from "./Modal";

const meta: Meta<typeof Modal> = {
  title: "Components/Modal",
  component: Modal,
  args: { title: "Delete requirement", onClose: fn(), children: "This cannot be undone." },
};
export default meta;

type Story = StoryObj<typeof Modal>;

export const Default: Story = {
  play: async ({ args }) => {
    // Rendered through a portal into document.body, not canvasElement.
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "Delete requirement" })).toBeInTheDocument();
    await expect(body.getByText("This cannot be undone.")).toBeInTheDocument();
    await userEvent.click(body.getByLabelText("Close"));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

export const ClosesOnEscape: Story = {
  play: async ({ args }) => {
    await userEvent.keyboard("{Escape}");
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

export const ClosesOnBackdropClick: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("presentation"));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** The dialog itself stops click propagation, so clicking inside it must
 * NOT trigger the backdrop's close handler. */
export const ClickInsideDoesNotClose: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByText("This cannot be undone."));
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

/** 2026-08 UX audit / style guide Principle 8: opening the dialog moves
 * focus into it (here, its own Close button, since this story's children
 * have no focusable content of their own) rather than leaving focus
 * wherever it was on the page behind the backdrop. */
export const FocusMovesIntoDialogOnOpen: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByLabelText("Close")).toHaveFocus();
  },
};

/** A child that sets its own `autoFocus` (e.g. `RichTextEditor`'s
 * link-URL field) wins — the dialog's own "focus something on open"
 * fallback only applies when nothing inside already has focus. */
export const AutoFocusChildWins: Story = {
  args: {
    // autoFocus here is exactly the behaviour under test, not an oversight.
    children: <input className="input" autoFocus placeholder="Link URL" />,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByPlaceholderText("Link URL")).toHaveFocus();
  },
};

/** Tab from the last focusable element wraps back to the first (the Close
 * button); Shift+Tab from the first wraps back to the last — focus never
 * escapes the dialog into the page behind it while it's open. */
export const TabTrapCycles: Story = {
  args: {
    children: (
      <div className="row">
        <button type="button">First action</button>
        <button type="button">Last action</button>
      </div>
    ),
  },
  play: async () => {
    const body = within(document.body);
    const closeButton = body.getByLabelText("Close");
    const lastAction = body.getByRole("button", { name: "Last action" });

    lastAction.focus();
    await userEvent.tab();
    await expect(closeButton).toHaveFocus();

    await userEvent.tab({ shift: true });
    await expect(lastAction).toHaveFocus();
  },
};

function RestoresFocusOnCloseHarness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open the modal</button>
      {open && (
        <Modal title="Delete requirement" onClose={() => setOpen(false)}>
          This cannot be undone.
        </Modal>
      )}
    </div>
  );
}

/** Closing the dialog (Escape, here) returns focus to whatever triggered
 * it — a keyboard user isn't dropped at the top of the page. */
export const RestoresFocusOnClose: Story = {
  render: () => <RestoresFocusOnCloseHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Open the modal" });
    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
