import type { Meta, StoryObj } from "@storybook/react-vite";
import { Bold } from "lucide-react";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ToggleButton } from "./ToggleButton";

function Harness({ iconOnly = true, action = false, disabled, help }: { iconOnly?: boolean; action?: boolean; disabled?: boolean; help?: string }) {
  const [on, setOn] = useState(false);
  return (
    <ToggleButton label="Bold" pressed={action ? undefined : on} iconOnly={iconOnly} disabled={disabled} help={help} onClick={() => setOn(!on)}>
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

/** A text toggle's help is its own tooltip, one line per state, opened by hover and by keyboard focus, with no `(?)` beside it. */
export const ATextToggleShowsItsHelpOnTheButton: Story = {
  args: { iconOnly: false, help: "On: text is bold.\nOff: text is regular." },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Bold" });
    await expect(within(canvasElement).queryByRole("button", { name: /^Help:/ })).not.toBeInTheDocument();
    await userEvent.hover(button);
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On: text is bold.");
    await expect(tip).toHaveTextContent("Off: text is regular.");
    await expect(button).toHaveAttribute("aria-describedby", tip.id);
    await userEvent.unhover(button);
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(await within(document.body).findByRole("tooltip")).toBeInTheDocument();
  },
};

/** An icon-only button with help names itself first, then the help, in one tooltip. */
export const AnIconToggleShowsItsNameThenItsHelp: Story = {
  args: { help: "Makes the selection bold." },
  play: async ({ canvasElement }) => {
    await userEvent.hover(within(canvasElement).getByRole("button", { name: "Bold" }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Bold");
    await expect(tip).toHaveTextContent("Makes the selection bold.");
  },
};
