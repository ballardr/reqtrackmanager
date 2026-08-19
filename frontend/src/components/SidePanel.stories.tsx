import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { SidePanel } from "./SidePanel";

const meta: Meta<typeof SidePanel> = {
  title: "Components/SidePanel",
  component: SidePanel,
  args: { title: "New change request", onClose: fn(), children: "Change request fields go here." },
};
export default meta;

type Story = StoryObj<typeof SidePanel>;

export const Default: Story = {
  play: async ({ args }) => {
    // Rendered through a portal into document.body, not canvasElement.
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "New change request" })).toBeInTheDocument();
    await expect(body.getByText("Change request fields go here.")).toBeInTheDocument();
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

/** The panel itself stops click propagation, so clicking inside it must
 * NOT trigger the backdrop's close handler. */
export const ClickInsideDoesNotClose: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByText("Change request fields go here."));
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

/** Same focus-trap/restoration behaviour as `Modal` (shared via
 * `dialogA11y.ts`) — see `Modal.stories.tsx` for the equivalent coverage of
 * `AutoFocusChildWins` and `TabTrapCycles`; this file only re-proves the
 * open/restore lifecycle to guard against a future SidePanel-specific
 * regression, not duplicate every case. */
export const FocusMovesIntoDialogOnOpen: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByLabelText("Close")).toHaveFocus();
  },
};

function RestoresFocusOnCloseHarness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open the panel</button>
      {open && (
        <SidePanel title="New change request" onClose={() => setOpen(false)}>
          Change request fields go here.
        </SidePanel>
      )}
    </div>
  );
}

/** Closing the panel (Escape, here) returns focus to whatever triggered
 * it — a keyboard user isn't dropped at the top of the page. */
export const RestoresFocusOnClose: Story = {
  render: () => <RestoresFocusOnCloseHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Open the panel" });
    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
