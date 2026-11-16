/**
 * Module: modules/architecture/noteModel
 *
 * The annotation notes of a diagram, as plain functions with no React, for both diagram editors (block diagram and state
 * machine diagram): the note and its leader lines while being edited, the edits a person makes, the request body of a save and
 * the mapping to the shared canvas's nodes and leader lines.
 *
 * Responsibilities:
 * - `EditorNote` / `EditorLeader`: a note with its title, text, tone, alignment, size mode and none or several leader lines. A
 *   leader ends at a box (`element`) or a line (`connection`) of a block diagram, a state or a transition of a state machine
 *   diagram, or a free point (`NoteLeaderTarget`).
 * - Edits over any layout that holds `notes` (`NotesLayout`): they return a new layout of the same kind, so one set of functions
 *   serves both editors and each keeps the rest of its own layout.
 * - `canvasNoteNodes` / `noteLeaderLines`: the shared canvas's nodes for notes and the lines for leaders; what a target is on
 *   the canvas (a node, a line, a point) is the caller's, so no diagram type is known here.
 *
 * Design decisions:
 * - A note's canvas node id is `NOTE_NODE_PREFIX + key`, whatever the diagram type, so a selection tells a note from a box
 *   by its id alone.
 * - The size a note is drawn at comes from `noteLayout` (the same measure the server's drawing uses), never from here.
 */
import type { GraphCanvasLeader, GraphCanvasNode } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import { suggestWaypoint } from "../../components/graphLinePath";
import { NOTE_PADDING, drawnSize } from "./noteLayout";
import type {
  DiagramLeader, DiagramNote, LeaderKind, LeaderValues, LineWaypoint, NoteSizeMode, NoteTextAlign, NoteTone, NoteValues,
} from "./types";

/** Default size of a new note. */
export const NOTE_WIDTH = 160;
export const NOTE_HEIGHT = 60;
/** Prefix of a note's canvas node id, so a node is told from an element or a state by its id alone. */
export const NOTE_NODE_PREFIX = "note:";
/** How far to the right of a note a leader added from its card ends, in canvas units. */
export const LEADER_REACH = 120;
/** The most leader lines one note may have (the server's limit). */
export const MAX_NOTE_LEADERS = 10;

/** One leader line of a note while editing; `id` is null until it is saved, `key` is stable (the id once stored) and names the leader on the canvas. */
export interface EditorLeader {
  key: string;
  id: string | null;
  kind: LeaderKind;
  element_id: string | null;
  connection_id: string | null;
  state_id: string | null;
  transition_id: string | null;
  x: number | null;
  y: number | null;
  start_point: AttachPoint | null;
  points: LineWaypoint[];
  smooth: boolean;
  start_style: LeaderValues["start_style"];
  end_style: LeaderValues["end_style"];
}

/** An annotation: plain text in a toned block with none or several leader lines; `id` is null until it is saved, `key` is stable while editing. */
export interface EditorNote {
  key: string;
  id: string | null;
  /** A short heading drawn in bold above the text; empty for none. */
  title: string;
  /** The text; the line breaks typed are kept. */
  text: string;
  x: number;
  y: number;
  /** The stored size: the size drawn when `sizeMode` is manual, and the size a note returns to from automatic. */
  width: number;
  height: number;
  tone: NoteTone;
  textAlign: NoteTextAlign;
  /** Whether the note is drawn at the size its content needs (`noteFrame`) or at the stored one. */
  sizeMode: NoteSizeMode;
  leaders: EditorLeader[];
}

/** Any layout that holds notes; the edits below return the layout they were given, with its notes changed. */
export interface NotesLayout {
  notes: EditorNote[];
}

/** What a leader ends at, as one value. */
export type NoteLeaderTarget =
  | { kind: "element"; elementId: string }
  | { kind: "connection"; connectionId: string }
  | { kind: "state"; stateId: string }
  | { kind: "transition"; transitionId: string }
  | { kind: "point"; x: number; y: number };

/** @param leader A leader. @returns What it ends at (null when the target fields do not match its kind). */
export function leaderOf(
  leader: Pick<EditorLeader, "kind" | "element_id" | "connection_id" | "state_id" | "transition_id" | "x" | "y">,
): NoteLeaderTarget | null {
  if (leader.kind === "element" && leader.element_id) return { kind: "element", elementId: leader.element_id };
  if (leader.kind === "connection" && leader.connection_id) return { kind: "connection", connectionId: leader.connection_id };
  if (leader.kind === "state" && leader.state_id) return { kind: "state", stateId: leader.state_id };
  if (leader.kind === "transition" && leader.transition_id) return { kind: "transition", transitionId: leader.transition_id };
  if (leader.kind === "point" && leader.x !== null && leader.y !== null) return { kind: "point", x: leader.x, y: leader.y };
  return null;
}

/** The "Points at" option value of a free position. */
export const LEADER_SPOT_OPTION = "spot";

/** @param target What a leader ends at. @returns The "Points at" list's option value for it. */
export function leaderOptionValue(target: NoteLeaderTarget | null): string {
  if (target?.kind === "element") return `element:${target.elementId}`;
  if (target?.kind === "connection") return `connection:${target.connectionId}`;
  if (target?.kind === "state") return `state:${target.stateId}`;
  if (target?.kind === "transition") return `transition:${target.transitionId}`;
  return target?.kind === "point" ? LEADER_SPOT_OPTION : "";
}

/** @param value An option value of the "Points at" list (`leaderOptionValue`). @returns The target it names, or null for a spot or an empty value (a spot needs coordinates the caller chooses). */
export function leaderTargetOf(value: string): NoteLeaderTarget | null {
  const at = value.indexOf(":");
  const kind = value.slice(0, at);
  const id = value.slice(at + 1);
  if (at < 0 || !id) return null;
  if (kind === "element") return { kind, elementId: id };
  if (kind === "connection") return { kind, connectionId: id };
  if (kind === "state") return { kind, stateId: id };
  if (kind === "transition") return { kind, transitionId: id };
  return null;
}

/** @param target What a leader ends at. @returns The leader fields that hold it (the others emptied, as the server requires). */
export function leaderTargetFields(
  target: NoteLeaderTarget,
): Pick<EditorLeader, "kind" | "element_id" | "connection_id" | "state_id" | "transition_id" | "x" | "y"> {
  return {
    kind: target.kind,
    element_id: target.kind === "element" ? target.elementId : null,
    connection_id: target.kind === "connection" ? target.connectionId : null,
    state_id: target.kind === "state" ? target.stateId : null,
    transition_id: target.kind === "transition" ? target.transitionId : null,
    x: target.kind === "point" ? target.x : null,
    y: target.kind === "point" ? target.y : null,
  };
}

/** @param key A fresh leader key. @param target Where it ends. @param start The attach point of the note it leaves from, or null for the nearest. @returns A new straight leader with an arrowhead at its end. */
export function newLeader(key: string, target: NoteLeaderTarget, start: AttachPoint | null = null): EditorLeader {
  return { key, id: null, ...leaderTargetFields(target), start_point: start, points: [], smooth: false, start_style: "none", end_style: "arrow" };
}

/** @param leader A leader of a resolved view or model. @returns Its editor form (its key is its id). */
export function leaderFromView(leader: DiagramLeader): EditorLeader {
  return {
    key: leader.id, id: leader.id, kind: leader.kind, element_id: leader.element_id, connection_id: leader.connection_id,
    state_id: leader.state_id, transition_id: leader.transition_id, x: leader.x, y: leader.y,
    start_point: leader.start_point, points: leader.points, smooth: leader.smooth, start_style: leader.start_style, end_style: leader.end_style,
  };
}

/** @param leader A leader being edited. @returns The request body of it. */
export function leaderToValues(leader: EditorLeader): LeaderValues {
  return {
    id: leader.id, kind: leader.kind, element_id: leader.element_id, connection_id: leader.connection_id, state_id: leader.state_id,
    transition_id: leader.transition_id, x: leader.x, y: leader.y,
    start_point: leader.start_point, points: leader.points, smooth: leader.smooth, start_style: leader.start_style, end_style: leader.end_style,
  };
}

/** @param note A note of a resolved view or model. @returns Its editor form (its key is its id). */
export function noteFromView(note: DiagramNote): EditorNote {
  return {
    key: note.id, id: note.id, title: note.title, text: note.text, x: note.x, y: note.y, width: note.width, height: note.height,
    tone: note.tone, textAlign: note.text_align, sizeMode: note.size_mode,
    leaders: note.leaders.map(leaderFromView),
  };
}

/** @param note A note being edited. @returns The request body of it. */
export function noteToValues(note: EditorNote): NoteValues {
  return {
    id: note.id, title: note.title, text: note.text, x: note.x, y: note.y, width: note.width, height: note.height, tone: note.tone,
    text_align: note.textAlign, size_mode: note.sizeMode, leaders: note.leaders.map(leaderToValues),
  };
}

/** @param notes Notes being edited. @returns What a save of them would send, as comparable data (for telling whether they changed). */
export function notesSignature(notes: readonly EditorNote[]): unknown[] {
  return notes.map(noteToValues).map((n) => [
    n.title, n.text, n.x, n.y, n.width, n.height, n.tone, n.text_align, n.size_mode,
    n.leaders.map((l) => [
      l.kind, l.element_id, l.connection_id, l.state_id, l.transition_id, l.x, l.y, l.start_point, l.points.map((p) => [p.x, p.y]), l.smooth,
      l.start_style, l.end_style,
    ]),
  ]);
}

// --- Edits (each returns a new layout) ---

/** @param key A fresh note key. @param at Where its top-left corner goes. @returns A new, empty, neutral note with no leader. */
export function newNote(key: string, at: { x: number; y: number }): EditorNote {
  return {
    key, id: null, title: "", text: "", x: at.x, y: at.y, width: NOTE_WIDTH, height: NOTE_HEIGHT, tone: "neutral", textAlign: "left", sizeMode: "automatic",
    leaders: [],
  };
}

/** Adds a note. */
export function addNote<L extends NotesLayout>(layout: L, note: EditorNote): L {
  return { ...layout, notes: [...layout.notes, note] };
}

/** What the Selection card changes about a note. */
export type NotePatch = Partial<Pick<EditorNote, "title" | "text" | "tone" | "textAlign" | "sizeMode" | "width" | "height">>;

/**
 * The size a note is drawn at: the frame its content needs when its size is automatic, else the stored size.
 *
 * @param note The note.
 * @returns The width and height the canvas, the leaders' attach points and the exports use for it.
 */
export function noteFrame(note: EditorNote): { width: number; height: number } {
  return drawnSize(note);
}

/** Changes the title, text, tone, alignment, size mode or stored size of a note. */
export function updateNote<L extends NotesLayout>(layout: L, key: string, patch: NotePatch): L {
  return { ...layout, notes: layout.notes.map((n) => (n.key === key ? { ...n, ...patch } : n)) };
}

/** Moves notes; `id`s are canvas node ids (`NOTE_NODE_PREFIX` and the note's key), and any other id is ignored. */
export function moveNotes<L extends NotesLayout>(layout: L, moves: readonly { id: string; x: number; y: number }[]): L {
  const to = new Map(moves.map((m) => [m.id, m]));
  return {
    ...layout,
    notes: layout.notes.map((n) => {
      const m = to.get(NOTE_NODE_PREFIX + n.key);
      return m ? { ...n, x: m.x, y: m.y } : n;
    }),
  };
}

/** Moves and resizes notes to the final geometry of a resize; a note the person resizes is sized manually from then on, at the size just drawn. */
export function resizeNotes<L extends NotesLayout>(
  layout: L, changes: readonly { id: string; x: number; y: number; width: number; height: number }[],
): L {
  const to = new Map(changes.map((c) => [c.id, c]));
  return {
    ...layout,
    notes: layout.notes.map((n) => {
      const c = to.get(NOTE_NODE_PREFIX + n.key);
      return c ? { ...n, x: c.x, y: c.y, width: c.width, height: c.height, sizeMode: "manual" } : n;
    }),
  };
}

/** @param layout A layout. @param leaderKey A leader's key. @returns The leader and the note it belongs to, or undefined. */
export function findLeader(layout: NotesLayout, leaderKey: string): { note: EditorNote; leader: EditorLeader } | undefined {
  for (const note of layout.notes) {
    const leader = note.leaders.find((l) => l.key === leaderKey);
    if (leader) return { note, leader };
  }
  return undefined;
}

/** Adds a leader to a note (a note keeps at most `MAX_NOTE_LEADERS`; a further one is left out). */
export function addLeader<L extends NotesLayout>(layout: L, noteKey: string, leader: EditorLeader): L {
  return {
    ...layout,
    notes: layout.notes.map((n) => (n.key === noteKey && n.leaders.length < MAX_NOTE_LEADERS ? { ...n, leaders: [...n.leaders, leader] } : n)),
  };
}

/** Changes one leader (found by key, whichever note holds it). */
export function patchLeader<L extends NotesLayout>(layout: L, leaderKey: string, patch: Partial<EditorLeader>): L {
  return {
    ...layout,
    notes: layout.notes.map((n) => (n.leaders.some((l) => l.key === leaderKey)
      ? { ...n, leaders: n.leaders.map((l) => (l.key === leaderKey ? { ...l, ...patch } : l)) }
      : n)),
  };
}

/** Points a leader at another target; its start, vertices, curve and ends are kept. */
export function setLeaderTarget<L extends NotesLayout>(layout: L, leaderKey: string, target: NoteLeaderTarget): L {
  return patchLeader(layout, leaderKey, leaderTargetFields(target));
}

/** Removes one leader; its note stays. */
export function removeLeader<L extends NotesLayout>(layout: L, leaderKey: string): L {
  return { ...layout, notes: layout.notes.map((n) => (n.leaders.some((l) => l.key === leaderKey) ? { ...n, leaders: n.leaders.filter((l) => l.key !== leaderKey) } : n)) };
}

/** A fresh key for a leader added in the editor. */
export function newLeaderKey(layout: NotesLayout): string {
  const used = new Set(layout.notes.flatMap((n) => n.leaders.map((l) => l.key)));
  let n = used.size + 1;
  while (used.has(`new-leader-${n}`)) n += 1;
  return `new-leader-${n}`;
}

/** Removes a note with its leaders. */
export function removeNote<L extends NotesLayout>(layout: L, key: string): L {
  return { ...layout, notes: layout.notes.filter((n) => n.key !== key) };
}

/** A fresh key for a note added in the editor. */
export function newNoteKey(layout: NotesLayout): string {
  const used = new Set(layout.notes.map((n) => n.key));
  let n = layout.notes.length + 1;
  while (used.has(`new-${n}`)) n += 1;
  return `new-${n}`;
}

/**
 * Drops the leaders whose state or transition is no longer in the diagram (the server removes them with their target), so a
 * reload after a delete never keeps a leader that would be refused on the next save.
 *
 * @param layout A layout.
 * @param stateIds The states the diagram still has.
 * @param transitionIds The transitions the diagram still has.
 */
export function dropLeadersWithout<L extends NotesLayout>(layout: L, stateIds: ReadonlySet<string>, transitionIds: ReadonlySet<string>): L {
  return {
    ...layout,
    notes: layout.notes.map((n) => ({
      ...n,
      leaders: n.leaders.filter((l) => !(
        (l.kind === "state" && l.state_id !== null && !stateIds.has(l.state_id))
        || (l.kind === "transition" && l.transition_id !== null && !transitionIds.has(l.transition_id))
      )),
    })),
  };
}

// --- Canvas mapping ---

/** A note's title and text shortened for a list. */
export function noteSummary(note: Pick<EditorNote, "title" | "text">): string {
  const flat = [note.title, note.text].map((part) => part.replace(/\s+/g, " ").trim()).filter(Boolean).join(" — ");
  if (!flat) return "Empty note";
  return flat.length > 60 ? `${flat.slice(0, 59)}…` : flat;
}

/** @param id A canvas node id. @returns The key of the note it names, or null when it is not a note. */
export function noteKeyOf(id: string): string | null {
  return id.startsWith(NOTE_NODE_PREFIX) ? id.slice(NOTE_NODE_PREFIX.length) : null;
}

/** @param note A note. @returns Whether it has neither a title nor text (the canvas then shows its placeholder and a faint outline). */
export function noteIsEmpty(note: Pick<EditorNote, "title" | "text">): boolean {
  return note.title.trim() === "" && note.text.trim() === "";
}

/** @param note A note. @param emptyNote The stand-in text for a note with nothing. @returns The label the canvas draws: the text as typed (its line breaks kept), nothing when only the title is set, else the stand-in. */
function noteLabel(note: Pick<EditorNote, "title" | "text">, emptyNote: string): string {
  if (note.text.trim()) return note.text.replace(/^\n+|\s+$/g, "");
  return note.title.trim() ? "" : emptyNote;
}

/**
 * @param notes The notes of the layout.
 * @param emptyNote Text shown on a note with no text yet.
 * @param noteCaption The caption of a note.
 * @returns The canvas nodes for the notes. A note with no tone is its text alone: no caption and no dashed edge (the canvas draws a
 * faint outline while it is hovered, selected or empty, so it can still be found and edited).
 */
export function canvasNoteNodes(notes: readonly EditorNote[], emptyNote: string, noteCaption: string): GraphCanvasNode[] {
  return notes.map<GraphCanvasNode>((n) => ({
    id: NOTE_NODE_PREFIX + n.key, label: noteLabel(n, emptyNote), title: n.title.trim() || undefined,
    caption: n.tone === "none" ? undefined : noteCaption, textAlign: n.textAlign,
    x: n.x, y: n.y, ...noteFrame(n), dashed: n.tone !== "none", tone: n.tone, placeholder: noteIsEmpty(n),
    inset: NOTE_PADDING,
  }));
}

/**
 * The canvas leader lines of the notes.
 *
 * @param notes The notes of the layout.
 * @param resolve What a target is on the canvas (a node, a line or a free point), or null when it is not drawn (the leader is then left out).
 */
export function noteLeaderLines(
  notes: readonly EditorNote[], resolve: (target: NoteLeaderTarget) => GraphCanvasLeader["to"] | null,
): GraphCanvasLeader[] {
  return notes.flatMap((n) => n.leaders.flatMap((l): GraphCanvasLeader[] => {
    const target = leaderOf(l);
    const to = target ? resolve(target) : null;
    if (!to) return [];
    return [{
      id: l.key, from: NOTE_NODE_PREFIX + n.key, fromPoint: l.start_point ?? undefined, points: l.points, smooth: l.smooth,
      startEnd: l.start_style, endEnd: l.end_style, to,
    }];
  }));
}

/**
 * Where a vertex added from the Selection card goes: off the straight line between the note's centre and what the leader ends
 * at.
 *
 * @param note The note the leader belongs to.
 * @param leader The leader.
 * @param centreOf The centre of what a target is on the canvas, or null when it has no position here (a line's has none, so the guess runs to the right of the note).
 */
export function leaderVertexSuggestion(
  note: EditorNote, leader: EditorLeader, centreOf: (target: NoteLeaderTarget) => { x: number; y: number } | null,
): LineWaypoint {
  const frame = noteFrame(note);
  const start = { x: note.x + frame.width / 2, y: note.y + frame.height / 2 };
  const target = leaderOf(leader);
  const end = (target ? centreOf(target) : null) ?? { x: start.x + 160, y: start.y };
  return suggestWaypoint(start, leader.points, end);
}
