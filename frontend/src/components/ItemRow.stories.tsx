import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { orphanedControlViolations } from "../testing/orphanedControls";
import { ItemRow } from "./ItemRow";

const LONG = "An exceptionally long record title that keeps going well past any sensible single line of text "
  + "so that every control placed beside it is put under real pressure to stay where it belongs";

/**
 * Text beside controls (style guide "Pattern: text beside controls"): the text wraps inside its own box,
 * the actions never move to a new line.
 */
const meta: Meta<typeof ItemRow> = {
  title: "Components/ItemRow",
  component: ItemRow,
  decorators: [(Story) => <div style={{ width: 420 }}><Story /></div>],
};
export default meta;

type Story = StoryObj<typeof ItemRow>;

const actions = (
  <>
    <button className="btn btn-sm">Edit</button>
    <button className="btn btn-sm btn-danger">Delete</button>
  </>
);

export const ShortText: Story = { args: { children: "Short title", actions } };

/** A 200-character title wraps within its own box; both buttons stay beside it. */
export const LongTitleKeepsActionsBesideIt: Story = {
  args: { children: LONG, actions },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const edit = canvas.getByRole("button", { name: "Edit" }).getBoundingClientRect();
    const text = canvasElement.querySelector(".item-row__content")!.getBoundingClientRect();
    // Beside the text (to its right), not under it, and the text is the part that grew.
    await expect(edit.left).toBeGreaterThanOrEqual(text.right - 1);
    await expect(text.height).toBeGreaterThan(edit.height * 2);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** A single unbroken token longer than the row still wraps (`overflow-wrap: anywhere`) rather than pushing the actions out. */
export const UnbrokenTokenDoesNotPushActionsOut: Story = {
  args: { children: "x".repeat(200), actions },
  play: async ({ canvasElement }) => {
    const row = canvasElement.querySelector<HTMLElement>(".item-row")!;
    await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
  },
};

/** The guard itself: a plain wrapping `.row` with the same content is reported, so a regression cannot pass unnoticed. */
export const GuardReportsAWrappingRow: Story = {
  render: () => (
    <div className="row" style={{ width: 420 }}>
      <span>{LONG}</span>
      <button className="btn btn-sm" style={{ flex: "none" }}>Delete</button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const violations = orphanedControlViolations(canvasElement);
    await expect(violations.some((v) => v.includes("alone at the start of a new line"))).toBe(true);
  },
};

/** A container that opts out with `data-wrap-ok` (a toolbar meant to wrap) is not reported. */
export const OptOutIsHonoured: Story = {
  render: () => (
    <div className="row" data-wrap-ok style={{ width: 420 }}>
      <span>{LONG}</span>
      <button className="btn btn-sm">Delete</button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};
