import type { Meta, StoryObj } from "@storybook/react-vite";
import { Bold } from "lucide-react";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ToggleButton } from "./ToggleButton";

function Harness({ iconOnly = true, action = false, disabled }: { iconOnly?: boolean; action?: boolean; disabled?: boolean }) {
  const [on, setOn] = useState(false);
  return (
    <ToggleButton label="Bold" pressed={action ? undefined : on} iconOnly={iconOnly} disabled={disabled} onClick={() => setOn(!on)}>
      {iconOnly ? <Bold size={14} aria-hidden="true" /> : "Bold"}
    </ToggleButton>
  );
}

/** A pressed-or-not button; the table editor's toolbar and a block form's on/off setting share it. */
const meta: Meta<typeof Harness> = { title: "Components/ToggleButton", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const AnIconToggleReportsItsPressedState: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Bold" });
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(button);
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(button).toHaveClass("btn-marked");
  },
};

export const ATextToggleIsNamedByItsText: Story = {
  args: { iconOnly: false },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Bold" });
    await expect(button).toHaveTextContent("Bold");
    await userEvent.click(button);
    await expect(button).toHaveAttribute("aria-pressed", "true");
  },
};

export const AnActionButtonHasNoPressedState: Story = {
  args: { action: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Bold" })).not.toHaveAttribute("aria-pressed");
  },
};

export const ADisabledToggleDoesNotChange: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Bold" });
    await userEvent.click(button);
    await expect(button).toHaveAttribute("aria-pressed", "false");
  },
};
