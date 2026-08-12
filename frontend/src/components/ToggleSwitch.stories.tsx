import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { ToggleSwitch } from "./ToggleSwitch";

const meta: Meta<typeof ToggleSwitch> = {
  title: "Components/ToggleSwitch",
  component: ToggleSwitch,
  args: { label: "Require 2FA" },
};
export default meta;

type Story = StoryObj<typeof ToggleSwitch>;

export const Off: Story = {
  args: { checked: false, onChange: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("switch");
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    await expect(args.onChange).toHaveBeenCalledWith(true);
  },
};

export const On: Story = {
  args: { checked: true, onChange: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  },
};

export const Disabled: Story = {
  args: { checked: false, disabled: true, onChange: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("switch")).toBeDisabled();
  },
};

/**
 * PreferencesPage.tsx's 2FA toggle renders this inside a CollapsibleSection
 * title, which wraps its whole header in an onClick that collapses the
 * section — this pins the `stopPropagation` behaviour documented in
 * ToggleSwitch.tsx: clicking the switch must never also fire the header's
 * click handler.
 */
function NestedInClickableHeader() {
  const [collapsed, setCollapsed] = useState(false);
  const [checked, setChecked] = useState(false);
  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setCollapsed((c) => !c)}
        className="row"
        style={{ gap: "0.5rem", cursor: "pointer" }}
      >
        <ToggleSwitch checked={checked} onChange={setChecked} label="Enable 2FA" />
        <span>Two-factor authentication ({collapsed ? "collapsed" : "expanded"})</span>
      </div>
    </div>
  );
}

export const NestedInClickableHeaderStory: StoryObj<typeof NestedInClickableHeader> = {
  name: "Nested in clickable header (stopPropagation)",
  render: () => <NestedInClickableHeader />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/expanded/)).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("switch"));
    // The section must still read "expanded" — the click toggled only the
    // switch, and never bubbled up to collapse the header.
    await expect(canvas.getByText(/expanded/)).toBeInTheDocument();
    await expect(canvas.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  },
};

export const LightTheme: Story = { args: { checked: true, onChange: fn() }, globals: { theme: "light" } };
export const DarkTheme: Story = { args: { checked: true, onChange: fn() }, globals: { theme: "dark" } };
