/**
 * Module: modules/architecture/diagramEditorModel
 *
 * The diagram editor's state as plain functions, with no React: the layout being edited (boxes, notes, line anchors and boundary boxes), an
 * undo/redo history over it, the merge of a freshly read view into that layout, and the mapping to the shared
 * canvas's nodes and lines.
 *
 * Responsibilities:
 * - `EditorLayout`: every placement of the diagram (including boxes a view switch hides and boxes the viewer cannot read,
 *   which a save must keep), its notes, the boundary boxes (one per outer connection) and the attach points a person chose
 *   for lines. Edits return a new layout; none mutates.
 * - `History`: past / present / future with a saved baseline, so the editor knows what is unsaved and Save is enabled
 *   only for a real change.
 * - `mergeView`: display data comes from the server's view, membership and geometry from the local layout, so a reload
 *   never discards unsaved work.
 *
 * Design decisions:
 * - Which boxes a view switch hides and which lines are drawn are not stored in the layout: `diagramLines` works them out
 *   from the layout and the model data, so a box added in the editor has its lines at once. This file only draws the
 *   lines it is given.
 */
import type { GraphCanvasEdge, GraphCanvasLeader, GraphCanvasNode } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import type { GraphNodeOutline } from "../../components/GraphCanvas";
import type {
  ArchitectureConnection, ArchitectureElement, BoundaryShape, BoundaryValues, DiagramAnchor, DiagramNote, DiagramView,
  DiagramViewBoundary, DiagramViewEdge, DiagramViewNode, ElementType, NoteLeader, NoteTone, NoteValues, PlacementValues,
} from "./types";
import { isOutOfUse } from "./types";
import {
  commitStep, isDirtyBy, redoStep, refreshPresentOf, startHistoryOf, undoStep, type History as HistoryOf,
} from "../../utils/editHistory";

export type EditorTheme = "light" | "dark";

/** Default size of a new box. */
export const BOX_WIDTH = 160;
export const BOX_HEIGHT = 80;
/** Default size of a new note. */
export const NOTE_WIDTH = 160;
export const NOTE_HEIGHT = 60;
/** Gap left between boxes when new ones are placed in a grid. */
const GRID_GAP = 40;
/** Prefix of a note's canvas node id, so a node is told from an element by its id alone. */
export const NOTE_NODE_PREFIX = "note:";
/** Prefix of a boundary box's canvas node id (the rest is its outer connection's id). */
export const BOUNDARY_NODE_PREFIX = "boundary:";
/** Default size of a new boundary box. */
export const BOUNDARY_WIDTH = 140;
export const BOUNDARY_HEIGHT = 56;

/** One placed element: what is drawn on it and where it sits. */
export interface EditorBox {
  elementId: string;
  unique_code: string;
  name: string;
  /** The line drawn inside the box (empty for none and for a box the viewer cannot read). */
  display_note: string;
  locked: boolean;
  shared: boolean;
  status: DiagramViewNode["status"];
  parent_id: string | null;
  element_type_id: string | null;
  element_type_name: string;
  color_light: string | null;
  color_dark: string | null;
  symbol_id: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
}

/** An annotation: plain text in a toned block with an optional leader line; `id` is null until it is saved, `key` is stable while editing. */
export interface EditorNote extends NoteLeader {
  key: string;
  id: string | null;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: NoteTone;
}

/** What a note's leader points at, as one value. */
export type NoteLeaderTarget =
  | { kind: "none" }
  | { kind: "element"; elementId: string }
  | { kind: "connection"; connectionId: string }
  | { kind: "point"; x: number; y: number };

/** @param note A note. @returns What its leader points at (none when the target fields do not match its kind). */
export function leaderOf(note: NoteLeader): NoteLeaderTarget {
  if (note.leader_kind === "element" && note.leader_element_id) return { kind: "element", elementId: note.leader_element_id };
  if (note.leader_kind === "connection" && note.leader_connection_id) return { kind: "connection", connectionId: note.leader_connection_id };
  if (note.leader_kind === "point" && note.leader_x !== null && note.leader_y !== null) return { kind: "point", x: note.leader_x, y: note.leader_y };
  return { kind: "none" };
}

/** The "Points at" option value of a free position. */
export const LEADER_SPOT_OPTION = "spot";

/** @param target What a leader points at. @returns The "Points at" list's option value for it (empty for none). */
export function leaderOptionValue(target: NoteLeaderTarget): string {
  if (target.kind === "element") return `element:${target.elementId}`;
  if (target.kind === "connection") return `connection:${target.connectionId}`;
  return target.kind === "point" ? LEADER_SPOT_OPTION : "";
}

/** @param target What a leader points at. @param arrow Whether it ends in an arrowhead. @returns The note fields that hold it. */
export function leaderFields(target: NoteLeaderTarget, arrow: boolean): NoteLeader {
  return {
    leader_kind: target.kind,
    leader_element_id: target.kind === "element" ? target.elementId : null,
    leader_connection_id: target.kind === "connection" ? target.connectionId : null,
    leader_x: target.kind === "point" ? target.x : null,
    leader_y: target.kind === "point" ? target.y : null,
    leader_arrow: arrow,
  };
}

/**
 * A boundary box: the stand-in, inside a scoped diagram, for one outer connection (the scope, or an element inside it, to an
 * element outside). It carries the display data of the connection and of the element outside; whether it is covered is
 * worked out from the model's realisations, so it is not stored here.
 */
export interface EditorBoundary {
  connectionId: string;
  connection_code: string;
  connection_name: string;
  type_name: string;
  shape: BoundaryShape;
  locked: boolean;
  outside_element_id: string;
  outside_element_code: string;
  outside_element_name: string;
  scope_end_element_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EditorLayout {
  boxes: EditorBox[];
  notes: EditorNote[];
  /** Where lines meet their boxes where a person chose it; a line with none uses the nearest points. */
  anchors: DiagramAnchor[];
  /** The outer connections drawn as boundary boxes (a scoped diagram only). */
  boundaries: EditorBoundary[];
}

export const EMPTY_LAYOUT: EditorLayout = { boxes: [], notes: [], anchors: [], boundaries: [] };

/** @param connectionId An outer connection. @returns The canvas node id of its boundary box. */
export const boundaryNodeId = (connectionId: string): string => BOUNDARY_NODE_PREFIX + connectionId;

/** @param box A boundary box of a resolved view. @returns Its editor form. */
export function boundaryFromView(box: DiagramViewBoundary): EditorBoundary {
  return {
    connectionId: box.connection_id, connection_code: box.connection_code, connection_name: box.connection_name,
    type_name: box.type_name, shape: box.shape, locked: box.locked, outside_element_id: box.outside_element_id,
    outside_element_code: box.outside_element_code, outside_element_name: box.outside_element_name,
    scope_end_element_id: box.scope_end_element_id, x: box.x, y: box.y, width: box.width, height: box.height,
  };
}

/**
 * The boundary box for an outer connection added from the Add menu.
 *
 * @param connection The outer connection (one end inside the diagram's scope, the other outside).
 * @param scopeEndId The connection's end inside the scope.
 * @param at Where the box's top-left corner goes.
 */
export function boundaryFromConnection(
  connection: ArchitectureConnection, scopeEndId: string, at: { x: number; y: number },
): EditorBoundary {
  const scopeIsSource = scopeEndId === connection.source_element_id;
  const locked = scopeIsSource ? connection.target_locked : connection.source_locked;
  return {
    connectionId: connection.id, connection_code: connection.unique_code, connection_name: locked ? "" : connection.name,
    type_name: locked ? "" : connection.connection_type_name,
    shape: locked ? "dot" : !connection.directional ? "bidirectional" : scopeIsSource ? "output" : "input", locked,
    outside_element_id: scopeIsSource ? connection.target_element_id : connection.source_element_id,
    outside_element_code: scopeIsSource ? connection.target_element_code : connection.source_element_code,
    outside_element_name: scopeIsSource ? connection.target_element_name : connection.source_element_name,
    scope_end_element_id: scopeEndId, x: at.x, y: at.y, width: BOUNDARY_WIDTH, height: BOUNDARY_HEIGHT,
  };
}

/** @param node A placed element of a resolved view. @returns Its box. */
export function boxFromNode(node: DiagramViewNode): EditorBox {
  return {
    elementId: node.element_id, unique_code: node.unique_code, name: node.name, display_note: node.display_note,
    locked: node.locked, shared: node.shared,
    status: node.status, parent_id: node.parent_id, element_type_id: node.element_type_id,
    element_type_name: node.element_type_name, color_light: node.color_light, color_dark: node.color_dark,
    symbol_id: node.symbol_id, x: node.x, y: node.y, width: node.width, height: node.height, collapsed: node.collapsed,
  };
}

/** @param note A note of a resolved view. @returns Its editor form (its key is its id). */
export function noteFromView(note: DiagramNote): EditorNote {
  return {
    key: note.id, id: note.id, text: note.text, x: note.x, y: note.y, width: note.width, height: note.height, tone: note.tone,
    leader_kind: note.leader_kind, leader_element_id: note.leader_element_id, leader_connection_id: note.leader_connection_id,
    leader_x: note.leader_x, leader_y: note.leader_y, leader_arrow: note.leader_arrow,
  };
}

/** @param view A resolved view. @returns The layout it holds (every placement and note, hidden or not). */
export function layoutFromView(view: DiagramView): EditorLayout {
  return {
    boxes: view.nodes.map(boxFromNode), notes: view.notes.map(noteFromView), anchors: view.anchors,
    boundaries: view.boundaries.map(boundaryFromView),
  };
}

/**
 * Applies a freshly read view to the layout being edited: membership and geometry stay local, while the display data
 * (names, types, colours) comes from the view.
 *
 * @param local The layout being edited.
 * @param view The view read from the server (for example after a connection was added).
 * @returns The layout to show.
 */
export function mergeView(local: EditorLayout, view: DiagramView): EditorLayout {
  const resolved = new Map(view.nodes.map((n) => [n.element_id, n]));
  const drawn = new Map(view.boundaries.map((b) => [b.connection_id, b]));
  return {
    boxes: local.boxes.map((b) => {
      const n = resolved.get(b.elementId);
      if (!n) return b;
      return { ...boxFromNode(n), x: b.x, y: b.y, width: b.width, height: b.height, collapsed: b.collapsed };
    }),
    notes: local.notes,
    anchors: local.anchors,
    boundaries: local.boundaries.map((b) => {
      const v = drawn.get(b.connectionId);
      return v ? { ...boundaryFromView(v), x: b.x, y: b.y, width: b.width, height: b.height } : b;
    }),
  };
}

/**
 * The box for an element placed from the palette or a picker.
 *
 * @param element The element (this project's or one shared with it).
 * @param type The element's type, for its colours.
 * @param at Where its top-left corner goes.
 */
export function boxFromElement(element: ArchitectureElement, type: ElementType | undefined, at: { x: number; y: number }): EditorBox {
  return {
    elementId: element.id, unique_code: element.unique_code, name: element.name, display_note: element.display_note,
    locked: false, shared: element.shared,
    status: element.status, parent_id: element.parent_id, element_type_id: element.element_type_id,
    element_type_name: element.element_type_name, color_light: type?.color_light ?? null, color_dark: type?.color_dark ?? null,
    symbol_id: element.effective_symbol_id, x: at.x, y: at.y, width: BOX_WIDTH, height: BOX_HEIGHT, collapsed: false,
  };
}

/** @param layout The layout to save. @returns The request bodies of the layout save. */
export function layoutToSave(
  layout: EditorLayout,
): { placements: PlacementValues[]; notes: NoteValues[]; anchors: DiagramAnchor[]; boundaries: BoundaryValues[] } {
  return {
    placements: layout.boxes.map((b) => ({
      element_id: b.elementId, x: b.x, y: b.y, width: b.width, height: b.height, collapsed: b.collapsed,
    })),
    notes: layout.notes.map((n) => ({
      id: n.id, text: n.text, x: n.x, y: n.y, width: n.width, height: n.height, tone: n.tone, ...leaderFields(leaderOf(n), n.leader_arrow),
    })),
    anchors: layout.anchors,
    boundaries: layout.boundaries.map((b) => ({ connection_id: b.connectionId, x: b.x, y: b.y, width: b.width, height: b.height })),
  };
}

/** The part of a layout a save would send, as comparable text. */
function signature(layout: EditorLayout): string {
  const { placements, notes, anchors, boundaries } = layoutToSave(layout);
  return JSON.stringify([
    [...placements].sort((a, b) => a.element_id.localeCompare(b.element_id)),
    notes.map((n) => [n.text, n.x, n.y, n.width, n.height, n.tone, n.leader_kind, n.leader_element_id, n.leader_connection_id, n.leader_x, n.leader_y, n.leader_arrow]),
    anchors.map((a) => [a.source_element_id, a.target_element_id, a.source_point, a.target_point]).sort(),
    [...boundaries].sort((a, b) => a.connection_id.localeCompare(b.connection_id)),
  ]);
}

// --- Edits (each returns a new layout) ---

/** Moves boxes and notes; `id`s are element ids or `note:`-prefixed note keys. */
export function moveItems(layout: EditorLayout, moves: { id: string; x: number; y: number }[]): EditorLayout {
  const to = new Map(moves.map((m) => [m.id, m]));
  return {
    ...layout,
    boxes: layout.boxes.map((b) => (to.has(b.elementId) ? { ...b, x: to.get(b.elementId)!.x, y: to.get(b.elementId)!.y } : b)),
    notes: layout.notes.map((n) => {
      const m = to.get(NOTE_NODE_PREFIX + n.key);
      return m ? { ...n, x: m.x, y: m.y } : n;
    }),
    boundaries: layout.boundaries.map((b) => {
      const m = to.get(boundaryNodeId(b.connectionId));
      return m ? { ...b, x: m.x, y: m.y } : b;
    }),
  };
}

/** Moves and resizes boxes and notes to the final geometry of a resize. */
export function resizeItems(
  layout: EditorLayout, changes: { id: string; x: number; y: number; width: number; height: number }[],
): EditorLayout {
  const to = new Map(changes.map((c) => [c.id, c]));
  return {
    ...layout,
    boxes: layout.boxes.map((b) => {
      const c = to.get(b.elementId);
      return c ? { ...b, x: c.x, y: c.y, width: c.width, height: c.height } : b;
    }),
    notes: layout.notes.map((n) => {
      const c = to.get(NOTE_NODE_PREFIX + n.key);
      return c ? { ...n, x: c.x, y: c.y, width: c.width, height: c.height } : n;
    }),
    boundaries: layout.boundaries.map((b) => {
      const c = to.get(boundaryNodeId(b.connectionId));
      return c ? { ...b, x: c.x, y: c.y, width: c.width, height: c.height } : b;
    }),
  };
}

/** Adds boxes, skipping any element already on the diagram. */
export function addBoxes(layout: EditorLayout, boxes: EditorBox[]): EditorLayout {
  const have = new Set(layout.boxes.map((b) => b.elementId));
  const fresh = boxes.filter((b) => !have.has(b.elementId));
  return fresh.length === 0 ? layout : { ...layout, boxes: [...layout.boxes, ...fresh] };
}

/** Takes an element off the diagram, with the line anchors that named it. The element itself is never touched. */
export function removeBox(layout: EditorLayout, elementId: string): EditorLayout {
  return {
    ...layout,
    boxes: layout.boxes.filter((b) => b.elementId !== elementId),
    anchors: layout.anchors.filter((a) => a.source_element_id !== elementId && a.target_element_id !== elementId),
  };
}

/** The points a person chose for the line from `sourceId` to `targetId`, oriented to that direction; null ends are automatic. */
export function anchorOf(
  anchors: readonly DiagramAnchor[], sourceId: string, targetId: string,
): { sourcePoint: AttachPoint | null; targetPoint: AttachPoint | null } {
  for (const a of anchors) {
    if (a.source_element_id === sourceId && a.target_element_id === targetId) {
      return { sourcePoint: a.source_point, targetPoint: a.target_point };
    }
    if (a.source_element_id === targetId && a.target_element_id === sourceId) {
      return { sourcePoint: a.target_point, targetPoint: a.source_point };
    }
  }
  return { sourcePoint: null, targetPoint: null };
}

/**
 * Chooses attach points for the line from `sourceId` to `targetId`. An end the change does not name keeps what it had; a
 * `null` end is made automatic. A line left with both ends automatic has no anchor at all.
 *
 * @param layout The layout being edited.
 * @param sourceId The line's source element.
 * @param targetId The line's target element.
 * @param change The ends to set (`undefined` leaves an end as it is).
 */
export function setLineAnchor(
  layout: EditorLayout, sourceId: string, targetId: string,
  change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null },
): EditorLayout {
  const before = anchorOf(layout.anchors, sourceId, targetId);
  const sourcePoint = change.sourcePoint === undefined ? before.sourcePoint : change.sourcePoint;
  const targetPoint = change.targetPoint === undefined ? before.targetPoint : change.targetPoint;
  const others = layout.anchors.filter((a) => !(
    (a.source_element_id === sourceId && a.target_element_id === targetId) ||
    (a.source_element_id === targetId && a.target_element_id === sourceId)
  ));
  const next = sourcePoint === null && targetPoint === null
    ? others
    : [...others, { source_element_id: sourceId, target_element_id: targetId, source_point: sourcePoint, target_point: targetPoint }];
  return { ...layout, anchors: next };
}

/** Adds boundary boxes, skipping any outer connection already drawn. */
export function addBoundaries(layout: EditorLayout, boundaries: EditorBoundary[]): EditorLayout {
  const have = new Set(layout.boundaries.map((b) => b.connectionId));
  const fresh = boundaries.filter((b) => !have.has(b.connectionId));
  return fresh.length === 0 ? layout : { ...layout, boundaries: [...layout.boundaries, ...fresh] };
}

/** Takes a boundary box off the diagram; the connection it stands for is never touched. */
export function removeBoundary(layout: EditorLayout, connectionId: string): EditorLayout {
  return { ...layout, boundaries: layout.boundaries.filter((b) => b.connectionId !== connectionId) };
}

/** @param key A fresh note key. @param at Where its top-left corner goes. @returns A new, empty, neutral note with no leader. */
export function newNote(key: string, at: { x: number; y: number }): EditorNote {
  return {
    key, id: null, text: "", x: at.x, y: at.y, width: NOTE_WIDTH, height: NOTE_HEIGHT, tone: "neutral", ...leaderFields({ kind: "none" }, true),
  };
}

export function addNote(layout: EditorLayout, note: EditorNote): EditorLayout {
  return { ...layout, notes: [...layout.notes, note] };
}

/** Changes the text, tone or arrowhead of a note. */
export function updateNote(
  layout: EditorLayout, key: string, patch: Partial<Pick<EditorNote, "text" | "tone" | "leader_arrow">>,
): EditorLayout {
  return { ...layout, notes: layout.notes.map((n) => (n.key === key ? { ...n, ...patch } : n)) };
}

/** Points a note's leader at a target (`none` removes the leader); the arrowhead setting is kept. */
export function setNoteLeader(layout: EditorLayout, key: string, target: NoteLeaderTarget): EditorLayout {
  return { ...layout, notes: layout.notes.map((n) => (n.key === key ? { ...n, ...leaderFields(target, n.leader_arrow) } : n)) };
}

export function removeNote(layout: EditorLayout, key: string): EditorLayout {
  return { ...layout, notes: layout.notes.filter((n) => n.key !== key) };
}

/**
 * The first free slot of a grid, for a box added without a drop position.
 *
 * @param layout The layout the box joins.
 * @param index Which of several boxes added together this is (they are not in the layout yet).
 * @param columns Boxes per row of the grid.
 */
export function nextFreePosition(layout: EditorLayout, index = 0, columns = 4): { x: number; y: number } {
  const taken = [...layout.boxes, ...layout.notes, ...layout.boundaries];
  const hits = (x: number, y: number) =>
    taken.some((t) => x < t.x + t.width && t.x < x + BOX_WIDTH && y < t.y + t.height && t.y < y + BOX_HEIGHT);
  let free = -1;
  for (let slot = 0; slot < 100_000; slot += 1) {
    const x = (slot % columns) * (BOX_WIDTH + GRID_GAP);
    const y = Math.floor(slot / columns) * (BOX_HEIGHT + GRID_GAP);
    if (!hits(x, y)) free += 1;
    if (free === index) return { x, y };
  }
  return { x: 0, y: 0 };
}

// --- History ---

/** An undo/redo history over layouts; `saved` is the layout last stored on the server. */
export type History = HistoryOf<EditorLayout>;

/** @param layout The layout just loaded (it is also the saved baseline). */
export function startHistory(layout: EditorLayout): History {
  return startHistoryOf(layout);
}

/** Records `next` as the new present, clearing redo; an edit that changes nothing adds no step. */
export function commit(history: History, next: EditorLayout): History {
  return commitStep(history, next, signature);
}

export const undo = (history: History): History => undoStep(history);

export const redo = (history: History): History => redoStep(history);

/** Replaces the present without a history step (a merged view's display data is not an edit). */
export function refreshPresent(history: History, present: EditorLayout): History {
  return refreshPresentOf(history, present);
}

/** Marks the present as stored on the server (after a successful save). */
export function markSaved(history: History, saved: EditorLayout): History {
  return { ...history, present: saved, saved };
}

/** True when the present differs from what the server holds. */
export function isDirty(history: History): boolean {
  return isDirtyBy(history, signature);
}

// --- Canvas mapping ---

const pick = (light: string | null, dark: string | null, theme: EditorTheme): string | undefined =>
  (theme === "dark" ? dark ?? light : light ?? dark) ?? undefined;

/** What the canvas needs besides the layout. */
export interface CanvasContext {
  theme: EditorTheme;
  /** The sanitised SVG of a symbol, once fetched. */
  symbolSvg: (symbolId: string) => string | undefined;
  /** Text shown on a box the viewer cannot read. */
  lockedLabel: (code: string) => string;
  /** Text shown on a note with no text yet. */
  emptyNote: string;
  /** The caption of a note. */
  noteCaption: string;
  /** Whether a box draws its display note (a viewer's switch; the notes are always kept). */
  showNotes: boolean;
  /** The elements a view switch hides: they stay in the layout but are not drawn. */
  hidden: ReadonlySet<string>;
  /** The outer connections at least one connection realises (a boundary box shows "Covered" for each). */
  covered: ReadonlySet<string>;
  /** The word for a boundary box that is realised and for one that is not (neutral, never a warning). */
  coverageLabel: (covered: boolean) => string;
}

/** The outline a boundary box is drawn with, from the direction of its connection. */
const BOUNDARY_OUTLINE: Record<BoundaryShape, GraphNodeOutline> = {
  input: "pointed-right", output: "pointed-left", bidirectional: "pointed-both", dot: "ellipse",
};

/** @returns The canvas nodes for the boxes a view switch leaves visible, and for the notes. */
export function canvasNodes(layout: EditorLayout, ctx: CanvasContext): GraphCanvasNode[] {
  const boxes = layout.boxes.filter((b) => !ctx.hidden.has(b.elementId)).map<GraphCanvasNode>((b) => ({
    id: b.elementId,
    label: b.locked ? ctx.lockedLabel(b.unique_code) : b.name,
    caption: b.locked ? undefined : `${b.unique_code} · ${b.element_type_name}`,
    body: ctx.showNotes && !b.locked && b.display_note ? b.display_note : undefined,
    x: b.x, y: b.y, width: b.width, height: b.height,
    symbolSvg: b.symbol_id && !b.locked ? ctx.symbolSvg(b.symbol_id) : undefined,
    accent: pick(b.color_light, b.color_dark, ctx.theme),
    dashed: b.locked || isOutOfUse(b.status),
  }));
  const notes = layout.notes.map<GraphCanvasNode>((n) => ({
    id: NOTE_NODE_PREFIX + n.key, label: n.text.trim() || ctx.emptyNote, caption: ctx.noteCaption,
    x: n.x, y: n.y, width: n.width, height: n.height, dashed: true, tone: n.tone,
  }));
  const boundaries = layout.boundaries.map<GraphCanvasNode>((b) => ({
    id: boundaryNodeId(b.connectionId), label: b.connection_code,
    caption: `${boundaryOutsideName(b)} · ${ctx.coverageLabel(ctx.covered.has(b.connectionId))}`,
    x: b.x, y: b.y, width: b.width, height: b.height, outline: BOUNDARY_OUTLINE[b.shape], dashed: b.locked,
  }));
  return [...boxes, ...notes, ...boundaries];
}

/** What each boundary shape means, for lists and captions (the outline itself carries the same in its form). */
export const BOUNDARY_SHAPE_LABEL: Record<BoundaryShape, string> = {
  input: "Input", output: "Output", bidirectional: "Two-way", dot: "Direction not shown",
};

/** @param box A boundary box. @returns The element outside, for a list: code and name, or the code alone when unreadable. */
export function boundaryOutsideName(box: Pick<EditorBoundary, "outside_element_code" | "outside_element_name" | "locked">): string {
  return box.locked ? box.outside_element_code : `${box.outside_element_code} ${box.outside_element_name}`.trim();
}

/** The label of a line: the text the view gives (which already counts several connections), else just the count when several. */
function edgeLabel(edge: DiagramViewEdge): string | undefined {
  return edge.label ?? (edge.count > 1 ? `×${edge.count}` : undefined);
}

/**
 * @param edges The resolved lines.
 * @param layout The layout being edited (its anchors give each line's chosen points); a line whose end is not a visible box (removed or switched off here) is left out.
 * @param hidden The elements a view switch hides.
 * @param theme Which of a line's two colours to use.
 */
export function canvasEdges(edges: DiagramViewEdge[], layout: EditorLayout, hidden: ReadonlySet<string>, theme: EditorTheme): GraphCanvasEdge[] {
  const visible = new Set([
    ...layout.boxes.filter((b) => !hidden.has(b.elementId)).map((b) => b.elementId),
    ...layout.boundaries.map((b) => boundaryNodeId(b.connectionId)),
  ]);
  return edges
    .filter((e) => visible.has(e.source_element_id) && visible.has(e.target_element_id))
    .map((e) => ({
      id: e.id, source: e.source_element_id, target: e.target_element_id, label: edgeLabel(e),
      dashed: e.indirect || (e.line_style !== null && e.line_style !== "solid"),
      color: pick(e.color_light, e.color_dark, theme),
      direction: e.two_way ? "none" : "forward",
      ...anchorOf(layout.anchors, e.source_element_id, e.target_element_id),
    }));
}

/**
 * The canvas leaders of the notes. A leader to a box is passed as is (the canvas draws it only while that box is drawn); a
 * leader to a connection goes to the drawn line that stands for it (a merged or rolled-up line stands for several), and is
 * left out when no drawn line does.
 *
 * @param layout The layout being edited.
 * @param edges The resolved lines.
 * @param drawn The ids of the lines the canvas draws (`canvasEdges`).
 */
export function canvasLeaders(layout: EditorLayout, edges: DiagramViewEdge[], drawn: ReadonlySet<string>): GraphCanvasLeader[] {
  const out: GraphCanvasLeader[] = [];
  for (const n of layout.notes) {
    const target = leaderOf(n);
    const from = NOTE_NODE_PREFIX + n.key;
    if (target.kind === "element") out.push({ id: n.key, from, to: { kind: "node", id: target.elementId }, arrow: n.leader_arrow });
    else if (target.kind === "point") out.push({ id: n.key, from, to: { kind: "point", x: target.x, y: target.y }, arrow: n.leader_arrow });
    else if (target.kind === "connection") {
      const line = edges.find((e) => drawn.has(e.id) && e.connections.some((c) => c.id === target.connectionId));
      if (line) out.push({ id: n.key, from, to: { kind: "edge", id: line.id }, arrow: n.leader_arrow });
    }
  }
  return out;
}

/**
 * Whether a note's leader is drawn: a box leader needs the box on the diagram and not switched off, a connection leader a
 * drawn line that stands for it; a free point and no leader are always "drawn".
 *
 * @param note The note.
 * @param visibleBoxIds The elements drawn as boxes.
 * @param edges The resolved lines.
 * @param drawn The ids of the lines the canvas draws.
 */
export function leaderIsDrawn(note: NoteLeader, visibleBoxIds: ReadonlySet<string>, edges: DiagramViewEdge[], drawn: ReadonlySet<string>): boolean {
  const target = leaderOf(note);
  if (target.kind === "element") return visibleBoxIds.has(target.elementId);
  if (target.kind === "connection") return edges.some((e) => drawn.has(e.id) && e.connections.some((c) => c.id === target.connectionId));
  return true;
}

/**
 * What a note's leader points at, in words, for lists and the Outline.
 *
 * @param note The note.
 * @param boxes Every box of the layout.
 * @param edges The resolved lines (their connections name a connection target).
 * @param drawn Whether the leader is drawn (`leaderIsDrawn`); a leader that is not drawn says so.
 * @returns "Points at ELM-001 Gateway", "Points at CON-001 Link", "Points at a spot", each with " (not drawn)" when hidden; null with no leader.
 */
export function leaderSummary(note: NoteLeader, boxes: readonly EditorBox[], edges: readonly DiagramViewEdge[], drawn: boolean): string | null {
  const target = leaderOf(note);
  let what: string;
  if (target.kind === "element") {
    const box = boxes.find((b) => b.elementId === target.elementId);
    what = box ? (box.locked ? box.unique_code : `${box.unique_code} ${box.name}`) : "an element not on this diagram";
  } else if (target.kind === "connection") {
    const connection = edges.flatMap((e) => e.connections).find((c) => c.id === target.connectionId);
    what = connection ? `${connection.unique_code}${connection.name ? ` ${connection.name}` : ""}` : "a connection not drawn here";
  } else if (target.kind === "point") what = "a spot";
  else return null;
  return `Points at ${what}${drawn ? "" : " (not drawn)"}`;
}

/** A fresh key for a note added in the editor. */
export function newNoteKey(layout: EditorLayout): string {
  const used = new Set(layout.notes.map((n) => n.key));
  let n = layout.notes.length + 1;
  while (used.has(`new-${n}`)) n += 1;
  return `new-${n}`;
}
