import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import type { BadgeTone } from "../api/types";
import { orphanedControlViolations } from "../testing/orphanedControls";
import { Badge } from "./Badge";

/**
 * The one pill (style guide "Pattern: pills"): one height, centred text, never shrinks or stretches,
 * one line up to a maximum width, then two lines, then clipped with a Tooltip.
 */
const meta: Meta<typeof Badge> = {
  title: "Components/Badge",
  component: Badge,
  args: { children: "Approved" },
};
export default meta;

type Story = StoryObj<typeof Badge>;

const TONES: (BadgeTone | undefined)[] = [undefined, "muted", "info", "accent", "warning", "danger"];

export const Default: Story = {};

/** Every tone is the same height; only the colour differs. */
export const EveryToneIsTheSameHeight: Story = {
  render: () => (
    <div className="row" data-testid="tones">
      {TONES.map((tone) => <Badge key={tone ?? "neutral"} tone={tone}>{tone ?? "neutral"}</Badge>)}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const heights = new Set(
      Array.from(canvasElement.querySelectorAll(".badge")).map((b) => Math.round(b.getBoundingClientRect().height)),
    );
    await expect(heights.size).toBe(1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** A container with `badge-column` gives every pill in it one width; each use picks the justification. */
export const SharedWidthColumnWithAlignment: Story = {
  render: () => (
    <div className="stack badge-column" style={{ alignItems: "flex-start" }}>
      <Badge tone="muted">Draft</Badge>
      <Badge tone="info" align="start">In review</Badge>
      <Badge tone="accent" align="end">Approved</Badge>
      <Badge tone="danger">Rejected</Badge>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const widths = new Set(
      Array.from(canvasElement.querySelectorAll(".badge")).map((b) => Math.round(b.getBoundingClientRect().width)),
    );
    await expect(widths.size).toBe(1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** `minWidth` does the same for one use without a container class. */
export const MinWidthProp: Story = { args: { minWidth: "10rem", children: "Short" } };

/** A label past the one-line limit wraps, centred, to two lines at the maximum width; the pill is then at its cap. */
export const TwoLinesAtTheMaximumWidth: Story = {
  args: { tone: "info", children: "Awaiting sign-off from the safety board" },
  play: async ({ canvasElement }) => {
    const pill = canvasElement.querySelector<HTMLElement>(".badge")!;
    await expect(pill.getBoundingClientRect().height).toBeGreaterThan(30);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** Past two lines the text is clipped and the full text is offered on hover or focus. */
export const TruncatesBeyondTwoLinesWithATooltip: Story = {
  args: { tone: "warning", children: "A forty-character status name that goes on and on and on well past two lines of text" },
  play: async ({ canvasElement }) => {
    const pill = canvasElement.querySelector<HTMLElement>(".badge")!;
    await expect(pill.getBoundingClientRect().height).toBeLessThan(40);
    await expect(pill.scrollHeight).toBeGreaterThanOrEqual(pill.clientHeight);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** An icon sits before the label and does not change the pill's height. */
export const WithIcon: Story = {
  args: { icon: <span aria-hidden="true">●</span>, children: "Locked" },
};

/** A pill beside a long title stays on the title's line and keeps its shape. */
export const BesideALongTitle: Story = {
  render: () => (
    <div style={{ width: 320 }}>
      <span>A very long record title that will certainly need to wrap </span>
      <Badge tone="muted" className="badge-after">Draft</Badge>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Draft")).toBeVisible();
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};
