/**
 * Module: components/GraphCanvasView
 *
 * The drawing half of the shared graph canvas: React Flow (`@xyflow/react`, MIT) behind the plain props of
 * `GraphCanvas`. Loaded lazily by `GraphCanvas`; nothing else may import `@xyflow/react`
 * (`scripts/check_graph_canvas_imports.py`).
 *
 * Responsibilities:
 * - Turn `GraphCanvasNode`/`GraphCanvasEdge` into React Flow nodes and edges, and report selection, moves and new
 *   connections back through the callbacks.
 * - Draw eight attach handles on every box and route each line between the points `graphAttachPoints` chooses (the nearest
 *   pair, or the ends the consumer fixed), following a box while it is dragged or resized; dragging a line's end to
 *   another handle of the same box is reported as an anchor change.
 * - Show a box's attach points only near the pointer, on the selected box and on a box with focus (`attachPointVisibility`);
 *   the nearness is worked out from the pointer position and set as an attribute on the box's element, never as React state.
 * - Draw each leader (an annotation's pointer) as a selectable line (the routed edge: vertices, a curve, an arrowhead or a dot at either
 *   end) from its node to the target: a node (the chosen or nearest attach points), the
 *   middle of a line or a free position (a small end handle the person can drag; dropping a dragged end on a node names that node).
 * - In comment mode report a click (empty canvas, a node or a line) instead of selecting or editing, and draw the consumer's
 *   pins in a layer above the canvas: each at one screen size, anchored to a node's corner or a line's middle, draggable
 *   when `movable`, and rendered by the consumer (`renderPin`).
 * - Draw a line from a node back to itself as a loop (`graphSelfLoop`), a line label with line breaks over several lines, a
 *   marker node (consumer-supplied SVG filling the frame, met only on its sides) and a container node whose children sit
 *   inside it: React Flow places a child relative to its parent, so this file converts between that and the consumer's
 *   absolute coordinates, and moving a container reports every node inside it.
 * - Keep the canvas keyboard operable: nodes and connections take focus, Enter/Space selects, arrow keys move the
 *   selected node (React Flow's own handling, off in read-only mode), Alt with an arrow key resizes it and Delete or
 *   Backspace asks the consumer to delete it, each with a spoken name.
 *
 * Design decisions:
 * - Labels are React text children (nodes) or React Flow's SVG text (connections), never markup. A symbol is an
 *   `<img>` of a sanitised data URI (`utils/safeSvgImage`), so it cannot run script or reach the page's DOM.
 * - Lines are straight, joining two attach points, so the canvas and the server's drawing of a diagram show the same line.
 * - Selection is single (no multi-select) and deletion is not handled here: what a delete means belongs to the
 *   consumer. Selection may be controlled (`selected`) or kept here.
 * - A dragged position is kept locally until the consumer's props change to a different position, so a consumer
 *   that does not store positions still sees the node stay where it was dropped.
 * - Styling points React Flow's variables at the product tokens (`GraphCanvasView.css`).
 *
 * Dependencies: `@xyflow/react`, `utils/safeSvgImage`.
 */
import {
  Background,
  BaseEdge,
  ConnectionMode,
  Controls,
  EdgeLabelRenderer,
  getStraightPath,
  Handle,
  MarkerType,
  NodeResizer,
  Position,
  ReactFlow,
  useReactFlow,
  useViewport,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
  type FinalConnectionState,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode,
} from "react";

import { useStrings } from "../context/TerminologyContext";
import { useLatest } from "../hooks/useLatest";
import { safeSvgImage } from "../utils/safeSvgImage";
import "./GraphCanvasView.css";
import {
  GRAPH_DROP_MIME, type GraphCanvasPin, type GraphCanvasProps, type GraphCanvasSelection, type GraphLeaderTarget, type GraphLineEnd, type GraphMarkerText, type GraphNodeBadge,
  type GraphNodeOutline, type GraphNodeTone, type GraphPinContext, type GraphPointAnchor,
} from "./GraphCanvas";
import {
  ATTACH_POINTS, SIDE_POINTS, nearestPoint, pointXY, routeAttachPoints, type AttachPoint, type BoxGeometry,
} from "./graphAttachPoints";
import { nearBoxIds } from "./graphAttachProximity";
import { insertWaypoint, lineMiddle, linePath, moveWaypoint, removeWaypoint, segmentMiddles, type LinePoint } from "./graphLinePath";
import { GraphNodeBadges } from "./GraphNodeBadges";
import { selfLoop, selfLoopPath, type LoopPoint } from "./graphSelfLoop";
import { snapApplies, snapCoordinate, snapResize } from "./graphSnap";

/** A node with no badges (one shared array, so an unchanged node keeps its data identity). */
const NO_BADGES: readonly GraphNodeBadge[] = [];

const DEFAULT_WIDTH = 160;
const DEFAULT_HEIGHT = 64;
/** The smallest size a node can be resized to, by pointer or key, and the step of a key resize. */
const MIN_WIDTH = 80;
const MIN_HEIGHT = 40;
const KEY_RESIZE_STEP = 10;
const RESIZE_KEYS: Record<string, { width: number; height: number }> = {
  ArrowRight: { width: KEY_RESIZE_STEP, height: 0 },
  ArrowLeft: { width: -KEY_RESIZE_STEP, height: 0 },
  ArrowDown: { width: 0, height: KEY_RESIZE_STEP },
  ArrowUp: { width: 0, height: -KEY_RESIZE_STEP },
};

/** The id prefix of the small node that ends a leader at a line's middle or a free position, and of a leader's own line. */
const LEADER_END_PREFIX = "leader-end:";
const LEADER_EDGE_PREFIX = "leader:";
/** The side of a leader's end node, and the end handle's id. */
const LEADER_END_SIZE = 14;
const LEADER_END_HANDLE = "end";

type NodeData = {
  label: string;
  caption?: string;
  badges: readonly GraphNodeBadge[];
  body?: string;
  symbol: string | null;
  accent?: string;
  dashed?: boolean;
  outline: GraphNodeOutline;
  tone?: GraphNodeTone;
  placeholder?: boolean;
  resizable: boolean;
  marker: boolean;
  markerText?: GraphMarkerText;
  container: boolean;
};
type FlowNode = Node<NodeData, "graph"> | Node<{ free: boolean }, "leaderEnd">;
type GraphFlowNode = Node<NodeData, "graph">;

/**
 * Where each attach point's handle sits. A handle is centred on its point; the position tells React Flow which part of the
 * handle's own box a line ends on, so a corner handle uses the side facing outward vertically.
 */
const HANDLE_POSITION: Record<AttachPoint, Position> = {
  top: Position.Top, right: Position.Right, bottom: Position.Bottom, left: Position.Left,
  top_right: Position.Top, bottom_right: Position.Bottom, bottom_left: Position.Bottom, top_left: Position.Top,
};
const HANDLE_STYLE: Partial<Record<AttachPoint, CSSProperties>> = {
  top_right: { top: 0, left: "100%", transform: "translate(-50%, -50%)" },
  bottom_right: { top: "100%", left: "100%", transform: "translate(-50%, -50%)" },
  bottom_left: { top: "100%", left: 0, transform: "translate(-50%, -50%)" },
  top_left: { top: 0, left: 0, transform: "translate(-50%, -50%)" },
};

/**
 * The points of a shaped node's outline in a 0-100 square that is stretched over the box (the stroke does not stretch), or
 * null for an ellipse (drawn as an ellipse) and a rectangle (the box's own border).
 */
const OUTLINE_POINTS: Partial<Record<GraphNodeOutline, string>> = {
  "pointed-right": "0,0 88,0 100,50 88,100 0,100",
  "pointed-left": "12,0 100,0 100,100 12,100 0,50",
  "pointed-both": "12,0 88,0 100,50 88,100 12,100 0,50",
};

/** The drawn outline of a shaped node: a filled, stroked polygon or ellipse behind the label. */
function NodeOutline({ outline }: { outline: GraphNodeOutline }) {
  const points = OUTLINE_POINTS[outline];
  return (
    <svg className="graph-node-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      {points ? <polygon points={points} /> : <ellipse cx="50" cy="50" rx="49" ry="49" />}
    </svg>
  );
}

/**
 * The body text of a node, clipped with an ellipsis to the whole lines its space allows (re-measured when the box is
 * resized). Nothing is shown when not even one line fits.
 */
function NodeBody({ text }: { text: string }) {
  const frame = useRef<HTMLSpanElement>(null);
  const [lines, setLines] = useState(0);
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el) return undefined;
    const measure = () => {
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
      setLines(lineHeight > 0 ? Math.floor(el.clientHeight / lineHeight) : 0);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <span className="graph-node-body" ref={frame}>
      {lines > 0 && <span style={{ WebkitLineClamp: lines }}>{text}</span>}
    </span>
  );
}

/** One box on the canvas: accent edge, optional symbol and the text label; the eight handles are for drawing lines. */
function GraphNodeBox({ data, selected }: NodeProps<GraphFlowNode>) {
  if (data.marker) {
    return (
      <div className={data.symbol ? "graph-node-marker" : "graph-node-marker graph-node-marker-empty"}>
        {data.symbol && <img className="graph-node-marker-image" src={data.symbol} alt="" />}
        {data.markerText && data.markerText.text && (
          <span
            className={data.markerText.onFill ? "graph-node-marker-text graph-node-marker-text-on-fill" : "graph-node-marker-text"}
            style={{ width: data.markerText.width, WebkitLineClamp: data.markerText.lines }}
          >
            {data.markerText.text}
          </span>
        )}
        {SIDE_POINTS.map((point) => (
          <Handle key={point} id={point} type="source" position={HANDLE_POSITION[point]} />
        ))}
      </div>
    );
  }
  const shaped = data.outline !== "rectangle";
  const classes = [
    "graph-node", data.dashed ? "graph-node-dashed" : "", shaped ? "graph-node-shaped" : "",
    data.container ? "graph-node-container" : "",
    data.tone ? `graph-node-tone graph-node-tone-${data.tone}` : "",
    data.placeholder ? "graph-node-placeholder" : "",
  ].filter(Boolean).join(" ");
  return (
    <>
    <div className={classes} style={data.accent ? ({ "--graph-node-accent": data.accent } as CSSProperties) : undefined}>
      {shaped && <NodeOutline outline={data.outline} />}
      {data.resizable && <NodeResizer isVisible={selected} minWidth={MIN_WIDTH} minHeight={MIN_HEIGHT} />}
      {data.symbol && <img className="graph-node-symbol" src={data.symbol} alt="" />}
      <span className={data.body ? "graph-node-text graph-node-text-body" : "graph-node-text"}>
        <span className="graph-node-label">{data.label}</span>
        {data.caption && <span className="graph-node-caption">{data.caption}</span>}
        {data.body && <NodeBody text={data.body} />}
      </span>
      {ATTACH_POINTS.map((point) => (
        <Handle key={point} id={point} type="source" position={HANDLE_POSITION[point]} style={HANDLE_STYLE[point]} />
      ))}
    </div>
    <GraphNodeBadges badges={data.badges} />
    </>
  );
}

/** The end of a leader at a line's middle or a free position: a small dot, visible and draggable only for a free end. */
function LeaderEndNode({ data }: NodeProps<Node<{ free: boolean }, "leaderEnd">>) {
  return (
    <div className={data.free ? "graph-leader-end graph-leader-end-free" : "graph-leader-end"}>
      <Handle id={LEADER_END_HANDLE} type="source" position={Position.Top} isConnectable={false} />
    </div>
  );
}

const NODE_TYPES = { graph: GraphNodeBox, leaderEnd: LeaderEndNode };

/** The text of a line, one block per line break, drawn by HTML over the canvas (anchored by its middle, or by its bottom left corner). */
function EdgeLabel({ text, at, corner }: { text: string; at: LoopPoint; corner?: boolean }) {
  const place = corner ? "translate(0, -100%)" : "translate(-50%, -50%)";
  return (
    <EdgeLabelRenderer>
      <div className={corner ? "graph-edge-label graph-edge-label-corner nodrag nopan" : "graph-edge-label nodrag nopan"} style={{ transform: `${place} translate(${at.x}px, ${at.y}px)` }}>
        {text}
      </div>
    </EdgeLabelRenderer>
  );
}

/** A straight line whose label has line breaks (the built-in line draws one line of text only). */
function GraphLineEdge({ id, sourceX, sourceY, targetX, targetY, markerStart, markerEnd, style, data }: EdgeProps<Edge<{ label?: string }, "multiline">>) {
  const [path, x, y] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  return (
    <>
      <BaseEdge id={id} path={path} markerStart={markerStart} markerEnd={markerEnd} style={style} />
      {data?.label && <EdgeLabel text={data.label} at={{ x, y }} />}
    </>
  );
}

/** What a routed line is given besides React Flow's own props. */
interface RoutedEdgeData extends Record<string, unknown> {
  label?: string;
  points: LinePoint[];
  smooth: boolean;
  /** True when a selected line shows handles and the vertices can be changed. */
  editable: boolean;
  /** Called once with the whole new list of vertices when a gesture ends. */
  onChange: (points: LinePoint[]) => void;
  /** The grid step to put a dragged vertex on right now, or 0 for none (read when the pointer moves, so a held key counts). */
  grid: () => number;
  /** Opens the line (a double-click on a segment's handle, which sits over the middle of the line, is a double-click on the line). */
  open: () => void;
}

/** How far the pointer must travel, in screen pixels, before a press on a segment's middle adds a vertex. */
const VERTEX_DRAG_THRESHOLD = 4;

/**
 * A line with vertices: the path through them (`graphLinePath`), its label at the middle and, on a selected line that can be
 * edited, a handle on each vertex (drag to move, double-click or Delete to remove) and one on each segment's middle (drag to add a vertex).
 */
function GraphRoutedEdge({ sourceX, sourceY, targetX, targetY, markerStart, markerEnd, style, selected, id, data }: EdgeProps<Edge<RoutedEdgeData, "routed">>) {
  const text = useStrings().graphCanvas;
  const { screenToFlowPosition } = useReactFlow();
  const [drag, setDrag] = useState<LinePoint[] | null>(null);
  const gesture = useRef<{ index: number | null; insertAt: number | null; startX: number; startY: number; points: LinePoint[]; changed: boolean } | null>(null);
  const latest = useLatest(data);
  const stored = data?.points ?? [];
  const points = drag ?? stored;
  const start = { x: sourceX, y: sourceY };
  const end = { x: targetX, y: targetY };
  const middle = lineMiddle(start, points, end);
  const handles = Boolean(selected && data?.editable);

  /** Starts moving vertex `index`, or (`insertAt`) adding one at the segment's middle once the pointer has travelled. */
  const begin = (event: ReactPointerEvent<HTMLElement>, index: number | null, insertAt: number | null) => {
    if (event.button !== 0 || !latest.current?.editable) return;
    event.stopPropagation();
    gesture.current = { index, insertAt, startX: event.clientX, startY: event.clientY, points: stored, changed: false };
  };

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const g = gesture.current;
      if (!g) return;
      if (g.insertAt !== null && Math.hypot(event.clientX - g.startX, event.clientY - g.startY) < VERTEX_DRAG_THRESHOLD) return;
      if (g.insertAt === null && g.index === null) return;
      const at = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const grid = latest.current?.grid() ?? 0;
      const place = grid > 0 ? { x: snapCoordinate(at.x, grid), y: snapCoordinate(at.y, grid) } : { x: Math.round(at.x), y: Math.round(at.y) };
      if (g.insertAt !== null) {
        const grown = insertWaypoint(g.points, g.insertAt, place);
        if (grown.length === g.points.length) { gesture.current = null; return; }
        g.points = grown;
        g.index = g.insertAt;
        g.insertAt = null;
      } else {
        g.points = moveWaypoint(g.points, g.index as number, place);
      }
      g.changed = true;
      setDrag(g.points);
    };
    const finish = () => {
      const g = gesture.current;
      gesture.current = null;
      if (!g) return;
      setDrag(null);
      if (g.changed) latest.current?.onChange(g.points);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };
  }, [screenToFlowPosition, latest]);

  const remove = (index: number) => latest.current?.onChange(removeWaypoint(stored, index));
  const path = linePath(start, points, end, data?.smooth ?? false);
  return (
    <>
      <BaseEdge id={id} path={path} markerStart={markerStart} markerEnd={markerEnd} style={style} />
      {data?.label && <EdgeLabel text={data.label} at={middle} />}
      {handles && (
        // The handles sit in the label layer, above the line's own end grips (React Flow draws those inside the line, so on a short line
        // they would cover the middle of the segment) and above the boxes.
        <EdgeLabelRenderer>
          {segmentMiddles(start, points, end).map((at, i) => (
            <div
              key={`segment-${i}`} className="graph-segment-handle nopan nodrag" aria-hidden="true"
              style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
              onPointerDown={(event) => begin(event, null, i)}
              onDoubleClick={(event) => { event.stopPropagation(); latest.current?.open(); }}
            />
          ))}
          {points.map((at, i) => (
            <div
              key={`vertex-${i}`} className="graph-waypoint nopan nodrag" tabIndex={0} role="button" aria-label={text.waypointAria(i + 1)}
              style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
              onPointerDown={(event) => begin(event, i, null)}
              onDoubleClick={(event) => { event.stopPropagation(); remove(i); }}
              onKeyDown={(event) => {
                if (event.key !== "Delete" && event.key !== "Backspace") return;
                event.preventDefault();
                event.stopPropagation();
                remove(i);
              }}
            />
          ))}
        </EdgeLabelRenderer>
      )}
    </>
  );
}

/** A loop on one box: the path and label anchor come from `graphSelfLoop`, passed in `data`. */
function GraphLoopEdge({ id, markerStart, markerEnd, style, data }: EdgeProps<Edge<{ path: string; label?: string; at: LoopPoint }, "loop">>) {
  if (!data) return null;
  return (
    <>
      <BaseEdge id={id} path={data.path} markerStart={markerStart} markerEnd={markerEnd} style={style} />
      {data.label && <EdgeLabel text={data.label} at={data.at} corner />}
    </>
  );
}

const EDGE_TYPES = { multiline: GraphLineEdge, loop: GraphLoopEdge, routed: GraphRoutedEdge };

type Box = BoxGeometry;

/** The middle of each drawn line, by edge id, from the attach points the line joins. */
function edgeMiddles(boxes: Map<string, Box>, edges: GraphCanvasProps["edges"]): Map<string, { x: number; y: number }> {
  const middles = new Map<string, { x: number; y: number }>();
  for (const e of edges) {
    const from = boxes.get(e.source);
    const to = boxes.get(e.target);
    if (!from || !to) continue;
    if (e.source === e.target) {
      middles.set(e.id, selfLoop(from).label);
      continue;
    }
    const via = e.points ?? [];
    const [a, b] = routeAttachPoints(from, to, e.sourcePoint, e.targetPoint, via);
    middles.set(e.id, lineMiddle(pointXY(from, a), via, pointXY(to, b)));
  }
  return middles;
}

/** How far a pointer must travel before a press on a pin is a drag and not a click. */
const PIN_DRAG_THRESHOLD = 4;

type PinPlace = { pin: GraphCanvasPin; x: number; y: number; detached: boolean };

/** One pin at its screen position (the canvas position scaled by the zoom, so the marker keeps its size); draggable if movable. */
function PinItem({
  place, renderPin, onMove,
}: {
  place: PinPlace;
  renderPin: (pin: GraphCanvasPin, context: GraphPinContext) => ReactNode;
  onMove?: (pinId: string, at: { x: number; y: number }) => void;
}) {
  const { x: vx, y: vy, zoom } = useViewport();
  const { screenToFlowPosition } = useReactFlow();
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const press = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const justDragged = useRef(false);
  const draggable = place.pin.movable === true && onMove !== undefined;
  const at = drag ?? place;
  const down = (event: ReactPointerEvent<HTMLDivElement>) => {
    // A portalled pop-over's events bubble through React to here; only a press on the marker itself starts a drag.
    if (!draggable || event.button !== 0 || !event.currentTarget.contains(event.target as globalThis.Node)) return;
    press.current = { x: event.clientX, y: event.clientY, moved: false };
  };
  const move = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = press.current;
    if (!start) return;
    if (!start.moved) {
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < PIN_DRAG_THRESHOLD) return;
      start.moved = true;
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    setDrag(screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };
  const up = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = press.current;
    press.current = null;
    if (!start?.moved) return;
    justDragged.current = true;
    setDrag(null);
    onMove?.(place.pin.id, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };
  return (
    <div
      className={draggable ? "graph-pin graph-pin-movable" : "graph-pin"}
      style={{ left: at.x * zoom + vx, top: at.y * zoom + vy }}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { press.current = null; setDrag(null); }}
      onClickCapture={(event) => {
        if (!justDragged.current) return;
        justDragged.current = false;
        event.stopPropagation();
        event.preventDefault();
      }}
    >
      {renderPin(place.pin, { detached: place.detached })}
    </div>
  );
}

/** The layer of pins above the canvas; it takes no pointer events itself, only its pins do. */
function PinLayer({
  places, renderPin, onMove,
}: {
  places: PinPlace[];
  renderPin: (pin: GraphCanvasPin, context: GraphPinContext) => ReactNode;
  onMove?: (pinId: string, at: { x: number; y: number }) => void;
}) {
  return (
    <div className="graph-pin-layer">
      {places.map((place) => <PinItem key={place.pin.id} place={place} renderPin={renderPin} onMove={onMove} />)}
    </div>
  );
}

/**
 * The marker for one end of a leader: React Flow's own closed arrow, the canvas's dot (defined once in `LeaderMarkerDefs`) or none.
 * The dot's id is passed as a string, which React Flow uses as it is.
 */
function leaderMarker(end: GraphLineEnd, dotId: string): Edge["markerEnd"] {
  if (end === "arrow") return { type: MarkerType.ArrowClosed };
  return end === "dot" ? dotId : undefined;
}

/** The dot marker leaders may end in: a small filled circle in the colour of the line it ends. */
function LeaderMarkerDefs({ id }: { id: string }) {
  return (
    <svg className="graph-marker-defs" width="0" height="0" aria-hidden="true" focusable="false">
      <defs>
        <marker id={id} viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <circle cx="5" cy="5" r="4.5" fill="var(--color-text-muted)" style={{ fill: "context-stroke" }} />
        </marker>
      </defs>
    </svg>
  );
}

type Moved = Record<string, { x: number; y: number; baseX: number; baseY: number }>;
type Sized = Record<string, { width: number; height: number; baseWidth: number; baseHeight: number }>;

/**
 * Draws the canvas.
 *
 * @param props See `GraphCanvasProps`; `initialView`/`showViewToggle` are handled by `GraphCanvas`.
 */
export function GraphCanvasView({
  nodes,
  edges,
  leaders = [],
  ariaLabel,
  readOnly = false,
  selected,
  onSelect,
  onNodesMove,
  onConnect,
  onConnectEmpty,
  onEdgeAnchorChange,
  onEdgePointsChange: onEdgePointsChangeProp,
  resizable = false,
  fitMaxZoom = 2,
  onNodesResize,
  onDelete,
  onDropItem,
  onNodeOpen,
  onEdgeOpen,
  onLeaderTargetChange,
  onLeaderPointsChange: onLeaderPointsChangeProp,
  onCanvasClick,
  onBackgroundClick,
  mode = "select",
  onCanvasPoint,
  pins = [],
  renderPin,
  onPinMove,
  centerOn,
  snapGrid,
  snapOn = false,
  snapInvertKey,
  attachPointVisibility = "near",
  height = 480,
}: GraphCanvasProps) {
  const text = useStrings().graphCanvas;
  const helpId = useId();
  const dotMarkerId = `graph-dot-${useId().replace(/:/g, "")}`;
  const commenting = mode === "comment" && onCanvasPoint !== undefined;
  const [moved, setMoved] = useState<Moved>({});
  const [sized, setSized] = useState<Sized>({});
  /** A free leader end while it is dragged (and until the consumer's leader reaches it), keyed by leader id. */
  const [endMoved, setEndMoved] = useState<Record<string, { x: number; y: number; baseX: number; baseY: number }>>({});
  const flow = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null);
  /** The geometry a resize last reached, read when it ends (state is not yet committed inside that event). */
  const resizing = useRef<Record<string, { x: number; y: number; width: number; height: number }>>({});
  /** Whether snapping applied while each node was resized; the pointer is released (and the invert key may be too) before the end is reported. */
  const resizeSnapped = useRef<Record<string, boolean>>({});
  const [localSelection, setLocalSelection] = useState<GraphCanvasSelection | null>(null);
  const selection = selected !== undefined ? selected : localSelection;
  /**
   * The selection as the latest change left it. Choosing an element makes React Flow report two changes in one event (the
   * old selection is cleared through the node callback and the new one set through the edge callback, or the reverse), and
   * both callbacks would otherwise start from the selection of the last render: the later one then undid the earlier one
   * and an edge chosen while a node was selected ended with nothing selected.
   */
  const latestSelection = useRef(selection);
  useLayoutEffect(() => { latestSelection.current = selection; }, [selection]);

  // Snap to grid: the person's setting, inverted while the invert key is held during a pointer drag or resize. The key is
  // tracked on the window (focus may be anywhere) and counts only while a pointer press began on a node or a resize handle.
  const [invertHeld, setInvertHeld] = useState(false);
  const [gesture, setGesture] = useState(false);
  const snapping = snapGrid !== undefined && snapGrid > 0 && snapApplies(snapOn, invertHeld, gesture);
  const snapRef = useLatest({ size: snapGrid ?? 0, on: snapping });
  const onEdgePointsChange = useLatest(onEdgePointsChangeProp);
  const onLeaderPointsChange = useLatest(onLeaderPointsChangeProp);
  const onEdgeOpenRef = useLatest(onEdgeOpen);
  const pointsEditable = onEdgePointsChangeProp !== undefined;
  useEffect(() => {
    if (snapGrid === undefined || snapInvertKey === undefined) return undefined;
    const press = (event: globalThis.KeyboardEvent) => { if (event.key === snapInvertKey) setInvertHeld(true); };
    const release = (event: globalThis.KeyboardEvent) => { if (event.key === snapInvertKey) setInvertHeld(false); };
    const clear = () => { setInvertHeld(false); setGesture(false); };
    const endGesture = () => setGesture(false);
    window.addEventListener("keydown", press);
    window.addEventListener("keyup", release);
    window.addEventListener("blur", clear);
    window.addEventListener("pointerup", endGesture);
    window.addEventListener("pointercancel", endGesture);
    return () => {
      window.removeEventListener("keydown", press);
      window.removeEventListener("keyup", release);
      window.removeEventListener("blur", clear);
      window.removeEventListener("pointerup", endGesture);
      window.removeEventListener("pointercancel", endGesture);
    };
  }, [snapGrid, snapInvertKey]);

  const labels = useMemo(() => new Map(nodes.map((n) => [n.id, n.label])), [nodes]);

  /** The node each node sits inside: unknown ids, a node's own id and a loop of parents are ignored. */
  const parents = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    const map = new Map<string, string>();
    for (const n of nodes) if (n.parentId !== undefined && n.parentId !== n.id && ids.has(n.parentId)) map.set(n.id, n.parentId);
    for (const id of [...map.keys()]) {
      const seen = new Set([id]);
      let cur = id;
      while (map.has(cur)) {
        cur = map.get(cur)!;
        if (seen.has(cur)) { map.delete(id); break; }
        seen.add(cur);
      }
    }
    return map;
  }, [nodes]);

  /** Every node's box in absolute canvas units, with a local move or resize applied until the consumer's props catch up. */
  const boxes = useMemo(() => {
    const map = new Map<string, Box>();
    for (const n of nodes) {
      const o = moved[n.id];
      const position = o && o.baseX === n.x && o.baseY === n.y ? { x: o.x, y: o.y } : { x: n.x, y: n.y };
      const baseWidth = n.width ?? DEFAULT_WIDTH;
      const baseHeight = n.height ?? DEFAULT_HEIGHT;
      const z = sized[n.id];
      const keep = z && z.baseWidth === baseWidth && z.baseHeight === baseHeight;
      map.set(n.id, {
        ...position, width: keep ? z.width : baseWidth, height: keep ? z.height : baseHeight,
        points: n.marker ? SIDE_POINTS : undefined,
      });
    }
    return map;
  }, [nodes, moved, sized]);

  // Attach points near the pointer: the boxes the pointer is near carry `data-attach-near` on their element (the stylesheet shows
  // their points). It is set from a pointer move through the DOM, never through state, so a move re-renders nothing; the work
  // is one pass over the boxes per animation frame. Read-only and comment mode draw no points, so they track nothing.
  const wrapper = useRef<HTMLDivElement>(null);
  const nearIds = useRef<Set<string>>(new Set());
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const frame = useRef(0);
  const tracking = attachPointVisibility === "near" && !readOnly && !commenting;
  const containerIds = useMemo(() => new Set(nodes.filter((n) => n.container).map((n) => n.id)), [nodes]);
  const latestBoxes = useLatest(boxes);
  const latestContainers = useLatest(containerIds);
  const markNear = useCallback((ids: Set<string>) => {
    const root = wrapper.current;
    if (!root) return;
    const mark = (id: string, near: boolean) => {
      const el = root.querySelector(`.react-flow__node[data-id="${CSS.escape(id)}"]`);
      if (near) el?.setAttribute("data-attach-near", "true");
      else el?.removeAttribute("data-attach-near");
    };
    for (const id of nearIds.current) if (!ids.has(id)) mark(id, false);
    for (const id of ids) if (!nearIds.current.has(id)) mark(id, true);
    nearIds.current = ids;
  }, []);
  const trackPointer = useCallback((event: { clientX: number; clientY: number }) => {
    pointer.current = { x: event.clientX, y: event.clientY };
    if (frame.current !== 0) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const instance = flow.current;
      const screen = pointer.current;
      if (!instance || !screen) return;
      const at = instance.screenToFlowPosition(screen);
      const entries = Array.from(latestBoxes.current, ([id, box]): [string, Box & { container: boolean }] => [id, { ...box, container: latestContainers.current.has(id) }]);
      markNear(nearBoxIds(entries, at, instance.getZoom()));
    });
  }, [latestBoxes, latestContainers, markNear]);
  const clearNear = useCallback(() => {
    pointer.current = null;
    if (frame.current !== 0) { cancelAnimationFrame(frame.current); frame.current = 0; }
    markNear(new Set());
  }, [markNear]);
  useEffect(() => {
    if (!tracking) clearNear();
    return clearNear;
  }, [tracking, clearNear]);

  // A local move, resize or leader end lasts only until the consumer's props catch up. Once the base it was measured from
  // has changed it is spent, and is dropped: kept, it would apply again whenever the consumer's value returned to that base,
  // so an undo of the move would leave the box where it was dragged.
  const spentMoves = Object.keys(moved).filter((id) => {
    const n = nodes.find((candidate) => candidate.id === id);
    return !n || n.x !== moved[id].baseX || n.y !== moved[id].baseY;
  });
  if (spentMoves.length > 0) setMoved((m) => Object.fromEntries(Object.entries(m).filter(([id]) => !spentMoves.includes(id))));
  const spentSizes = Object.keys(sized).filter((id) => {
    const n = nodes.find((candidate) => candidate.id === id);
    return !n || (n.width ?? DEFAULT_WIDTH) !== sized[id].baseWidth || (n.height ?? DEFAULT_HEIGHT) !== sized[id].baseHeight;
  });
  if (spentSizes.length > 0) setSized((m) => Object.fromEntries(Object.entries(m).filter(([id]) => !spentSizes.includes(id))));
  const spentEnds = Object.keys(endMoved).filter((id) => {
    const l = leaders.find((candidate) => candidate.id === id);
    return !l || (l.to.kind === "point" && (l.to.x !== endMoved[id].baseX || l.to.y !== endMoved[id].baseY));
  });
  if (spentEnds.length > 0) setEndMoved((m) => Object.fromEntries(Object.entries(m).filter(([id]) => !spentEnds.includes(id))));

  /** The nodes inside each node, at any depth. */
  const descendantsOf = useCallback(
    (id: string): string[] => {
      const found: string[] = [];
      const queue = [id];
      while (queue.length > 0) {
        const at = queue.pop()!;
        for (const [child, parent] of parents) if (parent === at) { found.push(child); queue.push(child); }
      }
      return found;
    },
    [parents],
  );

  /** How many parents a node has above it; a parent is drawn before (below) its children. */
  const depthOf = useCallback((id: string) => {
    let depth = 0;
    for (let cur = parents.get(id); cur !== undefined; cur = parents.get(cur)) depth += 1;
    return depth;
  }, [parents]);

  const flowNodes = useMemo<GraphFlowNode[]>(() => {
    const ordered = parents.size > 0 ? [...nodes].sort((a, b) => depthOf(a.id) - depthOf(b.id)) : nodes;
    return ordered.map((n) => {
      const box = boxes.get(n.id)!;
      const parent = parents.get(n.id);
      const parentBox = parent !== undefined ? boxes.get(parent) : undefined;
      return {
        id: n.id,
        type: "graph",
        // React Flow positions a child relative to its parent; the consumer's coordinates stay absolute.
        position: parentBox ? { x: box.x - parentBox.x, y: box.y - parentBox.y } : { x: box.x, y: box.y },
        ...(parentBox ? { parentId: parent, extent: "parent" as const } : {}),
        width: box.width,
        height: box.height,
        selected: selection?.kind === "node" && selection.id === n.id,
        ariaLabel: text.nodeAria(n.label),
        data: {
          label: n.label, caption: n.caption, badges: n.marker ? NO_BADGES : n.badges ?? NO_BADGES, body: n.body, symbol: n.symbolSvg ? safeSvgImage(n.symbolSvg) : null,
          accent: n.accent, dashed: n.dashed, outline: n.outline ?? "rectangle", tone: n.tone, placeholder: n.placeholder,
          resizable: resizable && !readOnly && !n.marker, marker: n.marker === true, markerText: n.marker ? n.markerText : undefined, container: n.container === true,
        },
      };
    });
  }, [nodes, boxes, parents, depthOf, selection, text, resizable, readOnly]);

  const flowEdges = useMemo<Edge[]>(() => {
    return edges.flatMap<Edge>((e) => {
      const from = boxes.get(e.source);
      const to = boxes.get(e.target);
      if (!from || !to) return [];
      const direction = e.direction ?? "forward";
      const marker = { type: MarkerType.ArrowClosed, color: e.color };
      const loop = e.source === e.target;
      // A loop's shape is fixed; React Flow only needs a handle that exists on the box (every box has "top").
      const via = e.points ?? [];
      const [sourceHandle, targetHandle] = loop ? (["top", "top"] as const) : routeAttachPoints(from, to, e.sourcePoint, e.targetPoint, via);
      const multiline = e.label !== undefined && e.label.includes("\n");
      // Every line of an editable canvas is drawn by the routed edge, so its label looks the same selected or not and a drag can add a vertex.
      const editable = !readOnly && !commenting && pointsEditable && e.routable !== false;
      const routed = !loop && (via.length > 0 || (!readOnly && pointsEditable && e.routable !== false));
      const shape = loop
        ? { type: "loop", data: { path: selfLoopPath(selfLoop(from)), label: e.label, at: selfLoop(from).label } }
        : routed
          ? {
            type: "routed",
            data: {
              label: e.label, points: via, smooth: e.smooth === true, editable,
              onChange: (next: LinePoint[]) => onEdgePointsChange.current?.(e.id, next),
              grid: () => (snapRef.current.on ? snapRef.current.size : 0),
              open: () => onEdgeOpenRef.current?.(e.id),
            } satisfies RoutedEdgeData,
          }
          : multiline ? { type: "multiline", data: { label: e.label } } : { type: "straight", label: e.label };
      return [{
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle,
        targetHandle,
        ...shape,
        selected: selection?.kind === "edge" && selection.id === e.id,
        reconnectable: !readOnly && onEdgeAnchorChange !== undefined && !loop,
        ariaLabel: text.edgeAria(labels.get(e.source) ?? e.source, labels.get(e.target) ?? e.target, e.label),
        markerEnd: direction === "none" ? undefined : marker,
        markerStart: direction === "both" ? marker : undefined,
        style: { stroke: e.color, strokeDasharray: e.dashed ? "6 4" : undefined },
      }];
    });
  }, [edges, boxes, selection, labels, text, readOnly, commenting, onEdgeAnchorChange, pointsEditable, onEdgePointsChange, onEdgeOpenRef, snapRef]);

  /** Tells the consumer a leader's vertices changed, and the grid step a dragged vertex lands on right now (0 for none). */
  const leaderPointsChanged = useCallback((id: string, next: LinePoint[]) => onLeaderPointsChange.current?.(id, next), [onLeaderPointsChange]);
  const gridNow = useCallback(() => (snapRef.current.on ? snapRef.current.size : 0), [snapRef]);

  /** The leaders whose node and target are on the canvas, as React Flow edges plus the small end nodes some of them need. */
  const flowLeaders = useMemo(() => {
    const middles = edgeMiddles(boxes, edges);
    const built = leaders.flatMap<{ line: Edge; end?: Node<{ free: boolean }, "leaderEnd"> }>((l) => {
      const start = boxes.get(l.from);
      if (!start) return [];
      const via = l.points ?? [];
      const editable = !readOnly && !commenting && onLeaderPointsChangeProp !== undefined;
      const common = {
        id: LEADER_EDGE_PREFIX + l.id, source: l.from, type: "routed",
        className: selection?.kind === "node" && selection.id === l.from ? "graph-leader graph-leader-of-selected" : "graph-leader",
        selected: selection?.kind === "leader" && selection.id === l.id,
        ariaLabel: text.leaderAria(labels.get(l.from) ?? l.from, ""),
        markerStart: leaderMarker(l.startEnd ?? "none", dotMarkerId),
        markerEnd: leaderMarker(l.endEnd ?? "arrow", dotMarkerId),
        reconnectable: !readOnly && onLeaderTargetChange !== undefined ? ("target" as const) : false,
        data: {
          points: via, smooth: l.smooth === true, editable,
          onChange: (next: LinePoint[]) => leaderPointsChanged(l.id, next),
          grid: gridNow,
          open: () => undefined,
        } satisfies RoutedEdgeData,
      };
      if (l.to.kind === "node") {
        const target = boxes.get(l.to.id);
        if (!target || l.to.id === l.from) return [];
        const [sourceHandle, targetHandle] = routeAttachPoints(start, target, l.fromPoint, undefined, via);
        return [{ line: { ...common, target: l.to.id, sourceHandle, targetHandle } }];
      }
      let at: { x: number; y: number } | undefined;
      if (l.to.kind === "edge") at = middles.get(l.to.id);
      else {
        const o = endMoved[l.id];
        at = o && o.baseX === l.to.x && o.baseY === l.to.y ? { x: o.x + LEADER_END_SIZE / 2, y: o.y + LEADER_END_SIZE / 2 } : { x: l.to.x, y: l.to.y };
      }
      if (!at) return [];
      const free = l.to.kind === "point";
      const end: Node<{ free: boolean }, "leaderEnd"> = {
        id: LEADER_END_PREFIX + l.id, type: "leaderEnd", position: { x: at.x - LEADER_END_SIZE / 2, y: at.y - LEADER_END_SIZE / 2 },
        width: LEADER_END_SIZE, height: LEADER_END_SIZE, data: { free }, selectable: false, focusable: false, connectable: false,
        draggable: free && !readOnly && onLeaderTargetChange !== undefined,
      };
      const sourceHandle = l.fromPoint ?? nearestPoint(start, via[0] ?? at);
      return [{ end, line: { ...common, target: LEADER_END_PREFIX + l.id, sourceHandle, targetHandle: LEADER_END_HANDLE } }];
    });
    return { ends: built.flatMap((b) => (b.end ? [b.end] : [])), lines: built.map((b) => b.line) };
  }, [leaders, boxes, edges, endMoved, selection, readOnly, commenting, labels, text, dotMarkerId, onLeaderTargetChange, onLeaderPointsChangeProp, leaderPointsChanged, gridNow]);

  /** Where each pin is drawn: on its node's top-right corner or its line's middle, else at its own place. */
  const pinPlaces = useMemo<PinPlace[]>(() => {
    if (pins.length === 0) return [];
    const middles = edgeMiddles(boxes, edges);
    return pins.map((pin) => {
      const anchor = pin.anchor;
      if (anchor?.kind === "node") {
        const box = boxes.get(anchor.id);
        if (box) return { pin, x: box.x + box.width, y: box.y, detached: false };
      } else if (anchor?.kind === "edge") {
        const middle = middles.get(anchor.id);
        if (middle) return { pin, ...middle, detached: false };
      }
      return { pin, x: pin.x, y: pin.y, detached: anchor !== undefined };
    });
  }, [pins, boxes, edges]);

  /** The topmost node holding a canvas position (a pin dropped on it is anchored to it), else empty canvas. */
  const anchorAt = useCallback(
    (point: { x: number; y: number }): GraphPointAnchor => {
      for (let i = flowNodes.length - 1; i >= 0; i--) {
        const n = flowNodes[i];
        const box = boxes.get(n.id);
        if (box && point.x >= box.x && point.x <= box.x + box.width && point.y >= box.y && point.y <= box.y + box.height) {
          return { kind: "node", id: n.id };
        }
      }
      return { kind: "none" };
    },
    [flowNodes, boxes],
  );

  const choose = useCallback(
    (next: GraphCanvasSelection | null) => {
      latestSelection.current = next;
      setLocalSelection(next);
      onSelect?.(next);
    },
    [onSelect],
  );

  /** Applies a batch of select changes in order, so "deselect old, select new" ends on the new one. */
  const applySelect = useCallback(
    (kind: "node" | "edge", changes: { type: string; id?: string; selected?: boolean }[]) => {
      let next = latestSelection.current;
      let changed = false;
      for (const c of changes) {
        if (c.type !== "select" || c.id === undefined) continue;
        // A leader is an edge to React Flow; the consumer sees it as its own kind, under its own id.
        const leader = kind === "edge" && c.id.startsWith(LEADER_EDGE_PREFIX);
        const which = leader ? "leader" : kind;
        const id = leader ? c.id.slice(LEADER_EDGE_PREFIX.length) : c.id;
        if (c.selected) {
          next = { kind: which, id };
          changed = true;
        } else if (next?.kind === which && next.id === id) {
          next = null;
          changed = true;
        }
      }
      if (changed) choose(next);
    },
    [choose],
  );

  const onNodesChange = useCallback(
    (allChanges: NodeChange<FlowNode>[]) => {
      const isLeaderEnd = (c: NodeChange<FlowNode>) => "id" in c && c.id.startsWith(LEADER_END_PREFIX);
      for (const c of allChanges.filter(isLeaderEnd)) {
        if (readOnly || c.type !== "position" || !c.position) continue;
        const leaderId = c.id.slice(LEADER_END_PREFIX.length);
        const leader = leaders.find((l) => l.id === leaderId);
        if (!leader || leader.to.kind !== "point") continue;
        // The end is a small node placed by its top-left corner; the point it stands for is its centre, and that is what snaps.
        const grid = snapRef.current;
        const centreX = grid.on ? snapCoordinate(c.position.x + LEADER_END_SIZE / 2, grid.size) : c.position.x + LEADER_END_SIZE / 2;
        const centreY = grid.on ? snapCoordinate(c.position.y + LEADER_END_SIZE / 2, grid.size) : c.position.y + LEADER_END_SIZE / 2;
        setEndMoved((m) => ({ ...m, [leaderId]: { x: centreX - LEADER_END_SIZE / 2, y: centreY - LEADER_END_SIZE / 2, baseX: leader.to.kind === "point" ? leader.to.x : 0, baseY: leader.to.kind === "point" ? leader.to.y : 0 } }));
        if (c.dragging !== true) {
          onLeaderTargetChange?.(leaderId, { kind: "point", x: Math.round(centreX), y: Math.round(centreY) });
        }
      }
      const changes = allChanges.filter((c) => !isLeaderEnd(c)) as NodeChange<GraphFlowNode>[];
      if (!commenting) applySelect("node", changes);
      const base = new Map(nodes.map((n) => [n.id, n]));
      const resizingIds = new Set<string>();
      for (const c of changes) if (c.type === "dimensions" && c.resizing === true) resizingIds.add(c.id);
      // React Flow reports a child's position relative to its parent; the consumer's coordinates are absolute. A parent is
      // resolved before its children, so a child moved in the same batch (a resize from the top or left edge keeps the
      // children where they were) is placed against its parent's new position.
      const absolute = new Map<string, { x: number; y: number }>();
      const positioned = changes.filter((c): c is NodeChange<GraphFlowNode> & { type: "position"; position: { x: number; y: number } } => c.type === "position" && c.position !== undefined);
      positioned.sort((a, b) => depthOf(a.id) - depthOf(b.id));
      for (const c of positioned) {
        const parent = parents.get(c.id);
        const parentAt = parent !== undefined ? (absolute.get(parent) ?? boxes.get(parent)) : undefined;
        absolute.set(c.id, parentAt ? { x: parentAt.x + c.position.x, y: parentAt.y + c.position.y } : { x: c.position.x, y: c.position.y });
      }
      const finished: { id: string; x: number; y: number }[] = [];
      const resized: { id: string; x: number; y: number; width: number; height: number }[] = [];
      const patch: Moved = {};
      const sizePatch: Sized = {};
      for (const c of changes) {
        if (readOnly) break;
        if (c.type === "add") continue;
        const n = base.get(c.id);
        if (!n) continue;
        if (c.type === "position" && c.position) {
          const at = absolute.get(c.id)!;
          patch[c.id] = { x: at.x, y: at.y, baseX: n.x, baseY: n.y };
          // A resize from the top or left edge moves the node too; that is part of the resize, not a move.
          if (resizingIds.has(c.id)) {
            resizing.current[c.id] = { ...(resizing.current[c.id] ?? { width: n.width ?? DEFAULT_WIDTH, height: n.height ?? DEFAULT_HEIGHT }), x: at.x, y: at.y };
          } else {
            // A child kept in place while its container is resized from the top or left has not moved: nothing to report.
            const keptInPlace = resizingIds.has(parents.get(c.id) ?? "");
            if (c.dragging !== true && !keptInPlace) finished.push({ id: c.id, x: Math.round(at.x), y: Math.round(at.y) });
            // Moving a node moves what is inside it, and the consumer hears about those too.
            const before = boxes.get(c.id);
            for (const inner of before ? descendantsOf(c.id) : []) {
              const box = boxes.get(inner);
              const innerBase = base.get(inner);
              if (!box || !innerBase || absolute.has(inner)) continue;
              const x = box.x + at.x - before!.x;
              const y = box.y + at.y - before!.y;
              patch[inner] = { x, y, baseX: innerBase.x, baseY: innerBase.y };
              if (c.dragging !== true) finished.push({ id: inner, x: Math.round(x), y: Math.round(y) });
            }
          }
        } else if (c.type === "dimensions" && c.dimensions && c.dimensions.width > 0 && c.dimensions.height > 0 && c.resizing === true) {
          // A node measured as empty (its frame was momentarily not laid out) is not a size the person chose.
          const { width, height } = c.dimensions;
          sizePatch[c.id] = { width, height, baseWidth: n.width ?? DEFAULT_WIDTH, baseHeight: n.height ?? DEFAULT_HEIGHT };
          const last = resizing.current[c.id] ?? { x: n.x, y: n.y, width, height };
          resizing.current[c.id] = { ...last, width, height };
          resizeSnapped.current[c.id] = snapRef.current.on;
        } else if (c.type === "dimensions" && c.resizing === false) {
          const last = resizing.current[c.id];
          delete resizing.current[c.id];
          if (last) {
            const reached = {
              x: Math.round(last.x), y: Math.round(last.y),
              width: Math.round(c.dimensions && c.dimensions.width > 0 ? c.dimensions.width : last.width),
              height: Math.round(c.dimensions && c.dimensions.height > 0 ? c.dimensions.height : last.height),
            };
            // The pointer snaps in grid steps from where the resize began; on release the four edges themselves are put on the grid.
            const grid = { size: snapRef.current.size, on: resizeSnapped.current[c.id] ?? snapRef.current.on };
            delete resizeSnapped.current[c.id];
            const before = { x: n.x, y: n.y, width: n.width ?? DEFAULT_WIDTH, height: n.height ?? DEFAULT_HEIGHT };
            const final = grid.on ? snapResize(before, reached, grid.size, MIN_WIDTH, MIN_HEIGHT) : reached;
            if (grid.on) {
              patch[c.id] = { x: final.x, y: final.y, baseX: n.x, baseY: n.y };
              sizePatch[c.id] = { width: final.width, height: final.height, baseWidth: n.width ?? DEFAULT_WIDTH, baseHeight: n.height ?? DEFAULT_HEIGHT };
            }
            resized.push({ id: c.id, ...final });
          }
        }
      }
      if (Object.keys(patch).length > 0) setMoved((m) => ({ ...m, ...patch }));
      if (Object.keys(sizePatch).length > 0) setSized((m) => ({ ...m, ...sizePatch }));
      if (finished.length > 0) onNodesMove?.(finished);
      if (resized.length > 0) onNodesResize?.(resized);
    },
    [applySelect, commenting, nodes, boxes, parents, depthOf, descendantsOf, leaders, readOnly, snapRef, onNodesMove, onNodesResize, onLeaderTargetChange],
  );

  const onEdgesChange = useCallback((changes: EdgeChange[]) => { if (!commenting) applySelect("edge", changes); }, [applySelect, commenting]);

  const handleConnect = useCallback(
    (c: Connection) => {
      if (c.source && c.target) onConnect?.(c.source, c.target, { sourcePoint: (c.sourceHandle as AttachPoint | null) ?? undefined });
    },
    [onConnect],
  );

  /**
   * A line drawn from a node and released where no handle took it: on a line, on a node's body or on empty canvas. The consumer is
   * told what it landed on (a leader's end, for an annotation); a connection started from a box ignores it.
   */
  const handleConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
      if (state.isValid || !flow.current || !onConnectEmpty || !state.fromNode || !state.fromHandle) return;
      const via = { sourcePoint: (state.fromHandle.id as AttachPoint | null) ?? undefined };
      const over = state.toNode?.id;
      if (over && over !== state.fromNode.id) {
        onConnectEmpty(state.fromNode.id, { kind: "node", id: over }, via);
        return;
      }
      const point = "changedTouches" in event ? event.changedTouches[0] : event;
      const line = document.elementsFromPoint(point.clientX, point.clientY)
        .map((el) => el.closest(".react-flow__edge"))
        .find((el): el is Element => el !== null && !(el.getAttribute("data-id") ?? "").startsWith(LEADER_EDGE_PREFIX));
      const lineId = line?.getAttribute("data-id");
      if (lineId) {
        onConnectEmpty(state.fromNode.id, { kind: "edge", id: lineId }, via);
        return;
      }
      const at = flow.current.screenToFlowPosition({ x: point.clientX, y: point.clientY });
      const snap = snapRef.current;
      onConnectEmpty(
        state.fromNode.id,
        { kind: "point", x: snap.on ? snapCoordinate(at.x, snap.size) : Math.round(at.x), y: snap.on ? snapCoordinate(at.y, snap.size) : Math.round(at.y) },
        via,
      );
    },
    [onConnectEmpty, snapRef],
  );

  /**
   * A line's end was dragged to a handle. Only a move to another handle of the same box counts as choosing a point; an end
   * dropped on a different box changes nothing (a line's ends are its connection's elements, not a point to move).
   */
  const handleReconnect = useCallback(
    (previous: Edge, c: Connection) => {
      if (previous.id.startsWith(LEADER_EDGE_PREFIX)) {
        const target = c.target;
        // A leader's end dropped on another box names that box; a drop on its own end or its own note changes nothing.
        if (target && !target.startsWith(LEADER_END_PREFIX) && target !== previous.source && nodes.some((n) => n.id === target)) {
          onLeaderTargetChange?.(previous.id.slice(LEADER_EDGE_PREFIX.length), { kind: "node", id: target });
        }
        return;
      }
      if (!onEdgeAnchorChange) return;
      const forward = c.source === previous.source && c.target === previous.target;
      const swapped = c.source === previous.target && c.target === previous.source;
      if (!forward && !swapped) return;
      const sourceHandle = (forward ? c.sourceHandle : c.targetHandle) as AttachPoint | null;
      const targetHandle = (forward ? c.targetHandle : c.sourceHandle) as AttachPoint | null;
      const change: { sourcePoint?: AttachPoint; targetPoint?: AttachPoint } = {};
      if (sourceHandle && sourceHandle !== previous.sourceHandle) change.sourcePoint = sourceHandle;
      if (targetHandle && targetHandle !== previous.targetHandle) change.targetPoint = targetHandle;
      if (change.sourcePoint || change.targetPoint) onEdgeAnchorChange(previous.id, change);
    },
    [onEdgeAnchorChange, onLeaderTargetChange, nodes],
  );

  /** A leader's end dropped on empty canvas becomes a free end at that position. */
  const handleReconnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, edge: Edge, _handleType: unknown, state: FinalConnectionState) => {
      if (!edge.id.startsWith(LEADER_EDGE_PREFIX) || state.isValid || !flow.current || !onLeaderTargetChange) return;
      const leaderId = edge.id.slice(LEADER_EDGE_PREFIX.length);
      const over = state.toNode?.id;
      if (over && over !== edge.source && !over.startsWith(LEADER_END_PREFIX)) {
        onLeaderTargetChange(leaderId, { kind: "node", id: over });
        return;
      }
      const point = "changedTouches" in event ? event.changedTouches[0] : event;
      const at = flow.current.screenToFlowPosition({ x: point.clientX, y: point.clientY });
      const target: GraphLeaderTarget = { kind: "point", x: Math.round(at.x), y: Math.round(at.y) };
      onLeaderTargetChange(leaderId, target);
    },
    [onLeaderTargetChange],
  );

  const allNodes = useMemo<FlowNode[]>(() => [...flowNodes, ...flowLeaders.ends], [flowNodes, flowLeaders]);
  const allEdges = useMemo<Edge[]>(() => [...flowEdges, ...flowLeaders.lines], [flowEdges, flowLeaders]);

  // A change of `centerOn.key` moves the view to the position, keeping the zoom unless it is too small to read. The first move
  // fits the drawing explicitly before moving (the canvas's own fit on load can land after it and undo it), so the view is
  // always fitted first and then moved; the fit is never repeated, so a later move keeps the person's own zoom.
  const [initialised, setInitialised] = useState(false);
  const fittedForCentre = useRef(false);
  const centerKey = centerOn?.key;
  const latestCenter = useLatest(centerOn);
  useEffect(() => {
    const target = latestCenter.current;
    const instance = flow.current;
    if (!initialised || centerKey === undefined || target === undefined || !instance) return undefined;
    const move = () => {
      void instance.setCenter(target.x, target.y, { zoom: Math.max(instance.getZoom(), 0.75), duration: 200 });
    };
    if (fittedForCentre.current) move();
    else {
      fittedForCentre.current = true;
      void instance.fitView({ maxZoom: fitMaxZoom, duration: 0 }).then(move);
    }
    return undefined;
  }, [centerKey, latestCenter, initialised, fitMaxZoom]);

  const keyResize = resizable && !readOnly && onNodesResize !== undefined;
  const keyDelete = !readOnly && onDelete !== undefined;

  /**
   * Handles the keys React Flow does not: Alt with an arrow key resizes the selected node, and Delete or Backspace asks
   * the consumer to delete the selection. Runs before React Flow's own key handling so Alt+arrow does not also move the node.
   */
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (!selection || target.closest("input, textarea, select, [contenteditable='true'], .graph-waypoint")) return;
    const step = RESIZE_KEYS[event.key];
    if (keyResize && event.altKey && step && selection.kind === "node") {
      const node = flow.current?.getNode(selection.id);
      if (!node) return;
      event.preventDefault();
      event.stopPropagation();
      // With snapping on, a key resize steps by the grid and the edge it moves is put on the grid; otherwise the usual small step.
      const grid = snapGrid !== undefined && snapGrid > 0 && snapOn ? snapGrid : 0;
      const stepWidth = grid > 0 ? Math.sign(step.width) * grid : step.width;
      const stepHeight = grid > 0 ? Math.sign(step.height) * grid : step.height;
      const at = boxes.get(selection.id) ?? node.position;
      const before = { x: Math.round(at.x), y: Math.round(at.y), width: Math.round(node.width ?? DEFAULT_WIDTH), height: Math.round(node.height ?? DEFAULT_HEIGHT) };
      const resized = {
        ...before,
        width: Math.max(MIN_WIDTH, before.width + stepWidth),
        height: Math.max(MIN_HEIGHT, before.height + stepHeight),
      };
      const { x, y, width, height } = grid > 0 ? snapResize(before, resized, grid, MIN_WIDTH, MIN_HEIGHT) : resized;
      const base = nodes.find((n) => n.id === selection.id);
      setSized((m) => ({
        ...m,
        [selection.id]: { width, height, baseWidth: base?.width ?? DEFAULT_WIDTH, baseHeight: base?.height ?? DEFAULT_HEIGHT },
      }));
      if (grid > 0) setMoved((m) => ({ ...m, [selection.id]: { x, y, baseX: base?.x ?? x, baseY: base?.y ?? y } }));
      onNodesResize?.([{ id: selection.id, x, y, width, height }]);
    } else if (keyDelete && (event.key === "Delete" || event.key === "Backspace")) {
      event.preventDefault();
      onDelete?.(selection);
    }
  };

  const dropEnabled = onDropItem !== undefined && !readOnly;
  const allowDrop = (event: DragEvent) => {
    if (!dropEnabled || !event.dataTransfer.types.includes(GRAPH_DROP_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };
  const dropItem = (event: DragEvent) => {
    if (!dropEnabled) return;
    const payload = event.dataTransfer.getData(GRAPH_DROP_MIME);
    if (!payload || !flow.current) return;
    event.preventDefault();
    onDropItem?.(payload, flow.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };

  return (
    <div
      ref={wrapper} role="group" aria-label={ariaLabel} aria-describedby={helpId} style={{ height }}
      onDragOver={allowDrop} onDrop={dropItem} onKeyDownCapture={handleKey}
      onPointerMoveCapture={tracking ? trackPointer : undefined}
      onPointerLeave={tracking ? clearNear : undefined}
      onPointerDownCapture={(event) => {
        if (tracking) trackPointer(event);
        if (snapGrid !== undefined && (event.target as HTMLElement).closest(".react-flow__node, .react-flow__resize-control")) setGesture(true);
      }}
    >
      <span id={helpId} className="sr-only">
        {text.keyboardHelp}
        {keyResize ? ` ${text.keyboardResizeHelp}` : ""}
        {keyDelete ? ` ${text.keyboardDeleteHelp}` : ""}
        {snapGrid !== undefined && snapOn ? ` ${text.keyboardSnapHelp}` : ""}
      </span>
      <ReactFlow
        className={["graph-canvas", attachPointVisibility === "near" ? "graph-attach-near" : "", readOnly ? "graph-canvas-readonly" : "", commenting ? "graph-canvas-comment" : ""].filter(Boolean).join(" ")}
        nodes={allNodes}
        edges={allEdges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onConnectEnd={handleConnectEnd}
        onReconnect={handleReconnect}
        onReconnectEnd={handleReconnectEnd}
        onPaneClick={(event) => {
          if (!flow.current) return;
          const at = flow.current.screenToFlowPosition({ x: event.clientX, y: event.clientY });
          if (commenting) onCanvasPoint?.(at, { kind: "none" });
          else {
            onBackgroundClick?.();
            if (!readOnly) onCanvasClick?.(at);
          }
        }}
        onNodeClick={(event, node) => {
          if (!commenting || !flow.current || node.type !== "graph") return;
          onCanvasPoint?.(flow.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }), { kind: "node", id: node.id });
        }}
        onEdgeClick={(event, edge) => {
          if (!commenting || !flow.current || edge.id.startsWith(LEADER_EDGE_PREFIX)) return;
          onCanvasPoint?.(flow.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }), { kind: "edge", id: edge.id });
        }}
        edgesReconnectable={!readOnly && !commenting && (onEdgeAnchorChange !== undefined || onLeaderTargetChange !== undefined)}
        onNodeDoubleClick={(_event, node) => onNodeOpen?.(node.id)}
        onEdgeDoubleClick={(_event, edge) => { if (!edge.id.startsWith(LEADER_EDGE_PREFIX)) onEdgeOpen?.(edge.id); }}
        onInit={(instance) => { flow.current = instance; setInitialised(true); }}
        nodesDraggable={!readOnly && !commenting}
        nodesConnectable={!readOnly && !commenting}
        nodesFocusable
        edgesFocusable
        elementsSelectable
        multiSelectionKeyCode={null}
        // Selection is single, so React Flow's Shift box selection is off: it also turned any press on a node made while Shift
        // was held into a selection rectangle, which blocked the drag that Shift (the invert key of Snap to grid) is held for.
        selectionKeyCode={null}
        deleteKeyCode={null}
        snapToGrid={snapping}
        snapGrid={snapGrid !== undefined && snapGrid > 0 ? [snapGrid, snapGrid] : undefined}
        connectionMode={ConnectionMode.Loose}
        fitView
        fitViewOptions={{ maxZoom: fitMaxZoom }}
        minZoom={0.1}
        maxZoom={2}
      >
        {snapGrid === undefined ? <Background /> : snapping && <Background gap={snapGrid} />}
        <Controls showInteractive={false} />
        <LeaderMarkerDefs id={dotMarkerId} />
        {renderPin && pinPlaces.length > 0 && (
          <PinLayer
            places={pinPlaces} renderPin={renderPin}
            onMove={onPinMove ? (pinId, at) => onPinMove(pinId, at, anchorAt(at)) : undefined}
          />
        )}
      </ReactFlow>
    </div>
  );
}
