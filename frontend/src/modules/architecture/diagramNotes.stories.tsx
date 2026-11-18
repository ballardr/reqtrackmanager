import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildConnection, buildDiagramView, buildLeader, buildNote, buildViewEdge } from "./architectureFixtures";
import { canvasEdges, canvasLeaders, canvasNodes, commit, isDirty, layoutFromView, layoutToSave, leaderIsDrawn, leaderSummary, noteLeadersSummary, startHistory, type EditorLayout } from "./diagramEditorModel";
import { addLeader, findLeader, leaderOf, leaderTargetFields, newLeader, newNote, patchLeader, removeLeader, setLeaderTarget, updateNote } from "./noteModel";

function Host() {
  return <p>Annotation notes: tone and their leader lines (what each ends at, its route and its ends), as the editor keeps them.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/DiagramNotes", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const LINK = buildConnection();
const LINE = buildViewEdge({ id: "el-1-el-2-con-1", connections: [LINK] });

/** A layout of the fixture view with the given notes. */
function layoutWith(...notes: ReturnType<typeof buildNote>[]): EditorLayout {
  return layoutFromView(buildDiagramView({ edges: [LINE], notes }));
}

const CTX = {
  theme: "light" as const, symbolSvg: () => undefined, lockedLabel: (c: string) => c, emptyNote: "Empty note", noteCaption: "Note",
  showNotes: true, hidden: new Set<string>(), covered: new Set<string>(), coverageLabel: () => "", badges: () => [],
};

export const ANoteKeepsItsToneAndItsLeadersFromTheView: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({
      tone: "danger", leaders: [buildLeader({ kind: "element", element_id: "el-1", x: null, y: null, end_style: "none", start_point: "top" })],
    }));
    const [note] = layout.notes;
    expect(note.tone).toBe("danger");
    const [leader] = note.leaders;
    expect(leaderOf(leader)).toEqual({ kind: "element", elementId: "el-1" });
    expect(leader).toMatchObject({ key: "ld-1", end_style: "none", start_point: "top" });
    const node = canvasNodes(layout, CTX).find((n) => n.id === `note:${note.key}`);
    expect(node?.tone).toBe("danger");
  },
};

export const ALeaderIsSavedWithOnlyTheColumnsOfItsKind: Story = {
  play: async () => {
    let layout = layoutWith(buildNote({ leaders: [buildLeader()] }));
    layout = setLeaderTarget(layout, "ld-1", { kind: "element", elementId: "el-2" });
    expect(layoutToSave(layout).notes[0].leaders[0]).toMatchObject({
      id: "ld-1", kind: "element", element_id: "el-2", connection_id: null, x: null, y: null, end_style: "arrow",
    });
    layout = setLeaderTarget(layout, "ld-1", { kind: "point", x: 5, y: 6 });
    expect(layoutToSave(layout).notes[0].leaders[0]).toMatchObject({ kind: "point", element_id: null, connection_id: null, x: 5, y: 6 });
    layout = setLeaderTarget(layout, "ld-1", { kind: "connection", connectionId: LINK.id });
    expect(layoutToSave(layout).notes[0].leaders[0]).toMatchObject({ kind: "connection", connection_id: LINK.id, x: null, y: null });
  },
};

export const RetargetingALeaderKeepsItsRouteAndItsEnds: Story = {
  play: async () => {
    let layout = layoutWith(buildNote({
      leaders: [buildLeader({ points: [{ x: 1, y: 2 }], line_shape: "spline", start_style: "dot", end_style: "none", start_point: "left" })],
    }));
    layout = setLeaderTarget(layout, "ld-1", { kind: "element", elementId: "el-1" });
    expect(layout.notes[0].leaders[0]).toMatchObject({
      points: [{ x: 1, y: 2 }], line_shape: "spline", start_style: "dot", end_style: "none", start_point: "left", kind: "element",
    });
  },
};

export const ANoteCanHaveSeveralLeadersAndEachIsFoundByKey: Story = {
  play: async () => {
    let layout = layoutWith(buildNote());
    layout = addLeader(layout, "nt-1", newLeader("new-leader-1", { kind: "element", elementId: "el-1" }, "right"));
    layout = addLeader(layout, "nt-1", newLeader("new-leader-2", { kind: "point", x: 1, y: 2 }));
    expect(layout.notes[0].leaders.map((l) => l.key)).toEqual(["new-leader-1", "new-leader-2"]);
    expect(findLeader(layout, "new-leader-2")?.note.key).toBe("nt-1");
    expect(findLeader(layout, "none")).toBeUndefined();
    expect(layoutToSave(layout).notes[0].leaders.map((l) => [l.id, l.kind, l.start_point])).toEqual([
      [null, "element", "right"], [null, "point", null],
    ]);
    layout = removeLeader(layout, "new-leader-1");
    expect(layout.notes[0].leaders.map((l) => l.key)).toEqual(["new-leader-2"]);
  },
};

export const ANoteKeepsAtMostTenLeaders: Story = {
  play: async () => {
    let layout = layoutWith(buildNote());
    for (let i = 0; i < 12; i += 1) layout = addLeader(layout, "nt-1", newLeader(`new-leader-${i}`, { kind: "point", x: i, y: 0 }));
    expect(layout.notes[0].leaders.length).toBe(10);
  },
};

export const ALeaderIsDrawnWithItsRouteStartAndEndsOnTheCanvas: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({
      leaders: [buildLeader({ points: [{ x: 5, y: 6 }], line_shape: "spline", start_point: "bottom", start_style: "dot", end_style: "arrow" })],
    }));
    expect(canvasLeaders(layout, [LINE], new Set())).toEqual([{
      id: "ld-1", from: "note:nt-1", fromPoint: "bottom", points: [{ x: 5, y: 6 }], lineShape: "spline", startEnd: "dot", endEnd: "arrow",
      to: { kind: "point", x: 300, y: -100 },
    }]);
  },
};

export const ATitleAndAnAlignmentAreCarriedToTheCanvasAndTheSave: Story = {
  play: async () => {
    let layout = layoutWith(buildNote({ title: "Heading", text: "One\n\nTwo", text_align: "center" }));
    const [note] = layout.notes;
    expect(note).toMatchObject({ title: "Heading", textAlign: "center" });
    const node = canvasNodes(layout, CTX).find((n) => n.id === `note:${note.key}`);
    // The title is its own line of the node and the text keeps the breaks typed.
    expect(node).toMatchObject({ title: "Heading", label: "One\n\nTwo", textAlign: "center", placeholder: false });
    expect(layoutToSave(layout).notes[0]).toMatchObject({ title: "Heading", text: "One\n\nTwo", text_align: "center" });
    layout = updateNote(layout, "nt-1", { title: "", text: "" });
    expect(canvasNodes(layout, CTX).find((n) => n.id === "note:nt-1")).toMatchObject({ title: undefined, label: "Empty note", placeholder: true });
  },
};

export const ANoteWithOnlyATitleIsNotAPlaceholder: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ title: "Heading", text: "" }));
    expect(canvasNodes(layout, CTX).find((n) => n.id === "note:nt-1")).toMatchObject({ title: "Heading", label: "", placeholder: false });
  },
};

export const ATitleOrAnAlignmentChangeMakesTheLayoutDirtyAndAnUnchangedOneDoesNot: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ title: "Heading" }));
    const history = startHistory(layout);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { title: "Other" })))).toBe(true);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { textAlign: "right" })))).toBe(true);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { title: "Heading", textAlign: "left" })))).toBe(false);
    expect(newNote("k", { x: 0, y: 0 })).toMatchObject({ title: "", textAlign: "left" });
  },
};

export const EditingATonePointingOrAnyPartOfALeaderMakesTheLayoutDirty: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ leaders: [buildLeader()] }));
    const history = startHistory(layout);
    expect(isDirty(history)).toBe(false);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { tone: "info" })))).toBe(true);
    expect(isDirty(commit(history, setLeaderTarget(layout, "ld-1", { kind: "point", x: 1, y: 1 })))).toBe(true);
    for (const change of [
      { points: [{ x: 1, y: 1 }] }, { line_shape: "spline" as const }, { start_style: "dot" as const }, { end_style: "none" as const }, { start_point: "top" as const },
    ]) {
      expect(isDirty(commit(history, patchLeader(layout, "ld-1", change)))).toBe(true);
    }
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { tone: "neutral" })))).toBe(false);
    expect(isDirty(commit(history, patchLeader(layout, "ld-1", { end_style: "arrow" })))).toBe(false);
  },
};

export const ALeaderToAConnectionGoesToTheDrawnLineThatStandsForIt: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ leaders: [buildLeader({ kind: "connection", connection_id: LINK.id, x: null, y: null })] }));
    const drawn = new Set(canvasEdges([LINE], layout, new Set(), "light").map((e) => e.id));
    expect(canvasLeaders(layout, [LINE], drawn)).toMatchObject([{ id: "ld-1", from: "note:nt-1", to: { kind: "edge", id: LINE.id }, endEnd: "arrow" }]);
    // With the line not drawn (an end switched off) the leader is left out and reported as not drawn.
    expect(canvasLeaders(layout, [LINE], new Set())).toEqual([]);
    const [leader] = layout.notes[0].leaders;
    expect(leaderIsDrawn(leader, new Set(["el-1", "el-2"]), [LINE], drawn)).toBe(true);
    expect(leaderIsDrawn(leader, new Set(["el-1", "el-2"]), [LINE], new Set())).toBe(false);
  },
};

export const ALeaderToABoxIsNotDrawnWhileTheBoxIsSwitchedOff: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ leaders: [buildLeader({ kind: "element", element_id: "el-3", x: null, y: null })] }));
    const [leader] = layout.notes[0].leaders;
    expect(leaderIsDrawn(leader, new Set(["el-1", "el-2", "el-3"]), [LINE], new Set())).toBe(true);
    expect(leaderIsDrawn(leader, new Set(["el-1", "el-2"]), [LINE], new Set())).toBe(false);
    expect(leaderSummary(leader, layout.boxes, [LINE], true)).toBe("ELM-003 Firewall");
    expect(leaderSummary(leader, layout.boxes, [LINE], false)).toBe("ELM-003 Firewall (not drawn)");
  },
};

export const TheSummaryNamesWhatEachKindOfLeaderEndsAt: Story = {
  play: async () => {
    const layout = layoutWith();
    const summary = (overrides: Parameters<typeof buildLeader>[0]) =>
      leaderSummary(layoutWith(buildNote({ leaders: [buildLeader(overrides)] })).notes[0].leaders[0], layout.boxes, [LINE], true);
    expect(summary({})).toBe("a spot");
    expect(summary({ kind: "connection", connection_id: LINK.id, x: null, y: null })).toBe(`${LINK.unique_code} ${LINK.name}`);
  },
};

export const ANoteWithSeveralLeadersListsEachInTheOutlineSummary: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({
      leaders: [buildLeader({ id: "a" }), buildLeader({ id: "b", kind: "element", element_id: "el-1", x: null, y: null })],
    }));
    const visible = new Set(["el-1", "el-2"]);
    expect(noteLeadersSummary(layout.notes[0], layout.boxes, [LINE], visible, new Set())).toBe("Points at a spot; Points at ELM-001 Gateway");
    expect(noteLeadersSummary(layoutWith(buildNote()).notes[0], layout.boxes, [LINE], visible, new Set())).toBeNull();
  },
};

export const ANewNoteIsNeutralWithNoLeader: Story = {
  play: async () => {
    const note = newNote("new-1", { x: 10, y: 20 });
    expect(note).toMatchObject({ id: null, tone: "neutral", leaders: [], x: 10, y: 20 });
    expect(newLeader("new-leader-1", { kind: "point", x: 1, y: 2 })).toMatchObject({
      id: null, kind: "point", x: 1, y: 2, start_point: null, points: [], line_shape: null, start_style: "none", end_style: "arrow",
    });
    expect(leaderTargetFields({ kind: "element", elementId: "el-1" })).toEqual({
      kind: "element", element_id: "el-1", connection_id: null, state_id: null, transition_id: null, x: null, y: null,
    });
    expect(leaderTargetFields({ kind: "state", stateId: "ste-1" })).toEqual({
      kind: "state", element_id: null, connection_id: null, state_id: "ste-1", transition_id: null, x: null, y: null,
    });
  },
};
