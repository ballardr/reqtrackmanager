import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildConnection, buildDiagramView, buildViewEdge } from "./architectureFixtures";
import { layoutFromView } from "./diagramEditorModel";
import { pinAnchorOf, pinPlaceOf } from "./diagramComments";

function Host() {
  return <p>Comment pins: how stored record keys map to the canvas's boxes and lines and back.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/DiagramComments", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const LINK = buildConnection();
const LINE = buildViewEdge({ id: "el-1-el-2-rolled", connections: [LINK] });
const LAYOUT = layoutFromView(buildDiagramView({ edges: [LINE] }));
const [FIRST_BOX] = LAYOUT.boxes;

export const AStoredBoxPinFollowsItsBoxAndALineFollowsItsConnection: Story = {
  play: async () => {
    expect(pinAnchorOf({ anchor_kind: "node", anchor_key: FIRST_BOX.elementId }, LAYOUT.boxes, [LINE])).toEqual({ kind: "node", id: FIRST_BOX.elementId });
    // A line is found by one of the connections it stands for, whatever id the drawn line has now.
    expect(pinAnchorOf({ anchor_kind: "edge", anchor_key: LINK.id }, LAYOUT.boxes, [LINE])).toEqual({ kind: "edge", id: LINE.id });
  },
};

export const APinWhoseBoxOrLineIsNotDrawnHasNoCanvasAnchor: Story = {
  play: async () => {
    expect(pinAnchorOf({ anchor_kind: "node", anchor_key: "no-such-box" }, LAYOUT.boxes, [LINE])).toBeUndefined();
    expect(pinAnchorOf({ anchor_kind: "edge", anchor_key: LINK.id }, LAYOUT.boxes, [])).toBeUndefined();
    expect(pinAnchorOf({ anchor_kind: "none", anchor_key: null }, LAYOUT.boxes, [LINE])).toBeUndefined();
  },
};

export const AClickBecomesAPlaceAnchoredToWhatItLandedOn: Story = {
  play: async () => {
    const free = pinPlaceOf({ x: 10.4, y: 20.6 }, { kind: "none" }, LAYOUT.boxes, [LINE]);
    expect(free).toEqual({ anchor_kind: "none", anchor_key: null, x: 10, y: 21 });
    const onBox = pinPlaceOf({ x: 0, y: 0 }, { kind: "node", id: FIRST_BOX.elementId }, LAYOUT.boxes, [LINE]);
    expect(onBox).toMatchObject({ anchor_kind: "node", anchor_key: FIRST_BOX.elementId, x: Math.round(FIRST_BOX.x + FIRST_BOX.width), y: Math.round(FIRST_BOX.y) });
    const onLine = pinPlaceOf({ x: 5, y: 6 }, { kind: "edge", id: LINE.id }, LAYOUT.boxes, [LINE]);
    expect(onLine).toEqual({ anchor_kind: "edge", anchor_key: LINK.id, x: 5, y: 6 });
  },
};

export const AClickOnANoteOrAnUnknownItemIsAFreePin: Story = {
  play: async () => {
    expect(pinPlaceOf({ x: 1, y: 2 }, { kind: "node", id: "note:abc" }, LAYOUT.boxes, [LINE])).toEqual({ anchor_kind: "none", anchor_key: null, x: 1, y: 2 });
    expect(pinPlaceOf({ x: 1, y: 2 }, { kind: "edge", id: "missing" }, LAYOUT.boxes, [LINE])).toEqual({ anchor_kind: "none", anchor_key: null, x: 1, y: 2 });
  },
};
