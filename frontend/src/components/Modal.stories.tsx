import type { Meta, StoryObj } from "@storybook/react-vite";
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

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
