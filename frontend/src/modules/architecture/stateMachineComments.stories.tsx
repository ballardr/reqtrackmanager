import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildStateMachineModel } from "./architectureFixtures";
import { layoutFromModel } from "./stateMachineModel";
import { statePinAnchorOf, statePinDescriber, statePinPlaceOf } from "./stateMachineComments";
import { stateLabelsWith } from "./useStateLabel";

function Host() {
  return <p>State machine comment pins: how stored record keys map to the canvas's states and transitions and back.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/StateMachineComments", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const MODEL = buildStateMachineModel();
const LAYOUT = layoutFromModel(MODEL);

export const AStoredPinFollowsItsStateOrTransition: Story = {
  play: async () => {
    await expect(statePinAnchorOf({ anchor_kind: "node", anchor_key: "ste-1" }, MODEL)).toEqual({ kind: "node", id: "ste-1" });
    await expect(statePinAnchorOf({ anchor_kind: "edge", anchor_key: "trn-1" }, MODEL)).toEqual({ kind: "edge", id: "trn-1" });
  },
};

export const APinWhoseStateOrTransitionIsGoneHasNoCanvasAnchor: Story = {
  play: async () => {
    await expect(statePinAnchorOf({ anchor_kind: "node", anchor_key: "gone" }, MODEL)).toBeUndefined();
    await expect(statePinAnchorOf({ anchor_kind: "edge", anchor_key: "gone" }, MODEL)).toBeUndefined();
    await expect(statePinAnchorOf({ anchor_kind: "none", anchor_key: null }, MODEL)).toBeUndefined();
  },
};

export const AClickBecomesAPlaceAnchoredToWhatItLandedOn: Story = {
  play: async () => {
    const idle = LAYOUT.boxes.find((b) => b.id === "ste-1")!;
    await expect(statePinPlaceOf({ x: 10.4, y: 20.6 }, { kind: "none" }, MODEL, LAYOUT)).toEqual({ anchor_kind: "none", anchor_key: null, x: 10, y: 21 });
    await expect(statePinPlaceOf({ x: 0, y: 0 }, { kind: "node", id: "ste-1" }, MODEL, LAYOUT)).toMatchObject({
      anchor_kind: "node", anchor_key: "ste-1", x: Math.round(idle.x + idle.width), y: Math.round(idle.y),
    });
    await expect(statePinPlaceOf({ x: 5, y: 6 }, { kind: "edge", id: "trn-1" }, MODEL, LAYOUT)).toEqual({ anchor_kind: "edge", anchor_key: "trn-1", x: 5, y: 6 });
    await expect(statePinPlaceOf({ x: 1, y: 2 }, { kind: "node", id: "unknown" }, MODEL, LAYOUT)).toEqual({ anchor_kind: "none", anchor_key: null, x: 1, y: 2 });
  },
};

export const TheDescriberNamesStatesAndTransitions: Story = {
  play: async () => {
    const describe = statePinDescriber(MODEL, stateLabelsWith((code) => code));
    await expect(describe.boxName("ste-1")).toBe("STE-001 Idle");
    await expect(describe.lineName("trn-1")).toBe("STE-001 → STE-002");
    await expect(describe.drawn({ anchor_kind: "node", anchor_key: "ste-1" })).toBe(true);
    await expect(describe.drawn({ anchor_kind: "node", anchor_key: "gone" })).toBe(false);
    // The record-code display rule decides how the code reads (here a project code is added).
    await expect(statePinDescriber(MODEL, stateLabelsWith((code) => `PLAT-${code}`)).boxName("ste-1")).toBe("PLAT-STE-001 Idle");
  },
};
