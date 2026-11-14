import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildState, buildStateMachineModel, buildTransition } from "./architectureFixtures";
import {
  actionLines, canvasEdges, canvasNodes, commit, defaultSize, frameAt, isDirty, layoutFromModel, layoutSignature, mergeModel, moveStates,
  nextFreeSpot, redo, resizeStates, setParent, setTransitionPoints, stateTree, startHistory, transitionLabel, undo,
} from "./stateMachineModel";
import { COMPOSITE_HEADER_HEIGHT, COMPOSITE_PADDING } from "./stateShapes";
import type { StateKind } from "./types";

function Host() {
  return <p>The state machine editor's drawing model: nesting, merging, the canvas mapping and the history.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/StateMachineModel", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const MODEL = buildStateMachineModel();
const LAYOUT = layoutFromModel(MODEL);
const KINDS = new Map<string, StateKind>(MODEL.states.map((s) => [s.id, s.kind]));
const box = (layout: typeof LAYOUT, id: string) => layout.boxes.find((b) => b.id === id)!;

/** A state placed inside another goes to the frame's top left below its name strip, and the frame grows to hold it. */
export const NestingMovesTheStateIntoTheFrameAndGrowsIt: Story = {
  play: async () => {
    const next = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    const child = box(next, "ste-1");
    const frame = box(next, "ste-2");
    await expect(child.parent_state_id).toBe("ste-2");
    await expect(child).toMatchObject({ x: box(LAYOUT, "ste-2").x + COMPOSITE_PADDING, y: box(LAYOUT, "ste-2").y + COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING });
    await expect(frame.x).toBeLessThanOrEqual(child.x - COMPOSITE_PADDING);
    await expect(frame.x + frame.width).toBeGreaterThanOrEqual(child.x + child.width + COMPOSITE_PADDING);
    await expect(frame.y + frame.height).toBeGreaterThanOrEqual(child.y + child.height + COMPOSITE_PADDING);
    // Taking it out again leaves it where it is.
    const out = setParent(next, "ste-1", null, KINDS);
    await expect(box(out, "ste-1")).toMatchObject({ parent_state_id: null, x: child.x, y: child.y });
  },
};

/** A marker cannot hold states, a state cannot be inside itself or inside one of its own descendants, and an unknown id changes nothing. */
export const NestingRefusesWhatWouldBreakTheTree: Story = {
  play: async () => {
    await expect(setParent(LAYOUT, "ste-1", "ste-0", KINDS)).toBe(LAYOUT);
    await expect(setParent(LAYOUT, "ste-1", "ste-1", KINDS)).toBe(LAYOUT);
    await expect(setParent(LAYOUT, "missing", "ste-2", KINDS)).toBe(LAYOUT);
    const nested = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    await expect(setParent(nested, "ste-2", "ste-1", KINDS)).toBe(nested);
  },
};

/** A composite state's children move with it when it is nested: their nesting keeps its shape. */
export const NestingAFrameCarriesItsChildren: Story = {
  play: async () => {
    const inner = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    const before = box(inner, "ste-1");
    const frame = box(inner, "ste-2");
    const outer = buildState({ id: "ste-5", unique_code: "STE-005", name: "Outer", x: 900, y: 500 });
    const withOuter = { ...inner, boxes: [...inner.boxes, { id: outer.id, x: outer.x, y: outer.y, width: outer.width, height: outer.height, collapsed: false, parent_state_id: null }] };
    const kinds = new Map(KINDS).set("ste-5", "state");
    const next = setParent(withOuter, "ste-2", "ste-5", kinds);
    const movedFrame = box(next, "ste-2");
    const movedChild = box(next, "ste-1");
    await expect(movedChild.x - movedFrame.x).toBe(before.x - frame.x);
    await expect(movedChild.y - movedFrame.y).toBe(before.y - frame.y);
  },
};

/** A merged model keeps the local geometry of a state still present, takes a new state's from the server and drops a removed one. */
export const MergingKeepsUnsavedGeometryAndFollowsTheModel: Story = {
  play: async () => {
    const edited = moveStates(LAYOUT, [{ id: "ste-1", x: 999, y: 888 }]);
    const withoutRunning = { ...MODEL, states: MODEL.states.filter((s) => s.id !== "ste-2"), transitions: MODEL.transitions.filter((t) => t.id === "trn-0") };
    const fresh = buildState({ id: "ste-7", unique_code: "STE-007", name: "New", x: 5, y: 6 });
    const merged = mergeModel(edited, { ...withoutRunning, states: [...withoutRunning.states, fresh] });
    await expect(box(merged, "ste-1")).toMatchObject({ x: 999, y: 888 });
    await expect(merged.boxes.some((b) => b.id === "ste-2")).toBe(false);
    await expect(box(merged, "ste-7")).toMatchObject({ x: 5, y: 6 });
    await expect(merged.points.map((p) => p.id)).toEqual(["trn-0"]);
  },
};

/** Canvas nodes: markers are marker shapes with the kind as their label, a state holding others is a container, an error tints its state. */
export const CanvasNodesUseMarkersContainersAndFindingTones: Story = {
  play: async () => {
    const nested = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    const nodes = canvasNodes(MODEL, nested, {
      findings: [{ severity: "error", code: "x", subject: "STE-001", message: "m" }, { severity: "warning", code: "y", subject: "STE-001", message: "m" }, { severity: "warning", code: "z", subject: "STE-002", message: "m" }],
    });
    const byId = new Map(nodes.map((n) => [n.id, n]));
    await expect(byId.get("ste-0")).toMatchObject({ marker: true, label: "Initial state", width: 20, height: 20 });
    await expect(byId.get("ste-0")?.symbolSvg).toContain("<circle");
    await expect(byId.get("ste-3")).toMatchObject({ marker: true, label: "Final state" });
    await expect(byId.get("ste-2")).toMatchObject({ container: true, tone: "warning", caption: "STE-002", body: "do / regulate" });
    await expect(byId.get("ste-1")).toMatchObject({ parentId: "ste-2", container: false, tone: "danger", body: "entry / stop motor\nexit / log" });
    // A frame is listed before the states inside it.
    await expect(nodes.findIndex((n) => n.id === "ste-2")).toBeLessThan(nodes.findIndex((n) => n.id === "ste-1"));
  },
};

/** A line keeps its attach points from the drawing; a transition to the same state is a line from a node to itself. */
export const CanvasEdgesCarryPointsAndLabels: Story = {
  play: async () => {
    const edited = setTransitionPoints(LAYOUT, "trn-1", { sourcePoint: "right", targetPoint: "left" });
    const edges = canvasEdges(MODEL, edited);
    const line = edges.find((e) => e.id === "trn-1")!;
    await expect(line).toMatchObject({ source: "ste-1", target: "ste-2", label: "start [ready]", sourcePoint: "right", targetPoint: "left" });
    await expect(edges.find((e) => e.id === "trn-2")).toMatchObject({ source: "ste-2", target: "ste-2" });
    await expect(edges.find((e) => e.id === "trn-0")?.label).toBeUndefined();
  },
};

export const TransitionLabelsFollowEventGuardAction: Story = {
  play: async () => {
    await expect(transitionLabel(buildTransition({ event: "stop" }))).toBe("stop");
    await expect(transitionLabel(buildTransition({ event: "tick", action: "go" }))).toBe("tick / go");
    await expect(transitionLabel(buildTransition({ event: "", action: "go" }))).toBe("/ go");
    await expect(transitionLabel(buildTransition({ event: "start", guard: "ready" }))).toBe("start [ready]");
    // A long label breaks before the action.
    await expect(transitionLabel(buildTransition({ event: "button pressed", guard: "battery is not low", action: "start the motor" }))).toBe("button pressed [battery is not low]\n/ start the motor");
    await expect(actionLines(buildState({ entry_action: "a", activity: "c" }))).toBe("entry / a\ndo / c");
  },
};

/** The outline's tree follows the drawing's nesting, not the stored parent. */
export const TheStateTreeFollowsTheDrawingsNesting: Story = {
  play: async () => {
    const nested = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    const tree = stateTree(MODEL, nested);
    await expect(tree.map((n) => n.id)).toEqual(["ste-0", "ste-2", "ste-3"]);
    await expect(tree.find((n) => n.id === "ste-2")?.children.map((n) => n.id)).toEqual(["ste-1"]);
  },
};

/** A drop is nested only into a frame that already holds states and only below its name strip. */
export const AFrameAtAPositionIsAnExistingCompositeState: Story = {
  play: async () => {
    const nested = setParent(LAYOUT, "ste-1", "ste-2", KINDS);
    const frame = box(nested, "ste-2");
    await expect(frameAt(nested, KINDS, { x: frame.x + 5, y: frame.y + frame.height - 5 })).toBe("ste-2");
    await expect(frameAt(nested, KINDS, { x: frame.x + 5, y: frame.y + 2 })).toBeNull();
    // A plain state is not turned into a frame by a drop.
    await expect(frameAt(LAYOUT, KINDS, { x: box(LAYOUT, "ste-2").x + 10, y: box(LAYOUT, "ste-2").y + 40 })).toBeNull();
  },
};

export const NewStatesTakeTheNextFreeSlot: Story = {
  play: async () => {
    const size = defaultSize("state");
    const spot = nextFreeSpot(LAYOUT, size);
    await expect(LAYOUT.boxes.some((b) => spot.x < b.x + b.width && spot.x + size.width > b.x && spot.y < b.y + b.height && spot.y + size.height > b.y)).toBe(false);
    await expect(defaultSize("choice")).toEqual({ width: 36, height: 36 });
  },
};

/** The history marks only drawing edits as unsaved, undoes and redoes them, and ignores an edit that changes nothing. */
export const HistoryTracksOnlyTheStoredPartOfTheDrawing: Story = {
  play: async () => {
    let history = startHistory(LAYOUT);
    await expect(isDirty(history)).toBe(false);
    history = commit(history, moveStates(history.present, [{ id: "ste-1", x: 1, y: 2 }]));
    await expect(isDirty(history)).toBe(true);
    const same = commit(history, history.present);
    await expect(same).toBe(history);
    history = commit(history, resizeStates(history.present, [{ id: "ste-2", x: 360, y: 34, width: 300, height: 200 }]));
    history = undo(undo(history));
    await expect(isDirty(history)).toBe(false);
    await expect(layoutSignature(history.present)).toBe(layoutSignature(LAYOUT));
    history = redo(history);
    await expect(isDirty(history)).toBe(true);
  },
};
