/**
 * Module: modules/architecture/stateMachineModel
 *
 * The state machine diagram editor's state as plain functions, with no React: the drawing being edited (each state's box
 * and nesting, each transition's attach points), the merge of a freshly read model into it, the edits a person makes and
 * the mapping to the shared canvas's nodes and lines.
 *
 * Responsibilities:
 * - `StateMachineLayout`: the part of the diagram a Save stores (`PUT .../layout`). Everything else a state or transition
 *   carries (name, kind, actions, event, guard) is read from the server's model and written at once by its own form, so
 *   it is never "unsaved".
 * - Edits return a new layout: move, resize, nest a state inside another (the child is moved into the frame and the frame
 *   grows to hold it, up the chain), fix a transition's attach points.
 * - `mergeModel`: geometry comes from the local layout, membership and display data from the model, so a reload after a
 *   state was added or removed never discards unsaved work.
 * - `canvasNodes` / `canvasEdges`: UML state machine notation on the shared canvas (a marker for an initial state, a final
 *   state and a choice, a rounded box for a state with its entry, exit and do lines, a container for a state that holds
 *   others, a loop for a transition to the same state).
 *
 * Design decisions:
 * - Canvas ids are the state and transition ids; there are no notes or boundary boxes here, so no prefixes.
 * - Only an ordinary state may hold others (a marker is a shape with no inside); the checks the server runs (one initial
 *   state per level, no depth beyond 12) are not repeated here.
 * - The shapes' sizes come from `stateShapes`, the table the server's drawing is tested against.
 */
import type { GraphCanvasEdge, GraphCanvasNode } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import {
  commitStep, isDirtyBy, redoStep, refreshPresentOf, startHistoryOf, undoStep, type History as HistoryOf,
} from "../../utils/editHistory";
import {
  COMPOSITE_HEADER_HEIGHT, COMPOSITE_PADDING, STATE_DEFAULT_SIZE, STATE_MARKERS, type StateMarkerKind,
} from "./stateShapes";
import {
  STATE_KIND_LABEL, STATE_MARKER_KINDS, type ArchitectureState, type StateKind, type StateLayoutValues, type StateMachineFinding,
  type StateMachineModel, type StateTransition, type TransitionPointsValues,
} from "./types";

/** One state's box and nesting. */
export interface StateBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
  parent_state_id: string | null;
}

/** The drawing: every state's box and the attach points chosen for transitions. */
export interface StateMachineLayout {
  boxes: StateBox[];
  points: TransitionPointsValues[];
}

export const EMPTY_STATE_LAYOUT: StateMachineLayout = { boxes: [], points: [] };

/** Gap left between states when new ones are placed in a grid. */
const GRID_GAP = 40;

/** The longest `event [guard] / action` shown on one line; a longer label breaks before the action. */
const LABEL_LINE_LENGTH = 28;

/** @param kind A state kind. @returns True when it is drawn as a marker (a shape with no text inside). */
export const isMarkerKind = (kind: StateKind): kind is StateMarkerKind => STATE_MARKER_KINDS.includes(kind);

/** @param kind A state kind. @returns The size a new state of the kind is drawn at. */
export function defaultSize(kind: StateKind): { width: number; height: number } {
  if (isMarkerKind(kind)) {
    const size = STATE_MARKERS[kind].size;
    return { width: size, height: size };
  }
  return { ...STATE_DEFAULT_SIZE };
}

/** @param state A state as the server sends it. @returns Its box. */
export function boxOfState(state: ArchitectureState): StateBox {
  return {
    id: state.id, x: state.x, y: state.y, width: state.width, height: state.height, collapsed: state.collapsed,
    parent_state_id: state.parent_state_id,
  };
}

/** @param model The model as read. @returns The drawing it holds. */
export function layoutFromModel(model: StateMachineModel): StateMachineLayout {
  return {
    boxes: model.states.map(boxOfState),
    points: model.transitions.map((t) => ({ id: t.id, source_point: t.source_point, target_point: t.target_point })),
  };
}

/**
 * Merges a freshly read model into the layout being edited: a state or transition still present keeps its local geometry,
 * nesting and attach points; a new one takes the server's; one the server no longer has is dropped.
 */
export function mergeModel(local: StateMachineLayout, model: StateMachineModel): StateMachineLayout {
  const fresh = layoutFromModel(model);
  const boxes = new Map(local.boxes.map((b) => [b.id, b]));
  const points = new Map(local.points.map((p) => [p.id, p]));
  return {
    boxes: fresh.boxes.map((b) => boxes.get(b.id) ?? b),
    points: fresh.points.map((p) => points.get(p.id) ?? p),
  };
}

/** @param layout The layout to save. @returns The request bodies of the layout save. */
export function layoutToSave(layout: StateMachineLayout): { states: StateLayoutValues[]; transitions: TransitionPointsValues[] } {
  return {
    states: layout.boxes.map((b) => ({
      id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, collapsed: b.collapsed, parent_state_id: b.parent_state_id,
    })),
    transitions: layout.points,
  };
}

/** The part of a layout a save would send, as comparable text. */
export function layoutSignature(layout: StateMachineLayout): string {
  const { states, transitions } = layoutToSave(layout);
  return JSON.stringify([
    [...states].sort((a, b) => a.id.localeCompare(b.id)),
    [...transitions].sort((a, b) => a.id.localeCompare(b.id)),
  ]);
}

// --- Edits (each returns a new layout) ---

const byId = (layout: StateMachineLayout, id: string): StateBox | undefined => layout.boxes.find((b) => b.id === id);

/** Moves states; a state inside a frame is reported by the canvas together with the frame, so each box is set as given. */
export function moveStates(layout: StateMachineLayout, moves: { id: string; x: number; y: number }[]): StateMachineLayout {
  const to = new Map(moves.map((m) => [m.id, m]));
  return { ...layout, boxes: layout.boxes.map((b) => (to.has(b.id) ? { ...b, x: to.get(b.id)!.x, y: to.get(b.id)!.y } : b)) };
}

/** Sets the position and size of states (a resize). */
export function resizeStates(
  layout: StateMachineLayout, changes: { id: string; x: number; y: number; width: number; height: number }[],
): StateMachineLayout {
  const to = new Map(changes.map((c) => [c.id, c]));
  return { ...layout, boxes: layout.boxes.map((b) => (to.has(b.id) ? { ...b, ...to.get(b.id)! } : b)) };
}

/** Adds the box of a state that was just created (the model read after it holds the same box). */
export function addStateBox(layout: StateMachineLayout, box: StateBox): StateMachineLayout {
  return layout.boxes.some((b) => b.id === box.id) ? layout : { ...layout, boxes: [...layout.boxes, box] };
}

/** Every box inside `id`, at any depth. */
export function descendantIds(layout: StateMachineLayout, id: string): Set<string> {
  const found = new Set<string>();
  let frontier = [id];
  while (frontier.length > 0) {
    const next = layout.boxes.filter((b) => b.parent_state_id !== null && frontier.includes(b.parent_state_id) && !found.has(b.id));
    next.forEach((b) => found.add(b.id));
    frontier = next.map((b) => b.id);
  }
  return found;
}

/** The id a palette item carries when dragged onto the canvas (the rest is the state kind). */
export const PALETTE_KIND_PREFIX = "state-kind:";

/** Grows each frame above `childId` so it holds the box with the padding and its name strip. */
export function growAround(layout: StateMachineLayout, childId: string): StateMachineLayout {
  let boxes = layout.boxes;
  let child = boxes.find((b) => b.id === childId);
  const seen = new Set<string>();
  while (child?.parent_state_id && !seen.has(child.id)) {
    seen.add(child.id);
    const parentId: string = child.parent_state_id;
    const parent = boxes.find((b) => b.id === parentId);
    if (!parent) break;
    const left = Math.min(parent.x, child.x - COMPOSITE_PADDING);
    const top = Math.min(parent.y, child.y - COMPOSITE_HEADER_HEIGHT - COMPOSITE_PADDING);
    const right = Math.max(parent.x + parent.width, child.x + child.width + COMPOSITE_PADDING);
    const bottom = Math.max(parent.y + parent.height, child.y + child.height + COMPOSITE_PADDING);
    const grown = { ...parent, x: left, y: top, width: right - left, height: bottom - top };
    boxes = boxes.map((b) => (b.id === parent.id ? grown : b));
    child = grown;
  }
  return { ...layout, boxes };
}

/**
 * Puts a state inside another (or at the top level with `null`). A state moved inside a frame it is not already within is
 * placed at the frame's top left, below its name strip, and every frame above it grows to hold it; its own children move
 * with it so the nesting keeps its shape. An unknown state, a marker as the parent, the state itself and one of its own
 * descendants as the parent leave the layout unchanged.
 */
export function setParent(layout: StateMachineLayout, id: string, parentId: string | null, kinds: ReadonlyMap<string, StateKind>): StateMachineLayout {
  const box = byId(layout, id);
  if (!box || box.parent_state_id === parentId) return layout;
  if (parentId !== null) {
    const parent = byId(layout, parentId);
    if (!parent || parentId === id || kinds.get(parentId) !== "state" || descendantIds(layout, id).has(parentId)) return layout;
    const within = box.x >= parent.x && box.y >= parent.y + COMPOSITE_HEADER_HEIGHT
      && box.x + box.width <= parent.x + parent.width && box.y + box.height <= parent.y + parent.height;
    const to = within ? { x: box.x, y: box.y } : { x: parent.x + COMPOSITE_PADDING, y: parent.y + COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING };
    const dx = to.x - box.x;
    const dy = to.y - box.y;
    const moving = new Set([id, ...descendantIds(layout, id)]);
    const shifted = layout.boxes.map((b) => (moving.has(b.id) ? { ...b, x: b.x + dx, y: b.y + dy } : b));
    const placed = shifted.map((b) => (b.id === id ? { ...b, parent_state_id: parentId } : b));
    let next: StateMachineLayout = { ...layout, boxes: placed };
    for (const mover of moving) next = growAround(next, mover);
    return next;
  }
  return { ...layout, boxes: layout.boxes.map((b) => (b.id === id ? { ...b, parent_state_id: null } : b)) };
}

/** Sets the attach point of one or both ends of a transition (`null` makes an end automatic). */
export function setTransitionPoints(
  layout: StateMachineLayout, id: string, change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null },
): StateMachineLayout {
  const known = layout.points.some((p) => p.id === id);
  const points = known ? layout.points : [...layout.points, { id, source_point: null, target_point: null }];
  return {
    ...layout,
    points: points.map((p) => (p.id === id ? {
      ...p,
      source_point: change.sourcePoint === undefined ? p.source_point : change.sourcePoint,
      target_point: change.targetPoint === undefined ? p.target_point : change.targetPoint,
    } : p)),
  };
}

/**
 * The innermost frame (an ordinary state) a canvas position falls in, or null. Used to nest a state dropped from the palette
 * into the frame it lands on, only where the frame already holds states (a plain state is not turned into a frame by a drop).
 */
export function frameAt(layout: StateMachineLayout, kinds: ReadonlyMap<string, StateKind>, at: { x: number; y: number }): string | null {
  const holding = new Set(layout.boxes.flatMap((b) => (b.parent_state_id ? [b.parent_state_id] : [])));
  const hits = layout.boxes.filter((b) => (
    kinds.get(b.id) === "state" && holding.has(b.id)
    && at.x >= b.x && at.x <= b.x + b.width && at.y >= b.y + COMPOSITE_HEADER_HEIGHT && at.y <= b.y + b.height
  ));
  if (hits.length === 0) return null;
  return hits.reduce((inner, b) => (b.width * b.height < inner.width * inner.height ? b : inner)).id;
}

/** The first free grid slot for a box of the given size, so a new state never lands on another. */
export function nextFreeSpot(layout: StateMachineLayout, size: { width: number; height: number } = STATE_DEFAULT_SIZE): { x: number; y: number } {
  const columns = 4;
  const cellW = STATE_DEFAULT_SIZE.width + GRID_GAP;
  const cellH = STATE_DEFAULT_SIZE.height + GRID_GAP;
  const hits = (x: number, y: number) => layout.boxes.some((b) => (
    x < b.x + b.width && x + size.width > b.x && y < b.y + b.height && y + size.height > b.y
  ));
  for (let slot = 0; slot < 400; slot += 1) {
    const x = (slot % columns) * cellW;
    const y = Math.floor(slot / columns) * cellH;
    if (!hits(x, y)) return { x, y };
  }
  return { x: 0, y: 0 };
}

/** A state with the states drawn inside it. */
export interface StateNode {
  id: string;
  state: ArchitectureState;
  children: StateNode[];
}

/** @returns The states as a forest by the drawing's nesting, in the model's order within each level. */
export function stateTree(model: StateMachineModel, layout: StateMachineLayout): StateNode[] {
  const parentOf = new Map(layout.boxes.map((b) => [b.id, b.parent_state_id]));
  const nodes = new Map(model.states.map((s) => [s.id, { id: s.id, state: s, children: [] as StateNode[] }]));
  const roots: StateNode[] = [];
  for (const state of model.states) {
    const node = nodes.get(state.id)!;
    const parent = parentOf.get(state.id);
    if (parent && nodes.has(parent)) nodes.get(parent)!.children.push(node);
    else roots.push(node);
  }
  return roots;
}

// --- History ---

export type History = HistoryOf<StateMachineLayout>;

export const startHistory = (layout: StateMachineLayout): History => startHistoryOf(layout);
export const commit = (history: History, next: StateMachineLayout): History => commitStep(history, next, layoutSignature);
export const undo = (history: History): History => undoStep(history);
export const redo = (history: History): History => redoStep(history);
export const refreshPresent = (history: History, present: StateMachineLayout): History => refreshPresentOf(history, present);
export const isDirty = (history: History): boolean => isDirtyBy(history, layoutSignature);

// --- Canvas mapping ---

/** The entry, exit and do lines of a state, one per line (empty when the state has none). */
export function actionLines(state: Pick<ArchitectureState, "entry_action" | "exit_action" | "activity">): string {
  return [
    state.entry_action && `entry / ${state.entry_action}`,
    state.exit_action && `exit / ${state.exit_action}`,
    state.activity && `do / ${state.activity}`,
  ].filter(Boolean).join("\n");
}

/** @param t A transition. @returns The text on its line: `event [guard] / action`, broken before the action when long. */
export function transitionLabel(t: Pick<StateTransition, "event" | "guard" | "action">): string {
  const head = [t.event, t.guard ? `[${t.guard}]` : ""].filter(Boolean).join(" ");
  if (!t.action) return head;
  const one = head ? `${head} / ${t.action}` : `/ ${t.action}`;
  return one.length <= LABEL_LINE_LENGTH || !head ? one : `${head}\n/ ${t.action}`;
}

/** What the canvas needs besides the model and the layout. */
export interface StateCanvasContext {
  /** The findings, to tint a state an error or warning names. */
  findings: readonly StateMachineFinding[];
  /** How a state's code is shown (the record-code display rule); the code itself by default. */
  codeOf?: (state: ArchitectureState) => string;
}

/** The tone each state code's findings call for: an error wins over a warning. */
function tonesBySubject(findings: readonly StateMachineFinding[]): Map<string, "danger" | "warning"> {
  const found = new Map<string, "danger" | "warning">();
  for (const f of findings) {
    if (!f.subject) continue;
    if (f.severity === "error") found.set(f.subject, "danger");
    else if (!found.has(f.subject)) found.set(f.subject, "warning");
  }
  return found;
}

/** @returns The canvas nodes for the model's states drawn at the layout's boxes, parents before their children. */
export function canvasNodes(model: StateMachineModel, layout: StateMachineLayout, ctx: StateCanvasContext): GraphCanvasNode[] {
  const boxes = new Map(layout.boxes.map((b) => [b.id, b]));
  const holding = new Set(layout.boxes.flatMap((b) => (b.parent_state_id ? [b.parent_state_id] : [])));
  const tones = tonesBySubject(ctx.findings);
  const depth = (state: ArchitectureState): number => {
    let found = 0;
    let at = boxes.get(state.id)?.parent_state_id ?? null;
    while (at && found < 20) {
      found += 1;
      at = boxes.get(at)?.parent_state_id ?? null;
    }
    return found;
  };
  return [...model.states].sort((a, b) => depth(a) - depth(b)).map<GraphCanvasNode>((state) => {
    const box = boxes.get(state.id) ?? boxOfState(state);
    const parentId = box.parent_state_id && boxes.has(box.parent_state_id) ? box.parent_state_id : undefined;
    if (isMarkerKind(state.kind)) {
      return {
        id: state.id, label: STATE_KIND_LABEL[state.kind], caption: state.name === STATE_KIND_LABEL[state.kind] ? undefined : state.name,
        x: box.x, y: box.y, width: box.width, height: box.height, marker: true, symbolSvg: STATE_MARKERS[state.kind].svg, parentId,
      };
    }
    return {
      id: state.id, label: state.name, caption: ctx.codeOf ? ctx.codeOf(state) : state.unique_code, body: actionLines(state) || undefined,
      x: box.x, y: box.y, width: box.width, height: box.height, container: holding.has(state.id), parentId,
      tone: tones.get(state.unique_code),
    };
  });
}

/** @returns The canvas lines for the model's transitions, with the layout's attach points. */
export function canvasEdges(model: StateMachineModel, layout: StateMachineLayout): GraphCanvasEdge[] {
  const points = new Map(layout.points.map((p) => [p.id, p]));
  return model.transitions.map<GraphCanvasEdge>((t) => ({
    id: t.id, source: t.source_state_id, target: t.target_state_id, label: transitionLabel(t) || undefined, direction: "forward",
    sourcePoint: points.get(t.id)?.source_point ?? null, targetPoint: points.get(t.id)?.target_point ?? null,
  }));
}

/** @returns The findings that name a state or transition code (or the diagram, with an empty code), for a Selection card. */
export function findingsFor(findings: readonly StateMachineFinding[], subject: string): StateMachineFinding[] {
  return findings.filter((f) => f.subject === subject);
}
