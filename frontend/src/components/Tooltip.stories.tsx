import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { Tooltip } from "./Tooltip";

const meta: Meta<typeof Tooltip> = {
  title: "Components/Tooltip",
  component: Tooltip,
  args: { label: "Collapse sidebar" },
};
export default meta;

type Story = StoryObj<typeof Tooltip>;

export const HoverShowsLabel: Story = {
  render: (args) => (
    <Tooltip {...args}>
      <button className="btn" aria-label={args.label}>
        ⇤
      </button>
    </Tooltip>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button");
    // Rendered through a portal, so the bubble lives in document.body.
    const bubble = within(document.body).getByRole("tooltip", { hidden: true });
    await expect(bubble).toHaveStyle({ opacity: "0" });
    await userEvent.hover(trigger);
    await expect(bubble).toHaveTextContent("Collapse sidebar");
    await expect(bubble).toHaveStyle({ opacity: "1" });
    await userEvent.unhover(trigger);
    await expect(bubble).toHaveStyle({ opacity: "0" });
  },
};

/**
 * Trigger pinned at the top-left corner of the viewport: with no room
 * above, the bubble must fall back to appearing below the trigger instead
 * of positioning off-screen (the `spaceAbove < VIEWPORT_MARGIN_PX` branch
 * in Tooltip.tsx).
 */
export const ClampsNearViewportEdge: Story = {
  render: (args) => (
    <div style={{ position: "fixed", top: 0, left: 0 }}>
      <Tooltip {...args}>
        <button className="btn" aria-label={args.label}>
          ⇤
        </button>
      </Tooltip>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button");
    await userEvent.hover(trigger);
    const bubble = within(document.body).getByRole("tooltip", { hidden: true });
    const bubbleTop = Number.parseFloat(bubble.style.top || "0");
    await expect(bubbleTop).toBeGreaterThanOrEqual(0);
  },
};

export const LightTheme: Story = {
  ...HoverShowsLabel,
  globals: { theme: "light" },
};
export const DarkTheme: Story = {
  ...HoverShowsLabel,
  globals: { theme: "dark" },
};
