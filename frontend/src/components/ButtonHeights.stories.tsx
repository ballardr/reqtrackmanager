import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";
import { Plus, Trash2 } from "lucide-react";

import { buttonHeightGeometry, buttonHeightViolations } from "../testing/buttonHeights";

/**
 * Neighbouring buttons share a height (style guide "Pattern: button sizes"): `buttonHeightViolations` measures
 * each row of buttons, including a button inside a wrapper, and fails a small button beside a medium one.
 */
const meta: Meta = { title: "Patterns/Button heights" };
export default meta;

type Story = StoryObj;

/** Medium buttons, text and icon-only, in one row are one height. */
export const MatchingMediumRow: Story = {
  render: () => (
    <div className="row">
      <button className="btn">Undo</button>
      <button className="btn btn-primary">Save</button>
      <button className="btn btn-icon" aria-label="Add"><Plus /></button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(buttonHeightGeometry(canvasElement).measurements.map((m) => m.heightPx)).toEqual([36, 36, 36]);
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** Small buttons in one row are one height. */
export const MatchingSmallRow: Story = {
  render: () => (
    <div className="row">
      <button className="btn btn-sm">Edit</button>
      <button className="btn btn-sm btn-icon" aria-label="Delete"><Trash2 /></button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** A small button beside a medium one is the defect the check exists to find, also when one sits in a wrapper. */
export const CheckDetectsAMixedRow: Story = {
  render: () => (
    <div className="row">
      <button className="btn btn-sm">Undo</button>
      <span className="row"><button className="btn">Export</button></span>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(buttonHeightViolations(canvasElement)).toHaveLength(1);
  },
};

/** A mixed row opts out with `data-button-size-ok`, and a button beside plain text is not compared. */
export const OptOutAndTextNeighbours: Story = {
  render: () => (
    <div className="stack">
      <div className="row" data-button-size-ok="a deliberate pairing in this story">
        <button className="btn btn-sm">Undo</button>
        <button className="btn">Export</button>
      </div>
      <div className="row">
        <span>Some text</span>
        <button className="btn">Export</button>
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};
