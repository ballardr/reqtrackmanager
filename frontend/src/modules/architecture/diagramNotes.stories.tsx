import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildConnection, buildDiagramView, buildNote, buildViewEdge } from "./architectureFixtures";
import {
  canvasEdges, canvasLeaders, canvasNodes, layoutFromView, layoutToSave, leaderIsDrawn, leaderOf, leaderSummary, newNote, setNoteLeader,
  updateNote, commit, isDirty, startHistory, type EditorLayout,
} from "./diagramEditorModel";

function Host() {
  return <p>Annotation notes: tone, leader line and what it points at, as the editor keeps them.</p>;
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
  showNotes: true, hidden: new Set<string>(), covered: new Set<string>(), coverageLabel: () => "",
};

export const ANoteKeepsItsToneAndLeaderFromTheView: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ tone: "danger", leader_kind: "element", leader_element_id: "el-1", leader_arrow: false }));
    const [note] = layout.notes;
    expect(note.tone).toBe("danger");
    expect(leaderOf(note)).toEqual({ kind: "element", elementId: "el-1" });
    expect(note.leader_arrow).toBe(false);
    const node = canvasNodes(layout, CTX).find((n) => n.id === `note:${note.key}`);
    expect(node?.tone).toBe("danger");
  },
};

export const ALeaderIsSavedWithOnlyTheColumnsOfItsKind: Story = {
  play: async () => {
    let layout = layoutWith(buildNote());
    layout = setNoteLeader(layout, "nt-1", { kind: "element", elementId: "el-2" });
    expect(layoutToSave(layout).notes[0]).toMatchObject({
      leader_kind: "element", leader_element_id: "el-2", leader_connection_id: null, leader_x: null, leader_y: null, leader_arrow: true,
    });
    layout = setNoteLeader(layout, "nt-1", { kind: "point", x: 5, y: 6 });
    expect(layoutToSave(layout).notes[0]).toMatchObject({
      leader_kind: "point", leader_element_id: null, leader_connection_id: null, leader_x: 5, leader_y: 6,
    });
    layout = setNoteLeader(layout, "nt-1", { kind: "none" });
    expect(layoutToSave(layout).notes[0]).toMatchObject({ leader_kind: "none", leader_x: null, leader_y: null });
  },
};

export const ChangingTheArrowheadKeepsTheTargetAndRetargetingKeepsTheArrowhead: Story = {
  play: async () => {
    let layout = layoutWith(buildNote({ leader_kind: "point", leader_x: 1, leader_y: 2 }));
    layout = updateNote(layout, "nt-1", { leader_arrow: false });
    expect(leaderOf(layout.notes[0])).toEqual({ kind: "point", x: 1, y: 2 });
    layout = setNoteLeader(layout, "nt-1", { kind: "element", elementId: "el-1" });
    expect(layout.notes[0].leader_arrow).toBe(false);
  },
};

export const EditingATonePointingOrTheArrowheadMakesTheLayoutDirty: Story = {
  play: async () => {
    const layout = layoutWith(buildNote());
    const history = startHistory(layout);
    expect(isDirty(history)).toBe(false);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { tone: "info" })))).toBe(true);
    expect(isDirty(commit(history, setNoteLeader(layout, "nt-1", { kind: "point", x: 1, y: 1 })))).toBe(true);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { leader_arrow: false })))).toBe(true);
    expect(isDirty(commit(history, updateNote(layout, "nt-1", { tone: "neutral" })))).toBe(false);
  },
};

export const ALeaderToAConnectionGoesToTheDrawnLineThatStandsForIt: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ leader_kind: "connection", leader_connection_id: LINK.id }));
    const drawn = new Set(canvasEdges([LINE], layout, new Set(), "light").map((e) => e.id));
    expect(canvasLeaders(layout, [LINE], drawn)).toEqual([
      { id: "nt-1", from: "note:nt-1", to: { kind: "edge", id: LINE.id }, arrow: true },
    ]);
    // With the line not drawn (an end switched off) the leader is left out and reported as not drawn.
    expect(canvasLeaders(layout, [LINE], new Set())).toEqual([]);
    expect(leaderIsDrawn(layout.notes[0], new Set(["el-1", "el-2"]), [LINE], drawn)).toBe(true);
    expect(leaderIsDrawn(layout.notes[0], new Set(["el-1", "el-2"]), [LINE], new Set())).toBe(false);
  },
};

export const ALeaderToABoxIsNotDrawnWhileTheBoxIsSwitchedOff: Story = {
  play: async () => {
    const layout = layoutWith(buildNote({ leader_kind: "element", leader_element_id: "el-3" }));
    expect(leaderIsDrawn(layout.notes[0], new Set(["el-1", "el-2", "el-3"]), [LINE], new Set())).toBe(true);
    expect(leaderIsDrawn(layout.notes[0], new Set(["el-1", "el-2"]), [LINE], new Set())).toBe(false);
    expect(leaderSummary(layout.notes[0], layout.boxes, [LINE], true)).toBe("Points at ELM-003 Firewall");
    expect(leaderSummary(layout.notes[0], layout.boxes, [LINE], false)).toBe("Points at ELM-003 Firewall (not drawn)");
  },
};

export const TheSummaryNamesWhatEachKindOfLeaderPointsAt: Story = {
  play: async () => {
    const layout = layoutWith();
    const summary = (overrides: Parameters<typeof buildNote>[0]) =>
      leaderSummary(layoutWith(buildNote(overrides)).notes[0], layout.boxes, [LINE], true);
    expect(summary({})).toBeNull();
    expect(summary({ leader_kind: "point", leader_x: 1, leader_y: 2 })).toBe("Points at a spot");
    expect(summary({ leader_kind: "connection", leader_connection_id: LINK.id })).toBe(`Points at ${LINK.unique_code} ${LINK.name}`);
  },
};

export const ANewNoteIsNeutralWithNoLeader: Story = {
  play: async () => {
    const note = newNote("new-1", { x: 10, y: 20 });
    expect(note).toMatchObject({ id: null, tone: "neutral", leader_kind: "none", leader_arrow: true, x: 10, y: 20 });
  },
};
