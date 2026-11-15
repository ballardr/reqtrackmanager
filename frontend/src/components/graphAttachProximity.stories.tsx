import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { ATTACH_NEAR_MARGIN_PX, nearBoxIds, type ProximityBox } from "./graphAttachProximity";

function Host() {
  return <p>Runs the canvas's pointer-nearness rule over its cases.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphAttachProximity", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const box = (x: number, y: number, extra: Partial<ProximityBox> = {}): [string, ProximityBox] => [`b${x}-${y}`, { x, y, width: 160, height: 64, ...extra }];

/** A pointer inside a box, or within the margin outside its edge, is near; one beyond the margin is not. */
export const NearMeansInsideOrWithinTheMargin: Story = {
  play: async () => {
    const boxes = [box(0, 0)];
    await expect([...nearBoxIds(boxes, { x: 80, y: 32 }, 1)]).toEqual(["b0-0"]);
    await expect([...nearBoxIds(boxes, { x: -ATTACH_NEAR_MARGIN_PX, y: 32 }, 1)]).toEqual(["b0-0"]);
    await expect([...nearBoxIds(boxes, { x: -ATTACH_NEAR_MARGIN_PX - 1, y: 32 }, 1)]).toEqual([]);
    await expect([...nearBoxIds(boxes, { x: 160 + ATTACH_NEAR_MARGIN_PX, y: 64 + ATTACH_NEAR_MARGIN_PX }, 1)]).toEqual(["b0-0"]);
    await expect([...nearBoxIds(boxes, { x: 80, y: 64 + ATTACH_NEAR_MARGIN_PX + 1 }, 1)]).toEqual([]);
  },
};

/** The margin is in screen pixels, so it is wider in canvas units when zoomed out and narrower when zoomed in. */
export const TheMarginDoesNotChangeWithZoom: Story = {
  play: async () => {
    const boxes = [box(0, 0)];
    // Zoomed out to half size, 24 screen pixels are 48 canvas units.
    await expect([...nearBoxIds(boxes, { x: -48, y: 32 }, 0.5)]).toEqual(["b0-0"]);
    await expect([...nearBoxIds(boxes, { x: -49, y: 32 }, 0.5)]).toEqual([]);
    // Zoomed in to double size, they are 12 canvas units.
    await expect([...nearBoxIds(boxes, { x: -12, y: 32 }, 2)]).toEqual(["b0-0"]);
    await expect([...nearBoxIds(boxes, { x: -13, y: 32 }, 2)]).toEqual([]);
    // A zoom that is not positive is read as 1.
    await expect([...nearBoxIds(boxes, { x: -24, y: 32 }, 0)]).toEqual(["b0-0"]);
  },
};

/** Only the boxes the pointer is near are named, so a second box far away stays hidden. */
export const OnlyNearBoxesAreNamed: Story = {
  play: async () => {
    const boxes = [box(0, 0), box(400, 0), box(130, 0)];
    await expect([...nearBoxIds(boxes, { x: 150, y: 32 }, 1)].sort()).toEqual(["b0-0", "b130-0"]);
  },
};

/** A container is near only along its edge: a pointer well inside the frame does not show the frame's points. */
export const AContainerIsNearOnlyAlongItsEdge: Story = {
  play: async () => {
    const frame: [string, ProximityBox] = ["frame", { x: 0, y: 0, width: 600, height: 400, container: true }];
    await expect([...nearBoxIds([frame], { x: 300, y: 200 }, 1)]).toEqual([]);
    await expect([...nearBoxIds([frame], { x: 10, y: 200 }, 1)]).toEqual(["frame"]);
    await expect([...nearBoxIds([frame], { x: 600 + 10, y: 200 }, 1)]).toEqual(["frame"]);
    await expect([...nearBoxIds([frame], { x: 300, y: 400 - 20 }, 1)]).toEqual(["frame"]);
    await expect([...nearBoxIds([frame], { x: 300, y: 400 + 30 }, 1)]).toEqual([]);
  },
};
