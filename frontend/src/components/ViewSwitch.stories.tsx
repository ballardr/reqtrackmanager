import type { Meta, StoryObj } from "@storybook/react-vite";
import { Eye, FileCode, Type } from "lucide-react";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { ViewSwitch, type ViewSwitchOption } from "./ViewSwitch";

/** The compact switch between the views of one field. */
const meta: Meta = { title: "Components/ViewSwitch" };
export default meta;

type Story = StoryObj;
type View = "visual" | "write" | "preview";

const OPTIONS: ViewSwitchOption<View>[] = [
  { key: "visual", label: "Visual", icon: Type },
  { key: "write", label: "Write", icon: FileCode },
  { key: "preview", label: "Preview", icon: Eye },
];

/** The chosen view is pressed and each button is named by its view. */
export const PressesTheChosenViewAndReportsChanges: Story = {
  render: () => {
    const onChange = fn();
    function Harness() {
      const [view, setView] = useState<View>("visual");
      return <ViewSwitch label="Editor view" options={OPTIONS} active={view} onChange={(next) => { onChange(next); setView(next); }} />;
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByRole("group", { name: "Editor view" });
    await expect(within(group).getByRole("button", { name: "Visual" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(group).getByRole("button", { name: "Preview" }));
    await expect(within(group).getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
    await expect(within(group).getByRole("button", { name: "Visual" })).toHaveAttribute("aria-pressed", "false");
  },
};

/** The buttons are the toolbar size, in a row of equal buttons. */
export const ButtonsAreToolbarSize: Story = {
  render: () => <ViewSwitch label="Editor view" options={OPTIONS} active="write" onChange={() => {}} />,
  play: async ({ canvasElement }) => {
    const buttons = within(canvasElement).getAllByRole("button");
    await expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      const box = button.getBoundingClientRect();
      await expect(Math.round(box.width)).toBe(28);
      await expect(Math.round(box.height)).toBe(28);
    }
  },
};

/** A disabled field leaves its views unavailable. */
export const DisabledViewsAreUnavailable: Story = {
  render: () => <ViewSwitch label="Editor view" options={OPTIONS} active="write" onChange={() => {}} disabled />,
  play: async ({ canvasElement }) => {
    for (const button of within(canvasElement).getAllByRole("button")) await expect(button).toBeDisabled();
  },
};
