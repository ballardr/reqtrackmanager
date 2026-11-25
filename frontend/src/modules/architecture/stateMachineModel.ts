/**
 * Module: modules/architecture/stateMachineModel
 *
 * The state machine diagram editor's state as plain functions, with no React: the drawing being edited, the merge of a freshly
 * read model into it, the edits a person makes and the mapping to the shared canvas's nodes and lines.
 * - `StateMachineLayout`: the part a Save stores (`PUT .../layout`): each state's box and nesting and each transition's attach
 *   points. Name, kind, actions, event and guard are read from the server's model and written at once by their own form.
 * - Edits return a new layout: move, resize, nest a state (the child moves into the frame and the frame grows to hold it, up
 *   the chain), fix attach points. `mergeModel` takes geometry from the local layout and membership and display data from the
 *   model, so a reload never discards unsaved work.
 * - `canvasNodes` / `canvasEdges`: UML notation on the shared canvas (markers for an initial state, a final state and a
 *   choice, a rounded box with entry, exit and do lines, a container for a state that holds others, a loop for a self transition).
 * - Canvas ids are the state and transition ids. Only an ordinary state may hold others; the server's checks (one initial state
 *   per level, depth at most 12) are not repeated. Sizes come from `stateShapes`. A marker's label grows its drawn frame around
 *   the stored box's centre (`markerFrame`), so a move reported as the frame's corner is turned back into the stored box
 *   (`markerOffsets`); a label outside the symbol is drawn beside it (`besideLabel`) and `markerAttachPoints` keeps an open
 *   line end off that side.
 */
import type { GraphCanvasEdge, GraphCanvasLeader, GraphCanvasNode } from "../../components/GraphCanvas";
import { effectiveShape } from "../../components/graphLinePath";
import {
  commitStep, isDirtyBy, redoStep, refreshPresentOf, startHistoryOf, undoStep, type History as HistoryOf,
} from "../../utils/editHistory";
import {
  canvasNoteNodes, dropLeadersWithout, leaderOf, moveNotes, noteFromView, noteLeaderLines, noteToValues, notesSignature, resizeNotes, type EditorLeader,
  type EditorNote,
} from "./noteModel";
import {
  COMPOSITE_HEADER_HEIGHT, COMPOSITE_PADDING, LABEL_ON_FILL_KINDS, labelledSvg, markerAttachPoints, markerFrame, STATE_DEFAULT_SIZE, STATE_MARKERS,
  type StateMarkerKind,
} from "./stateShapes";
import { besideLabel, fitLabel } from "./symbolLabelLayout";
import {
  STATE_KIND_LABEL, STATE_MARKER_KINDS, type ArchitectureState, type LineRouteChange, type StateKind, type StateLayoutValues, type StateMachineValidationIssue,
  type StateMachineModel, type StateTransition, type TransitionPointsValues, type NoteValues,
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

/** The drawing: every state's box, the attach points chosen for transitions and the diagram's notes with their leaders. */
export interface StateMachineLayout {
  boxes: StateBox[];
  points: TransitionPointsValues[];
  notes: EditorNote[];
}

export const EMPTY_STATE_LAYOUT: StateMachineLayout = { boxes: [], points: [], notes: [] };

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
    points: model.transitions.map((t) => ({
      id: t.id, source_point: t.source_point, target_point: t.target_point, points: t.points, line_shape: t.line_shape,
    })),
    notes: model.notes.map(noteFromView),
  };
}

/**
 * Merges a freshly read model into the layout being edited: a state or transition still present keeps its local geometry,
 * nesting and attach points; a new one takes the server's; one the server does not return is dropped. Notes stay as edited
 * (a save changes them), except that a leader to a state or transition the server does not return is dropped with it.
 */
export function mergeModel(local: StateMachineLayout, model: StateMachineModel): StateMachineLayout {
  const fresh = layoutFromModel(model);
  const boxes = new Map(local.boxes.map((b) => [b.id, b]));
  const points = new Map(local.points.map((p) => [p.id, p]));
  return dropLeadersWithout(
    {
      boxes: fresh.boxes.map((b) => boxes.get(b.id) ?? b),
      points: fresh.points.map((p) => points.get(p.id) ?? p),
      notes: local.notes,
    },
    new Set(model.states.map((x) => x.id)), new Set(model.transitions.map((t) => t.id)),
  );
}

/** @param layout The layout to save. @returns The request bodies of the layout save. */
export function layoutToSave(
  layout: StateMachineLayout,
): { states: StateLayoutValues[]; transitions: TransitionPointsValues[]; notes: NoteValues[] } {
  return {
    states: layout.boxes.map((b) => ({
      id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, collapsed: b.collapsed, parent_state_id: b.parent_state_id,
    })),
    transitions: layout.points,
    notes: layout.notes.map(noteToValues),
  };
}

/** The part of a layout a save would send, as comparable text. */
export function layoutSignature(layout: StateMachineLayout): string {
  const { states, transitions } = layoutToSave(layout);
  return JSON.stringify([
    [...states].sort((a, b) => a.id.localeCompare(b.id)),
    [...transitions].sort((a, b) => a.id.localeCompare(b.id)),
    notesSignature(layout.notes),
  ]);
}

// --- Edits (each returns a new layout) ---

const byId = (layout: StateMachineLayout, id: string): StateBox | undefined => layout.boxes.find((b) => b.id === id);

/**
 * How far each marker's drawn frame lies from its stored box (the frame's corner minus the box's), for a marker whose label inside
 * it grows the frame around the box's centre. A marker drawn at its stored box (no label, or a label outside it) has none.
 *
 * @param states The diagram's states, which carry the label and its position.
 * @param layout The drawing being edited (the stored boxes).
 * @returns The offset of every marker whose frame is not its box.
 */
export function markerOffsets(states: readonly ArchitectureState[], layout: StateMachineLayout): Map<string, { x: number; y: number }> {
  const boxes = new Map(layout.boxes.map((b) => [b.id, b]));
  const found = new Map<string, { x: number; y: number }>();
  for (const state of states) {
    const box = boxes.get(state.id);
    if (!box || !isMarkerKind(state.kind)) continue;
    const frame = markerFrame(state.kind, box, state.label, state.label_position);
    if (frame.x !== box.x || frame.y !== box.y) found.set(state.id, { x: frame.x - box.x, y: frame.y - box.y });
  }
  return found;
}

/**
 * Moves states; a state inside a frame is reported by the canvas together with the frame, so each box is set as given. A move is
 * the new corner of the state's drawn frame, so a marker whose frame differs from its box is put back by that difference.
 *
 * @param layout The drawing being edited.
 * @param moves The new top left corner of each moved state's drawn frame.
 * @param offsets The frame-to-box difference of markers (`markerOffsets`); none by default.
 * @returns The layout with the boxes moved.
 */
export function moveStates(
  layout: StateMachineLayout, moves: { id: string; x: number; y: number }[], offsets: ReadonlyMap<string, { x: number; y: number }> = new Map(),
): StateMachineLayout {
  const to = new Map(moves.map((m) => [m.id, m]));
  return {
    ...moveNotes(layout, moves),
    boxes: layout.boxes.map((b) => {
      const move = to.get(b.id);
      if (!move) return b;
      const offset = offsets.get(b.id);
      return { ...b, x: move.x - (offset?.x ?? 0), y: move.y - (offset?.y ?? 0) };
    }),
  };
}

/** Sets the position and size of states (a resize). */
export function resizeStates(
  layout: StateMachineLayout, changes: { id: string; x: number; y: number; width: number; height: number }[],
): StateMachineLayout {
  const to = new Map(changes.map((c) => [c.id, c]));
  return { ...resizeNotes(layout, changes), boxes: layout.boxes.map((b) => (to.has(b.id) ? { ...b, ...to.get(b.id)! } : b)) };
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

/**
 * Sets how a transition is routed: the attach point of one or both ends (`null` makes an end automatic), its vertices
 * (an empty list leaves it to its shape) and its own shape (`null` follows the diagram's default). What the change does not name is kept.
 */
export function setTransitionPoints(
  layout: StateMachineLayout, id: string,
  change: LineRouteChange,
): StateMachineLayout {
  const known = layout.points.some((p) => p.id === id);
  const points = known ? layout.points : [...layout.points, { id, source_point: null, target_point: null, points: [], line_shape: null }];
  return {
    ...layout,
    points: points.map((p) => (p.id === id ? {
      ...p,
      source_point: change.sourcePoint === undefined ? p.source_point : change.sourcePoint,
      target_point: change.targetPoint === undefined ? p.target_point : change.targetPoint,
      points: change.points === undefined ? p.points : change.points,
      line_shape: change.lineShape === undefined ? p.line_shape : change.lineShape,
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
  /** The issues, to tint a state an error or warning names. */
  issues: readonly StateMachineValidationIssue[];
  /** How a state's code is shown (the record-code display rule); the code itself by default. */
  codeOf?: (state: ArchitectureState) => string;
  /** Text shown on a note with no text yet; "Empty note" by default. */
  emptyNote?: string;
  /** The caption of a note; "Note" by default. */
  noteCaption?: string;
}

/** The tone each state code's issues call for: an error wins over a warning. */
function tonesBySubject(issues: readonly StateMachineValidationIssue[]): Map<string, "danger" | "warning"> {
  const found = new Map<string, "danger" | "warning">();
  for (const f of issues) {
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
  const tones = tonesBySubject(ctx.issues);
  const depth = (state: ArchitectureState): number => {
    let found = 0;
    let at = boxes.get(state.id)?.parent_state_id ?? null;
    while (at && found < 20) {
      found += 1;
      at = boxes.get(at)?.parent_state_id ?? null;
    }
    return found;
  };
  const states = [...model.states].sort((a, b) => depth(a) - depth(b)).map<GraphCanvasNode>((state) => {
    const box = boxes.get(state.id) ?? boxOfState(state);
    const parentId = box.parent_state_id && boxes.has(box.parent_state_id) ? box.parent_state_id : undefined;
    if (isMarkerKind(state.kind)) {
      const inside = state.label_position === "inside";
      const layout = inside ? fitLabel(state.kind, state.label) : null;
      const frame = markerFrame(state.kind, box, state.label, state.label_position);
      const beside = inside ? null : besideLabel(state.label, state.label_position, frame.width, frame.height);
      return {
        id: state.id, label: STATE_KIND_LABEL[state.kind], caption: state.name === STATE_KIND_LABEL[state.kind] ? undefined : state.name,
        x: frame.x, y: frame.y, width: frame.width, height: frame.height, marker: true,
        symbolSvg: layout ? labelledSvg(state.kind, layout.size) : STATE_MARKERS[state.kind].svg, parentId,
        attachPoints: markerAttachPoints(state.label, state.label_position),
        markerText: layout
          ? { lines: layout.lines, onFill: LABEL_ON_FILL_KINDS.has(state.kind) }
          : beside ? { lines: beside.lines, onFill: false, block: { x: beside.x, y: beside.y, width: beside.width, height: beside.height, align: beside.align } } : undefined,
      };
    }
    return {
      id: state.id, label: state.name, caption: ctx.codeOf ? ctx.codeOf(state) : state.unique_code, body: actionLines(state) || undefined,
      x: box.x, y: box.y, width: box.width, height: box.height, container: holding.has(state.id), parentId,
      tone: tones.get(state.unique_code),
    };
  });
  return [...states, ...canvasNoteNodes(layout.notes, ctx.emptyNote ?? "Empty note", ctx.noteCaption ?? "Note")];
}

/**
 * @param layout The drawing being edited.
 * @param model The model as read (a leader to a state or transition it does not hold is not drawn).
 * @returns The canvas leader lines of the notes: a state's box, a transition's line or a free point.
 */
export function canvasLeaders(layout: StateMachineLayout, model: StateMachineModel): GraphCanvasLeader[] {
  const states = new Set(model.states.map((x) => x.id));
  const transitions = new Set(model.transitions.map((t) => t.id));
  return noteLeaderLines(layout.notes, (target) => {
    if (target.kind === "state") return states.has(target.stateId) ? { kind: "node", id: target.stateId } : null;
    if (target.kind === "transition") return transitions.has(target.transitionId) ? { kind: "edge", id: target.transitionId } : null;
    return target.kind === "point" ? { kind: "point", x: target.x, y: target.y } : null; // a block diagram's targets are not drawn here
  }, model.diagram.line_shape);
}

/**
 * @param model The model as read (it names the two states).
 * @param transition A transition.
 * @param codeOf How a state's code is shown.
 * @returns "STE-001 Idle to STE-002 Running (start)" for lists and the Outline.
 */
export function transitionName(model: StateMachineModel, transition: StateTransition, codeOf: (code: string) => string = (code) => code): string {
  const end = (id: string, code: string) => [codeOf(code), model.states.find((x) => x.id === id)?.name].filter(Boolean).join(" ");
  const ends = `${end(transition.source_state_id, transition.source_state_code)} to ${end(transition.target_state_id, transition.target_state_code)}`;
  return transition.event ? `${ends} (${transition.event})` : ends;
}

/**
 * Whether a leader's target is on the diagram: a state or transition the model holds, or a free point (always).
 *
 * @param leader The leader.
 * @param model The model as read.
 */
export function leaderIsDrawn(leader: EditorLeader, model: StateMachineModel): boolean {
  const target = leaderOf(leader);
  if (target?.kind === "state") return model.states.some((x) => x.id === target.stateId);
  if (target?.kind === "transition") return model.transitions.some((t) => t.id === target.transitionId);
  return target?.kind === "point";
}

/**
 * What a leader ends at, in words, for lists and the Outline.
 *
 * @param leader The leader.
 * @param model The model as read.
 * @param codeOf How a record code is shown.
 * @returns "STE-001 Idle", "transition STE-001 to STE-002 (start)" or "a spot".
 */
export function leaderSummary(leader: EditorLeader, model: StateMachineModel, codeOf: (code: string) => string = (code) => code): string {
  const target = leaderOf(leader);
  if (target?.kind === "state") {
    const found = model.states.find((x) => x.id === target.stateId);
    return found ? `${codeOf(found.unique_code)} ${found.name}` : "a state that is no longer on this diagram";
  }
  if (target?.kind === "transition") {
    const found = model.transitions.find((t) => t.id === target.transitionId);
    return found ? `transition ${transitionName(model, found, codeOf)}` : "a transition that is no longer on this diagram";
  }
  return "a spot";
}

/** @param model The model as read. @param codeOf How a record code is shown. @returns The "Points at" options: every state and every transition. */
export function leaderTargetOptions(model: StateMachineModel, codeOf: (code: string) => string = (code) => code): { value: string; label: string }[] {
  return [
    ...model.states.map((x) => ({ value: `state:${x.id}`, label: `State: ${codeOf(x.unique_code)} ${x.name}` })),
    ...model.transitions.map((t) => ({ value: `transition:${t.id}`, label: `Transition: ${transitionName(model, t, codeOf)}` })),
  ];
}

/** @returns The canvas lines for the model's transitions, with the layout's attach points. */
export function canvasEdges(model: StateMachineModel, layout: StateMachineLayout): GraphCanvasEdge[] {
  const points = new Map(layout.points.map((p) => [p.id, p]));
  return model.transitions.map<GraphCanvasEdge>((t) => ({
    id: t.id, source: t.source_state_id, target: t.target_state_id, label: transitionLabel(t) || undefined, direction: "forward",
    sourcePoint: points.get(t.id)?.source_point ?? null, targetPoint: points.get(t.id)?.target_point ?? null,
    points: points.get(t.id)?.points ?? [], lineShape: effectiveShape(points.get(t.id)?.line_shape, model.diagram.line_shape),
  }));
}

/** @returns The issues that name a state or transition code (or the diagram, with an empty code), for a Selection card. */
export function issuesFor(issues: readonly StateMachineValidationIssue[], subject: string): StateMachineValidationIssue[] {
  return issues.filter((f) => f.subject === subject);
}
