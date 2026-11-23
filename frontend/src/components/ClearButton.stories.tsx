import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ClearButton } from "./ClearButton";

/** The compact X that empties a value or removes an item: icon only, named by its field, tooltip on hover and focus. */
const meta: Meta<typeof ClearButton> = {
  title: "Components/ClearButton",
  component: ClearButton,
  args: { label: "Clear: Owner", onClick: fn() },
  render: (args) => (
    <div className="row" style={{ alignItems: "center", gap: "var(--space-2)" }}>
      <span>Alex Morgan</span>
      <ClearButton {...args} />
    </div>
  ),
};
export default meta;

type Story = StoryObj<typeof ClearButton>;

/** Pressing it reports the click; its name is the label and its glyph is 14px. */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Clear: Owner" });
    await expect(button.querySelector("svg")!.getBoundingClientRect().width).toBe(14);
    await userEvent.click(button);
    await expect(args.onClick).toHaveBeenCalled();
  },
};

/** The tooltip shows the same text on hover and on keyboard focus, never a native title. */
export const TooltipOnHoverAndFocus: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Clear: Owner" });
    await expect(button).not.toHaveAttribute("title");
    await userEvent.hover(button);
    await waitFor(() => expect(within(document.body).getByRole("tooltip", { hidden: true })).toHaveTextContent("Clear: Owner"));
    await userEvent.unhover(button);
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await waitFor(() => expect(within(document.body).getByRole("tooltip", { hidden: true })).toHaveTextContent("Clear: Owner"));
  },
};

/** A disabled control does not report a click. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Clear: Owner" }));
    await expect(args.onClick).not.toHaveBeenCalled();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
