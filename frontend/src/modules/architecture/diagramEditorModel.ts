/**
 * Module: modules/architecture/diagramEditorModel
 *
 * The diagram editor's state as plain functions, with no React.
 * - `EditorLayout`: every placement of the diagram (including boxes a view switch hides and boxes the viewer cannot read,
 *   which a save must keep), its notes, the boundary boxes (one per outer connection) and the chosen line attach points.
 *   Edits return a new layout; none mutates.
 * - `History`: past / present / future with a saved baseline, so Save is enabled only for a real change.
 * - `mergeView`: display data comes from the server's view, membership and geometry from the local layout, so a reload
 *   never discards unsaved work. The mapping to the shared canvas's nodes and lines is here too.
 * Which boxes a view switch hides and which lines are drawn are not stored in the layout: `diagramLines` derives them from the
 * layout and the model data, so a box added in the editor has its lines at once; this file only draws the lines it is given.
 */
import type { GraphCanvasEdge, GraphCanvasLeader, GraphCanvasNode, GraphNodeBadge } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import { effectiveShape, reverseRoute, type LineShape } from "../../components/graphLinePath";
import { SYMBOL_HEIGHT, drawnBoxSize, fitBox } from "./elementBoxFit";
import type { GraphNodeOutline } from "../../components/GraphCanvas";
import {
  canvasNoteNodes, leaderOf, moveNotes, noteFrame, noteFromView, noteLeaderLines, noteToValues, notesSignature, resizeNotes, type EditorLeader,
  type EditorNote,
} from "./noteModel";
import type {
  ArchitectureConnection, ArchitectureElement, BoundaryShape, BoundaryValues, DiagramAnchor, DiagramView,
  DiagramViewBoundary, DiagramViewEdge, DiagramViewNode, ElementType, LineRouteChange, LineWaypoint, NoteValues, PlacementValues,
} from "./types";
import { isOutOfUse } from "./types";
import {
  commitStep, isDirtyBy, redoStep, refreshPresentOf, startHistoryOf, undoStep, type History as HistoryOf,
} from "../../utils/editHistory";

export type EditorTheme = "light" | "dark";

/** Default size of a new box. */
export const BOX_WIDTH = 160;
export const BOX_HEIGHT = 80;
/** Gap left between boxes when new ones are placed in a grid. */
const GRID_GAP = 40;
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

/**
 * The box with its element's current name, note, type and symbol, keeping the box's position, size and collapsed state (an
 * element edited in the Selection card is shown renamed without waiting for the layout to be saved).
 *
 * @param box The box on the diagram.
 * @param element The element as just stored.
 * @param type The element's type, for its colours.
 */
export function boxWithElement(box: EditorBox, element: ArchitectureElement, type: ElementType | undefined): EditorBox {
  return {
    ...boxFromElement(element, type, box), width: box.width, height: box.height, collapsed: box.collapsed, shared: box.shared,
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
    notes: layout.notes.map(noteToValues),
    anchors: layout.anchors,
    boundaries: layout.boundaries.map((b) => ({ connection_id: b.connectionId, x: b.x, y: b.y, width: b.width, height: b.height })),
  };
}

/** The part of a layout a save would send, as comparable text. */
function signature(layout: EditorLayout): string {
  const { placements, anchors, boundaries } = layoutToSave(layout);
  return JSON.stringify([
    [...placements].sort((a, b) => a.element_id.localeCompare(b.element_id)),
    notesSignature(layout.notes),
    anchors.map((a) => [a.source_element_id, a.target_element_id, a.connection_id, a.source_point, a.target_point, a.points.map((p) => [p.x, p.y]), a.line_shape]).sort(),
    [...boundaries].sort((a, b) => a.connection_id.localeCompare(b.connection_id)),
  ]);
}

// --- Edits (each returns a new layout) ---

/** Moves boxes and notes; `id`s are element ids or `note:`-prefixed note keys. */
export function moveItems(layout: EditorLayout, moves: { id: string; x: number; y: number }[]): EditorLayout {
  const to = new Map(moves.map((m) => [m.id, m]));
  return {
    ...moveNotes(layout, moves),
    boxes: layout.boxes.map((b) => (to.has(b.elementId) ? { ...b, x: to.get(b.elementId)!.x, y: to.get(b.elementId)!.y } : b)),
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
    ...resizeNotes(layout, changes),
    boxes: layout.boxes.map((b) => {
      const c = to.get(b.elementId);
      return c ? { ...b, x: c.x, y: c.y, width: c.width, height: c.height } : b;
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

/** How a line is routed, oriented from its source to its target: the chosen attach points (null is automatic) and the vertices. */
export interface LineRoute {
  sourcePoint: AttachPoint | null;
  targetPoint: AttachPoint | null;
  points: LineWaypoint[];
  /** The line's own shape, or null to follow the diagram's default. */
  lineShape: LineShape | null;
}

/** A route read from `anchor` oriented from `sourceId` to `targetId`, or `null` when the anchor joins other boxes. */
function orientedRoute(anchor: DiagramAnchor, sourceId: string, targetId: string): LineRoute | null {
  if (anchor.source_element_id === sourceId && anchor.target_element_id === targetId) {
    return { sourcePoint: anchor.source_point, targetPoint: anchor.target_point, points: anchor.points, lineShape: anchor.line_shape };
  }
  if (anchor.source_element_id === targetId && anchor.target_element_id === sourceId) {
    return { sourcePoint: anchor.target_point, targetPoint: anchor.source_point, points: reverseRoute(anchor.points), lineShape: anchor.line_shape };
  }
  return null;
}

const NO_ROUTE: LineRoute = { sourcePoint: null, targetPoint: null, points: [], lineShape: null };

/** The route a person chose for the pair of boxes `sourceId` and `targetId`, oriented to that direction (an anchor stored the other way round is read reversed). A connection's own route is not the pair's. */
export function anchorOf(anchors: readonly DiagramAnchor[], sourceId: string, targetId: string): LineRoute {
  for (const a of anchors) {
    if (a.connection_id) continue;
    const route = orientedRoute(a, sourceId, targetId);
    if (route) return route;
  }
  return NO_ROUTE;
}

/** The own route of a connection between `sourceId` and `targetId`, oriented to that direction, or `null` when it has none there. */
export function connectionRouteOf(anchors: readonly DiagramAnchor[], connectionId: string, sourceId: string, targetId: string): LineRoute | null {
  const anchor = anchors.find((a) => a.connection_id === connectionId);
  return anchor ? orientedRoute(anchor, sourceId, targetId) : null;
}

/**
 * How a drawn line is routed: the own route of the connection it is drawn for, else its pair's route.
 *
 * @param anchors The layout's anchors.
 * @param line The line (its ends and, for a connection drawn on its own route, that connection).
 */
export function routeOf(
  anchors: readonly DiagramAnchor[], line: Pick<DiagramViewEdge, "source_element_id" | "target_element_id" | "route_connection_id">,
): LineRoute {
  if (line.route_connection_id) {
    return connectionRouteOf(anchors, line.route_connection_id, line.source_element_id, line.target_element_id) ?? NO_ROUTE;
  }
  return anchorOf(anchors, line.source_element_id, line.target_element_id);
}

/** The connections routed on their own and the two boxes each route joins, for `resolveDiagram` (which draws each as a line apart). */
export function routedConnections(anchors: readonly DiagramAnchor[]): Map<string, readonly [string, string]> {
  return new Map(anchors.flatMap((a) => (a.connection_id ? [[a.connection_id, [a.source_element_id, a.target_element_id] as const] as const] : [])));
}

/** Whether another drawn line joins the same two boxes as `line` (in either direction), so the pair's route would move both. */
export function sharesItsPair(edges: readonly DiagramViewEdge[], line: Pick<DiagramViewEdge, "id" | "source_element_id" | "target_element_id">): boolean {
  return edges.some((e) => e.id !== line.id && (
    (e.source_element_id === line.source_element_id && e.target_element_id === line.target_element_id) ||
    (e.source_element_id === line.target_element_id && e.target_element_id === line.source_element_id)
  ));
}

/**
 * The connection an edit to a line's route belongs to: the connection the line is drawn for on its own route; else the one
 * chosen in a merged line's card when it can have a route of its own; else the only connection of a line that shares its two
 * boxes with another line (a pair's route would move both); else none (the edit is the pair's and moves every connection on
 * the line).
 *
 * @param line The line being edited.
 * @param chosenConnectionId The connection chosen in the line's card, or null.
 * @param sharesPair Whether another line joins the same two boxes (`sharesItsPair`).
 */
export function routedConnectionOf(
  line: Pick<DiagramViewEdge, "route_connection_id" | "routable_connection_ids" | "connections">, chosenConnectionId: string | null, sharesPair: boolean,
): string | null {
  if (line.route_connection_id) return line.route_connection_id;
  if (chosenConnectionId !== null && line.routable_connection_ids.includes(chosenConnectionId)) return chosenConnectionId;
  return sharesPair && line.connections.length === 1 && line.routable_connection_ids.length === 1 ? line.routable_connection_ids[0] : null;
}

/**
 * Routes the line from `sourceId` to `targetId`. A part the change does not name keeps what it had: an attach point (a `null`
 * end is made automatic), the vertices (an empty list leaves the line to its shape) and the line's own shape (null follows
 * the diagram's default). A line left with both ends automatic, no vertices and no shape has no anchor at all.
 *
 * @param layout The layout being edited.
 * @param sourceId The line's source element.
 * @param targetId The line's target element.
 * @param change The parts to set (`undefined` leaves a part as it is); `points` run from the source to the target.
 */
export function setLineAnchor(
  layout: EditorLayout, sourceId: string, targetId: string,
  change: LineRouteChange,
): EditorLayout {
  const before = anchorOf(layout.anchors, sourceId, targetId);
  const sourcePoint = change.sourcePoint === undefined ? before.sourcePoint : change.sourcePoint;
  const targetPoint = change.targetPoint === undefined ? before.targetPoint : change.targetPoint;
  const points = change.points === undefined ? before.points : change.points;
  const lineShape = change.lineShape === undefined ? before.lineShape : change.lineShape;
  const others = layout.anchors.filter((a) => a.connection_id || !(
    (a.source_element_id === sourceId && a.target_element_id === targetId) ||
    (a.source_element_id === targetId && a.target_element_id === sourceId)
  ));
  const next = sourcePoint === null && targetPoint === null && points.length === 0 && lineShape === null
    ? others
    : [...others, {
      source_element_id: sourceId, target_element_id: targetId, connection_id: null, source_point: sourcePoint, target_point: targetPoint,
      points, line_shape: lineShape,
    }];
  return { ...layout, anchors: next };
}

/**
 * Routes one connection on its own, which draws it as a line apart from the line its pair of boxes shares. A connection with
 * no route of its own starts from the route its line has now (so it does not jump), then takes the change; a part the change
 * does not name keeps what it had. Unlike a pair's route, one with both ends automatic and no vertices is kept (the
 * connection stays a line of its own); `clearConnectionRoute` joins it to its pair's line again.
 *
 * @param layout The layout being edited.
 * @param connectionId The connection.
 * @param sourceId The source element of the line being edited.
 * @param targetId The target element of the line being edited.
 * @param change The parts to set (`undefined` leaves a part as it is); `points` run from the source to the target.
 */
export function setConnectionRoute(
  layout: EditorLayout, connectionId: string, sourceId: string, targetId: string, change: LineRouteChange,
): EditorLayout {
  const before = connectionRouteOf(layout.anchors, connectionId, sourceId, targetId) ?? anchorOf(layout.anchors, sourceId, targetId);
  const points = change.points === undefined ? before.points : change.points;
  const lineShape = change.lineShape === undefined ? before.lineShape : change.lineShape;
  const row: DiagramAnchor = {
    source_element_id: sourceId, target_element_id: targetId, connection_id: connectionId,
    source_point: change.sourcePoint === undefined ? before.sourcePoint : change.sourcePoint,
    target_point: change.targetPoint === undefined ? before.targetPoint : change.targetPoint,
    points, line_shape: lineShape,
  };
  return { ...layout, anchors: [...layout.anchors.filter((a) => a.connection_id !== connectionId), row] };
}

/** Takes a connection's own route away, so it is drawn with its pair's line and route again. */
export function clearConnectionRoute(layout: EditorLayout, connectionId: string): EditorLayout {
  return { ...layout, anchors: layout.anchors.filter((a) => a.connection_id !== connectionId) };
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

/** The label a box the viewer cannot read is drawn with (the page passes the same text to `canvasNodes`). */
export function lockedBoxLabel(code: string): string {
  return `${code} (not visible)`;
}

/** The small line under a box's name: its code and its type. */
function boxCaption(box: Pick<EditorBox, "unique_code" | "element_type_name">): string {
  return `${box.unique_code} · ${box.element_type_name}`;
}

/**
 * The size a box is drawn at: the stored size, made larger where its symbol, code and name need it (`elementBoxFit`). The stored
 * size is never rewritten (a symbol changed on an element's type reaches boxes on diagrams nobody has open), so every reader of a
 * box's geometry (the canvas, the lines' attach points, the free slot, the exports) reads this.
 *
 * @param box The box.
 * @param lockedLabel The text a locked box draws, for a caller that draws its own.
 * @returns The width and height the box is drawn at.
 */
export function boxFrame(
  box: Pick<EditorBox, "unique_code" | "name" | "element_type_name" | "symbol_id" | "locked" | "width" | "height">,
  lockedLabel: (code: string) => string = lockedBoxLabel,
): { width: number; height: number } {
  if (box.locked) return drawnBoxSize(false, "", lockedLabel(box.unique_code), box.width, box.height);
  return drawnBoxSize(box.symbol_id !== null, boxCaption(box), box.name, box.width, box.height);
}

/** @returns The least size a resize may make a box (what its content needs at the width it is drawn at). */
function boxMinimum(box: Parameters<typeof boxFrame>[0], lockedLabel: (code: string) => string): { minWidth: number; minHeight: number } {
  const frame = boxFrame(box, lockedLabel);
  const fit = box.locked
    ? fitBox(false, "", lockedLabel(box.unique_code), frame.width)
    : fitBox(box.symbol_id !== null, boxCaption(box), box.name, frame.width);
  return { minWidth: fit.minWidth, minHeight: fit.minHeight };
}

/**
 * The first free slot of a grid, for a box added without a drop position.
 *
 * @param layout The layout the box joins.
 * @param index Which of several boxes added together this is (they are not in the layout yet).
 * @param columns Boxes per row of the grid.
 */
export function nextFreePosition(layout: EditorLayout, index = 0, columns = 4): { x: number; y: number } {
  const taken = [
    ...layout.boxes.map((b) => ({ x: b.x, y: b.y, ...boxFrame(b) })), ...layout.notes.map((n) => ({ x: n.x, y: n.y, ...noteFrame(n) })), ...layout.boundaries,
  ];
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
  /** The badges a box carries (a state machine diagram link); none for an element with nothing to open. */
  badges: (elementId: string) => GraphNodeBadge[];
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
    caption: b.locked ? undefined : boxCaption(b),
    body: ctx.showNotes && !b.locked && b.display_note ? b.display_note : undefined,
    x: b.x, y: b.y, ...boxFrame(b, ctx.lockedLabel), ...boxMinimum(b, ctx.lockedLabel),
    symbolSvg: b.symbol_id && !b.locked ? ctx.symbolSvg(b.symbol_id) : undefined,
    symbolHeight: b.symbol_id && !b.locked ? SYMBOL_HEIGHT : undefined,
    accent: pick(b.color_light, b.color_dark, ctx.theme),
    dashed: b.locked || isOutOfUse(b.status),
    badges: b.locked ? undefined : ctx.badges(b.elementId),
  }));
  const notes = canvasNoteNodes(layout.notes, ctx.emptyNote, ctx.noteCaption);
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
 * @param defaultShape The diagram's default line shape, for a line with none of its own.
 */
export function canvasEdges(
  edges: DiagramViewEdge[], layout: EditorLayout, hidden: ReadonlySet<string>, theme: EditorTheme, defaultShape: LineShape = "straight",
): GraphCanvasEdge[] {
  const visible = new Set([
    ...layout.boxes.filter((b) => !hidden.has(b.elementId)).map((b) => b.elementId),
    ...layout.boundaries.map((b) => boundaryNodeId(b.connectionId)),
  ]);
  return edges
    .filter((e) => visible.has(e.source_element_id) && visible.has(e.target_element_id))
    .map((e) => {
      const { lineShape, ...route } = routeOf(layout.anchors, e);
      return {
      id: e.id, source: e.source_element_id, target: e.target_element_id, label: edgeLabel(e),
      dashed: e.indirect || (e.line_style !== null && e.line_style !== "solid"),
      color: pick(e.color_light, e.color_dark, theme),
      direction: e.two_way ? "none" : "forward",
      // A line to a boundary box has no element pair of its own to keep a route on, so it stays automatic.
      routable: !e.source_is_boundary && !e.target_is_boundary,
      ...route, lineShape: effectiveShape(lineShape, defaultShape),
      };
    });
}

/**
 * The canvas leaders of the notes. A leader to a box is passed as is (the canvas draws it only while that box is drawn); a
 * leader to a connection goes to the drawn line that stands for it (a merged or rolled-up line stands for several), and is
 * left out when no drawn line does.
 *
 * @param layout The layout being edited.
 * @param edges The resolved lines.
 * @param drawn The ids of the lines the canvas draws (`canvasEdges`).
 * @param defaultShape The diagram's default line shape, for a leader with none of its own.
 */
export function canvasLeaders(
  layout: EditorLayout, edges: DiagramViewEdge[], drawn: ReadonlySet<string>, defaultShape: LineShape = "straight",
): GraphCanvasLeader[] {
  return noteLeaderLines(layout.notes, (target) => {
    if (target.kind === "element") return { kind: "node", id: target.elementId };
    if (target.kind === "point") return { kind: "point", x: target.x, y: target.y };
    if (target.kind !== "connection") return null; // a state machine diagram's targets are not a block diagram's
    const edge = edges.find((e) => drawn.has(e.id) && e.connections.some((c) => c.id === target.connectionId));
    return edge ? { kind: "edge", id: edge.id } : null;
  }, defaultShape);
}

/**
 * Whether a leader is drawn: a box leader needs the box on the diagram and not switched off, a connection leader a drawn line
 * that stands for it; a free point is always "drawn".
 *
 * @param leader The leader.
 * @param visibleBoxIds The elements drawn as boxes.
 * @param edges The resolved lines.
 * @param drawn The ids of the lines the canvas draws.
 */
export function leaderIsDrawn(leader: EditorLeader, visibleBoxIds: ReadonlySet<string>, edges: DiagramViewEdge[], drawn: ReadonlySet<string>): boolean {
  const target = leaderOf(leader);
  if (target?.kind === "element") return visibleBoxIds.has(target.elementId);
  if (target?.kind === "connection") return edges.some((e) => drawn.has(e.id) && e.connections.some((c) => c.id === target.connectionId));
  return true;
}

/**
 * What a leader ends at, in words, for lists and the Outline.
 *
 * @param leader The leader.
 * @param boxes Every box of the layout.
 * @param edges The resolved lines (their connections name a connection target).
 * @param drawn Whether the leader is drawn (`leaderIsDrawn`); a leader that is not drawn says so.
 * @returns "ELM-001 Gateway", "CON-001 Link" or "a spot", with " (not drawn)" when hidden.
 */
export function leaderSummary(leader: EditorLeader, boxes: readonly EditorBox[], edges: readonly DiagramViewEdge[], drawn: boolean): string {
  const target = leaderOf(leader);
  let what: string;
  if (target?.kind === "element") {
    const box = boxes.find((b) => b.elementId === target.elementId);
    what = box ? (box.locked ? box.unique_code : `${box.unique_code} ${box.name}`) : "an element not on this diagram";
  } else if (target?.kind === "connection") {
    const connection = edges.flatMap((e) => e.connections).find((c) => c.id === target.connectionId);
    what = connection ? `${connection.unique_code}${connection.name ? ` ${connection.name}` : ""}` : "a connection not drawn here";
  } else what = "a spot";
  return `${what}${drawn ? "" : " (not drawn)"}`;
}

/**
 * All of a note's leaders in words for the Outline: "ELM-001 Gateway; a spot", or null with none.
 *
 * @param note The note.
 * @param boxes Every box of the layout.
 * @param edges The resolved lines.
 * @param visibleBoxIds The elements drawn as boxes.
 * @param drawn The ids of the lines the canvas draws.
 */
export function noteLeadersSummary(
  note: EditorNote, boxes: readonly EditorBox[], edges: DiagramViewEdge[], visibleBoxIds: ReadonlySet<string>, drawn: ReadonlySet<string>,
): string | null {
  if (note.leaders.length === 0) return null;
  return note.leaders.map((l) => `Points at ${leaderSummary(l, boxes, edges, leaderIsDrawn(l, visibleBoxIds, edges, drawn))}`).join("; ");
}
