import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

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

/** A wide hover target (a whole stat cell or row) where centring on the trigger would be far from the cursor. */
const wideTarget = (args: { label: string }) => (
  <div style={{ width: "100%", margin: "2rem 0" }}>
    <Tooltip {...args} followPointer>
      <button className="btn" style={{ width: "100%", height: 40 }} aria-label={args.label}>
        Wide target
      </button>
    </Tooltip>
  </div>
);
/** Moves the (real, coordinate-carrying) pointer over `target`. */
const point = (target: HTMLElement, clientX: number, clientY: number) => userEvent.pointer({ target, coords: { clientX, clientY } });
const bubbleOf = () => within(document.body).getByRole("tooltip", { hidden: true });
const centreX = (el: HTMLElement) => el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2;

/** `followPointer`: the bubble sits just below the pointer, centred on it, and tracks it as it moves. */
export const FollowsThePointer: Story = {
  args: { label: "Opens the list" },
  render: wideTarget,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button");
    const y = trigger.getBoundingClientRect().top + 20;
    const x = window.innerWidth * 0.75; // over the far right of the target, not its centre
    await point(trigger, x, y);
    // Position is set in a layout effect after the state update, so wait for it to settle.
    await waitFor(() => expect(Math.abs(centreX(bubbleOf()) - x)).toBeLessThanOrEqual(2));
    await expect(bubbleOf().getBoundingClientRect().top).toBeGreaterThan(y); // below the cursor, not covering it
    await point(trigger, x - window.innerWidth * 0.5, y);
    await waitFor(() => expect(Math.abs(centreX(bubbleOf()) - (x - window.innerWidth * 0.5))).toBeLessThanOrEqual(2));
  },
};

/** Near the right edge the bubble is clamped inside the viewport rather than centred off-screen. */
export const FollowingClampsAtTheViewportEdge: Story = {
  args: { label: "Opens the list" },
  render: wideTarget,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button");
    await point(trigger, window.innerWidth - 2, 100);
    await waitFor(() => expect(bubbleOf()).toHaveStyle({ opacity: "1" }));
    await expect(bubbleOf().getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth - 8 + 1);
    await expect(bubbleOf().getBoundingClientRect().left).toBeGreaterThanOrEqual(8 - 1);
  },
};

/** With no room below the pointer the bubble flips above it. */
export const FollowingFlipsAboveNearTheBottom: Story = {
  args: { label: "Opens the list" },
  render: wideTarget,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button");
    const y = window.innerHeight - 6;
    await point(trigger, 300, y);
    await waitFor(() => expect(bubbleOf()).toHaveStyle({ opacity: "1" }));
    await expect(bubbleOf().getBoundingClientRect().bottom).toBeLessThanOrEqual(y);
    await expect(bubbleOf().getBoundingClientRect().top).toBeGreaterThan(0); // actually placed, not left at the origin
  },
};

/** Keyboard focus has no pointer, so it keeps the trigger-centred placement. */
export const FollowingFallsBackToTheTriggerOnKeyboardFocus: Story = {
  args: { label: "Opens the list" },
  render: wideTarget,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button");
    trigger.focus();
    await waitFor(() => expect(bubbleOf()).toHaveStyle({ opacity: "1" }));
    await waitFor(() => expect(Math.abs(centreX(bubbleOf()) - centreX(trigger))).toBeLessThanOrEqual(2));
  },
};
