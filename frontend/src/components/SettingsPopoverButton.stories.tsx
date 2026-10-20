import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { SettingsPopoverButton } from "./SettingsPopoverButton";

const meta: Meta<typeof SettingsPopoverButton> = {
  title: "Components/SettingsPopoverButton",
  component: SettingsPopoverButton,
  args: {
    label: "Score settings: Severity × Frequency, combined by Weighted average",
    title: "Score settings",
    children: <label>Scoring model <select><option>Severity × Frequency</option></select></label>,
  },
};
export default meta;

type Story = StoryObj<typeof SettingsPopoverButton>;

/** The gear names the current settings, opens a popover and closes on Escape, returning focus to itself. */
export const OpensAndClosesTheSettings: Story = {
  play: async ({ canvasElement }) => {
    const gear = within(canvasElement).getByRole("button", { name: /^Score settings: / });
    await expect(gear).toHaveAttribute("aria-haspopup", "dialog");
    await expect(gear).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(gear);
    await expect(await within(document.body).findByRole("dialog", { name: "Score settings" })).toBeInTheDocument();
    await expect(gear).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("dialog", { name: "Score settings" })).not.toBeInTheDocument();
    await expect(gear).toHaveFocus();
  },
};

/** A non-default choice marks the closed button, so a changed view is visible without opening it. */
export const MarkedWhenNotTheDefault: Story = {
  args: { marked: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: /^Score settings: / })).toHaveClass("btn-marked");
  },
};

export const NotMarkedByDefault: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: /^Score settings: / })).not.toHaveClass("btn-marked");
  },
};
