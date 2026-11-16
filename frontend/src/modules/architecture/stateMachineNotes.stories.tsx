import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildLeader, buildNote, buildState, buildStateMachineModel, buildTransition } from "./architectureFixtures";
import {
  canvasLeaders, canvasNodes, commit, isDirty, layoutFromModel, layoutSignature, layoutToSave, leaderIsDrawn, leaderSummary, leaderTargetOptions,
  mergeModel, moveStates, resizeStates, startHistory, type StateMachineLayout,
} from "./stateMachineModel";
import {
  addLeader, addNote, leaderOf, leaderTargetOf, newLeader, newNote, noteKeyOf, patchLeader, removeNote, setLeaderTarget, updateNote,
} from "./noteModel";

function Host() {
  return <p>Notes on a state machine diagram: their leaders to a state, a transition or a spot, as the editor keeps them.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/StateMachineNotes", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

/** The fixture machine (an initial state, Idle, Running with a loop, a final state) with the given notes. */
function modelWith(...notes: ReturnType<typeof buildNote>[]) {
  return buildStateMachineModel({ notes });
}

const layoutOf = (model: ReturnType<typeof modelWith>): StateMachineLayout => layoutFromModel(model);

const TO_STATE = buildLeader({ id: "ld-1", kind: "state", state_id: "ste-1", x: null, y: null });
const TO_LINE = buildLeader({ id: "ld-2", kind: "transition", transition_id: "trn-1", x: null, y: null });
const TO_SPOT = buildLeader({ id: "ld-3" });

export const ANoteAndItsLeadersComeFromTheModelAndGoBackInTheSave: Story = {
  play: async () => {
    const model = modelWith(buildNote({ title: "Why", text: "Wait", tone: "info", leaders: [TO_STATE, TO_LINE, TO_SPOT] }));
    const layout = layoutOf(model);
    expect(layout.notes[0]).toMatchObject({ key: "nt-1", id: "nt-1", title: "Why", tone: "info" });
    expect(layout.notes[0].leaders.map(leaderOf)).toEqual([
      { kind: "state", stateId: "ste-1" }, { kind: "transition", transitionId: "trn-1" }, { kind: "point", x: 300, y: -100 },
    ]);
    const saved = layoutToSave(layout).notes;
    expect(saved).toHaveLength(1);
    expect(saved[0].leaders.map((l) => [l.kind, l.state_id, l.transition_id, l.element_id, l.connection_id])).toEqual([
      ["state", "ste-1", null, null, null], ["transition", null, "trn-1", null, null], ["point", null, null, null, null],
    ]);
  },
};

export const EditingANoteOrAnyPartOfALeaderMakesTheDrawingDirty: Story = {
  play: async () => {
    const layout = layoutOf(modelWith(buildNote({ leaders: [TO_STATE] })));
    const history = startHistory(layout);
    expect(isDirty(history)).toBe(false);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { title: "New" })))).toBe(true);
    expect(isDirty(commit(history, setLeaderTarget(layout, "ld-1", { kind: "transition", transitionId: "trn-2" })))).toBe(true);
    expect(isDirty(commit(history, patchLeader(layout, "ld-1", { points: [{ x: 1, y: 1 }] })))).toBe(true);
    expect(isDirty(commit(history, removeNote(layout, "nt-1")))).toBe(true);
    expect(isDirty(commit(history, addNote(layout, newNote("new-1", { x: 0, y: 0 }))))).toBe(true);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { tone: "neutral" })))).toBe(false);
    // The signature changes with a note, so a save is offered only for a real change.
    expect(layoutSignature(layout)).not.toBe(layoutSignature(removeNote(layout, "nt-1")));
  },
};

export const TheCanvasDrawsANoteNodeAndALeaderToEachDrawnTarget: Story = {
  play: async () => {
    const model = modelWith(buildNote({ title: "Why", text: "Wait", leaders: [TO_STATE, TO_LINE, TO_SPOT] }));
    const layout = layoutOf(model);
    const nodes = canvasNodes(model, layout, { findings: [] });
    expect(nodes.find((n) => n.id === "note:nt-1")).toMatchObject({ label: "Wait", title: "Why", caption: "Note" });
    expect(canvasLeaders(layout, model)).toMatchObject([
      { id: "ld-1", from: "note:nt-1", to: { kind: "node", id: "ste-1" } },
      { id: "ld-2", from: "note:nt-1", to: { kind: "edge", id: "trn-1" } },
      { id: "ld-3", from: "note:nt-1", to: { kind: "point", x: 300, y: -100 } },
    ]);
  },
};

export const ALeaderToAStateOrTransitionThatIsGoneIsNotDrawnAndSaysSo: Story = {
  play: async () => {
    const model = modelWith(buildNote({ leaders: [TO_STATE, TO_LINE] }));
    const layout = layoutOf(model);
    const gone = { ...model, states: model.states.filter((s) => s.id !== "ste-1"), transitions: model.transitions.filter((t) => t.id !== "trn-1") };
    expect(canvasLeaders(layout, gone)).toEqual([]);
    const [state, line] = layout.notes[0].leaders;
    expect(leaderIsDrawn(state, model)).toBe(true);
    expect(leaderIsDrawn(state, gone)).toBe(false);
    expect(leaderIsDrawn(line, gone)).toBe(false);
    expect(leaderSummary(state, gone)).toBe("a state that is no longer on this diagram");
    expect(leaderSummary(line, gone)).toBe("a transition that is no longer on this diagram");
  },
};

export const ReadingTheModelAgainDropsTheLeadersOfWhatTheServerRemovedAndKeepsTheEditedNotes: Story = {
  play: async () => {
    const model = modelWith(buildNote({ leaders: [TO_STATE, TO_LINE, TO_SPOT] }));
    const edited = updateNote(layoutOf(model), "nt-1", { text: "Edited" });
    // The server removed the state with its transitions (and so the leaders aimed at them).
    const after = { ...model, states: model.states.filter((s) => s.id !== "ste-1"), transitions: model.transitions.filter((t) => t.source_state_id !== "ste-1" && t.target_state_id !== "ste-1") };
    const merged = mergeModel(edited, after);
    expect(merged.notes[0].text).toBe("Edited");
    expect(merged.notes[0].leaders.map((l) => l.key)).toEqual(["ld-3"]);
    // Nothing removed: the edited notes are kept as they are.
    expect(mergeModel(edited, model).notes).toEqual(edited.notes);
  },
};

export const MovingAndResizingANoteMovesOnlyTheNoteAndResizingMakesItManual: Story = {
  play: async () => {
    const model = modelWith(buildNote({ leaders: [] }), buildNote({ id: "nt-2" }));
    const layout = layoutOf(model);
    const moved = moveStates(layout, [{ id: "note:nt-1", x: 10, y: 20 }]);
    expect(moved.notes.map((n) => [n.x, n.y])).toEqual([[10, 20], [0, -120]]);
    expect(moved.boxes).toEqual(layout.boxes);
    const resized = resizeStates(layout, [{ id: "note:nt-2", x: 5, y: 6, width: 300, height: 90 }]);
    expect(resized.notes[1]).toMatchObject({ x: 5, y: 6, width: 300, height: 90, sizeMode: "manual" });
  },
};

export const ThePointsAtListNamesEveryStateAndTransition: Story = {
  play: async () => {
    const model = buildStateMachineModel({
      states: [buildState({ id: "a", unique_code: "STE-001", name: "Idle" }), buildState({ id: "b", unique_code: "STE-002", name: "Running" })],
      transitions: [buildTransition({ id: "t", source_state_id: "a", source_state_code: "STE-001", target_state_id: "b", target_state_code: "STE-002", event: "go" })],
    });
    expect(leaderTargetOptions(model)).toEqual([
      { value: "state:a", label: "State: STE-001 Idle" }, { value: "state:b", label: "State: STE-002 Running" },
      { value: "transition:t", label: "Transition: STE-001 Idle to STE-002 Running (go)" },
    ]);
    expect(leaderTargetOf("state:a")).toEqual({ kind: "state", stateId: "a" });
    expect(leaderTargetOf("transition:t")).toEqual({ kind: "transition", transitionId: "t" });
    expect(leaderTargetOf("element:e")).toEqual({ kind: "element", elementId: "e" });
    expect(leaderTargetOf("connection:c")).toEqual({ kind: "connection", connectionId: "c" });
    for (const value of ["", "spot", "state:", "nothing"]) expect(leaderTargetOf(value)).toBeNull();
  },
};

export const ALeaderIsAddedToANoteUpToTheLimit: Story = {
  play: async () => {
    let layout = layoutOf(modelWith(buildNote({ leaders: [] })));
    for (let i = 0; i < 12; i += 1) layout = addLeader(layout, "nt-1", newLeader(`k${i}`, { kind: "state", stateId: "ste-1" }));
    expect(layout.notes[0].leaders).toHaveLength(10);
    expect(noteKeyOf("note:nt-1")).toBe("nt-1");
    expect(noteKeyOf("ste-1")).toBeNull();
  },
};
