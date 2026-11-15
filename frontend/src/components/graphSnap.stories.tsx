import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { snapApplies, snapCoordinate, snapResize } from "./graphSnap";

function Host() {
  return <p>Runs the canvas's grid rule over its cases.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphSnap", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

/** A coordinate lands on the nearest grid line, negative ones included, and a line is left alone. */
export const SnapsACoordinateToTheNearestLine: Story = {
  play: async () => {
    await expect(snapCoordinate(0, 20)).toBe(0);
    await expect(snapCoordinate(9, 20)).toBe(0);
    await expect(snapCoordinate(11, 20)).toBe(20);
    await expect(snapCoordinate(587, 20)).toBe(580);
    await expect(snapCoordinate(-9, 20)).toBe(0);
    await expect(Object.is(snapCoordinate(-9, 20), 0)).toBe(true);
    await expect(snapCoordinate(-11, 20)).toBe(-20);
    await expect(snapCoordinate(-143, 20)).toBe(-140);
    await expect(snapCoordinate(40, 20)).toBe(40);
    // No grid, no change.
    await expect(snapCoordinate(13, 0)).toBe(13);
  },
};

/** A nested box is in absolute coordinates, so it snaps to the same lines as a top-level one whatever its parent's position. */
export const NestedBoxesShareTheTopLevelGrid: Story = {
  play: async () => {
    // A parent at (33, 47) holding a child at absolute (53, 91): the child's own position is not what is snapped.
    await expect(snapCoordinate(53, 20)).toBe(60);
    await expect(snapCoordinate(91, 20)).toBe(100);
  },
};

/** A resize puts the edges it moved on the grid and leaves the others where they were. */
export const ResizeSnapsOnlyTheEdgesItMoved: Story = {
  play: async () => {
    const before = { x: 0, y: 0, width: 160, height: 64 };
    // Bottom right handle: the right and bottom edges move.
    await expect(snapResize(before, { x: 0, y: 0, width: 187, height: 81 }, 20, 80, 40)).toEqual({ x: 0, y: 0, width: 180, height: 80 });
    // Top left handle: the left and top edges move and the right and bottom edges stay.
    await expect(snapResize(before, { x: -27, y: -13, width: 187, height: 77 }, 20, 80, 40)).toEqual({ x: -20, y: -20, width: 180, height: 84 });
    // A box already off the grid is not moved by a resize that leaves its top left corner alone.
    const off = { x: 13, y: 7, width: 160, height: 64 };
    await expect(snapResize(off, { x: 13, y: 7, width: 170, height: 64 }, 20, 80, 40)).toEqual({ x: 13, y: 7, width: 167, height: 64 });
  },
};

/** Snapping never takes a box below its minimum size, and the edge that did not move stays fixed at the minimum. */
export const ResizeKeepsTheMinimumSize: Story = {
  play: async () => {
    const before = { x: 0, y: 0, width: 160, height: 64 };
    await expect(snapResize(before, { x: 0, y: 0, width: 83, height: 41 }, 20, 80, 40)).toEqual({ x: 0, y: 0, width: 80, height: 40 });
    // Dragging the left edge far right: the right edge stays at 160 and the box stops at the minimum width.
    await expect(snapResize(before, { x: 150, y: 0, width: 10, height: 64 }, 20, 80, 40)).toEqual({ x: 80, y: 0, width: 80, height: 64 });
  },
};

/** The invert key flips the setting during a pointer gesture only. */
export const TheInvertKeyActsOnlyDuringAGesture: Story = {
  play: async () => {
    await expect(snapApplies(false, false, false)).toBe(false);
    await expect(snapApplies(true, false, false)).toBe(true);
    await expect(snapApplies(false, true, true)).toBe(true);
    await expect(snapApplies(true, true, true)).toBe(false);
    // Held with no pointer gesture (a key-driven move): the setting alone decides.
    await expect(snapApplies(false, true, false)).toBe(false);
    await expect(snapApplies(true, true, false)).toBe(true);
  },
};
