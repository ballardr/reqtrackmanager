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
  ConnectionMode,
  Controls,
  Handle,
  MarkerType,
  NodeResizer,
  Position,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useId, useMemo, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent } from "react";

import { useStrings } from "../context/TerminologyContext";
import { safeSvgImage } from "../utils/safeSvgImage";
import "./GraphCanvasView.css";
import { GRAPH_DROP_MIME, type GraphCanvasProps, type GraphCanvasSelection } from "./GraphCanvas";
import { ATTACH_POINTS, lineAttachPoints, type AttachPoint } from "./graphAttachPoints";

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

type NodeData = { label: string; caption?: string; symbol: string | null; accent?: string; dashed?: boolean; resizable: boolean };
type FlowNode = Node<NodeData, "graph">;

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

/** One box on the canvas: accent edge, optional symbol and the text label; the eight handles are for drawing lines. */
function GraphNodeBox({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div
      className={data.dashed ? "graph-node graph-node-dashed" : "graph-node"}
      style={data.accent ? ({ "--graph-node-accent": data.accent } as CSSProperties) : undefined}
    >
      {data.resizable && <NodeResizer isVisible={selected} minWidth={MIN_WIDTH} minHeight={MIN_HEIGHT} />}
      {data.symbol && <img className="graph-node-symbol" src={data.symbol} alt="" />}
      <span className="graph-node-text">
        <span className="graph-node-label">{data.label}</span>
        {data.caption && <span className="graph-node-caption">{data.caption}</span>}
      </span>
      {ATTACH_POINTS.map((point) => (
        <Handle key={point} id={point} type="source" position={HANDLE_POSITION[point]} style={HANDLE_STYLE[point]} />
      ))}
    </div>
  );
}

const NODE_TYPES = { graph: GraphNodeBox };

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
  ariaLabel,
  readOnly = false,
  selected,
  onSelect,
  onNodesMove,
  onConnect,
  onEdgeAnchorChange,
  resizable = false,
  onNodesResize,
  onDelete,
  onDropItem,
  height = 480,
}: GraphCanvasProps) {
  const text = useStrings().graphCanvas;
  const helpId = useId();
  const [moved, setMoved] = useState<Moved>({});
  const [sized, setSized] = useState<Sized>({});
  const flow = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null);
  /** The geometry a resize last reached, read when it ends (state is not yet committed inside that event). */
  const resizing = useRef<Record<string, { x: number; y: number; width: number; height: number }>>({});
  const [localSelection, setLocalSelection] = useState<GraphCanvasSelection | null>(null);
  const selection = selected !== undefined ? selected : localSelection;

  const labels = useMemo(() => new Map(nodes.map((n) => [n.id, n.label])), [nodes]);

  const flowNodes = useMemo<FlowNode[]>(
    () =>
      nodes.map((n) => {
        const o = moved[n.id];
        const position = o && o.baseX === n.x && o.baseY === n.y ? { x: o.x, y: o.y } : { x: n.x, y: n.y };
        const baseWidth = n.width ?? DEFAULT_WIDTH;
        const baseHeight = n.height ?? DEFAULT_HEIGHT;
        const z = sized[n.id];
        const keep = z && z.baseWidth === baseWidth && z.baseHeight === baseHeight;
        return {
          id: n.id,
          type: "graph",
          position,
          width: keep ? z.width : baseWidth,
          height: keep ? z.height : baseHeight,
          selected: selection?.kind === "node" && selection.id === n.id,
          ariaLabel: text.nodeAria(n.label),
          data: {
            label: n.label, caption: n.caption, symbol: n.symbolSvg ? safeSvgImage(n.symbolSvg) : null,
            accent: n.accent, dashed: n.dashed, resizable: resizable && !readOnly,
          },
        };
      }),
    [nodes, moved, sized, selection, text, resizable, readOnly],
  );

  const flowEdges = useMemo<Edge[]>(() => {
    const boxes = new Map(flowNodes.map((n) => [n.id, { x: n.position.x, y: n.position.y, width: n.width ?? DEFAULT_WIDTH, height: n.height ?? DEFAULT_HEIGHT }]));
    return edges.flatMap<Edge>((e) => {
      const from = boxes.get(e.source);
      const to = boxes.get(e.target);
      if (!from || !to) return [];
      const direction = e.direction ?? "forward";
      const marker = { type: MarkerType.ArrowClosed, color: e.color };
      const [sourceHandle, targetHandle] = lineAttachPoints(from, to, e.sourcePoint, e.targetPoint);
      return [{
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle,
        targetHandle,
        type: "straight",
        label: e.label,
        selected: selection?.kind === "edge" && selection.id === e.id,
        reconnectable: !readOnly && onEdgeAnchorChange !== undefined,
        ariaLabel: text.edgeAria(labels.get(e.source) ?? e.source, labels.get(e.target) ?? e.target, e.label),
        markerEnd: direction === "none" ? undefined : marker,
        markerStart: direction === "both" ? marker : undefined,
        style: { stroke: e.color, strokeDasharray: e.dashed ? "6 4" : undefined },
      }];
    });
  }, [edges, flowNodes, selection, labels, text, readOnly, onEdgeAnchorChange]);

  const choose = useCallback(
    (next: GraphCanvasSelection | null) => {
      setLocalSelection(next);
      onSelect?.(next);
    },
    [onSelect],
  );

  /** Applies a batch of select changes in order, so "deselect old, select new" ends on the new one. */
  const applySelect = useCallback(
    (kind: "node" | "edge", changes: { type: string; id?: string; selected?: boolean }[]) => {
      let next = selection;
      let changed = false;
      for (const c of changes) {
        if (c.type !== "select" || c.id === undefined) continue;
        if (c.selected) {
          next = { kind, id: c.id };
          changed = true;
        } else if (next?.kind === kind && next.id === c.id) {
          next = null;
          changed = true;
        }
      }
      if (changed) choose(next);
    },
    [selection, choose],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      applySelect("node", changes);
      const base = new Map(nodes.map((n) => [n.id, n]));
      const resizingIds = new Set<string>();
      for (const c of changes) if (c.type === "dimensions" && c.resizing === true) resizingIds.add(c.id);
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
          patch[c.id] = { x: c.position.x, y: c.position.y, baseX: n.x, baseY: n.y };
          // A resize from the top or left edge moves the node too; that is part of the resize, not a move.
          if (resizingIds.has(c.id)) {
            resizing.current[c.id] = { ...(resizing.current[c.id] ?? { width: n.width ?? DEFAULT_WIDTH, height: n.height ?? DEFAULT_HEIGHT }), x: c.position.x, y: c.position.y };
          } else if (c.dragging !== true) {
            finished.push({ id: c.id, x: Math.round(c.position.x), y: Math.round(c.position.y) });
          }
        } else if (c.type === "dimensions" && c.dimensions && c.dimensions.width > 0 && c.dimensions.height > 0 && c.resizing === true) {
          // A node measured as empty (its frame was momentarily not laid out) is not a size the person chose.
          const { width, height } = c.dimensions;
          sizePatch[c.id] = { width, height, baseWidth: n.width ?? DEFAULT_WIDTH, baseHeight: n.height ?? DEFAULT_HEIGHT };
          const last = resizing.current[c.id] ?? { x: n.x, y: n.y, width, height };
          resizing.current[c.id] = { ...last, width, height };
        } else if (c.type === "dimensions" && c.resizing === false) {
          const last = resizing.current[c.id];
          delete resizing.current[c.id];
          if (last) {
            resized.push({
              id: c.id, x: Math.round(last.x), y: Math.round(last.y),
              width: Math.round(c.dimensions && c.dimensions.width > 0 ? c.dimensions.width : last.width),
              height: Math.round(c.dimensions && c.dimensions.height > 0 ? c.dimensions.height : last.height),
            });
          }
        }
      }
      if (Object.keys(patch).length > 0) setMoved((m) => ({ ...m, ...patch }));
      if (Object.keys(sizePatch).length > 0) setSized((m) => ({ ...m, ...sizePatch }));
      if (finished.length > 0) onNodesMove?.(finished);
      if (resized.length > 0) onNodesResize?.(resized);
    },
    [applySelect, nodes, readOnly, onNodesMove, onNodesResize],
  );

  const onEdgesChange = useCallback((changes: EdgeChange[]) => applySelect("edge", changes), [applySelect]);

  const handleConnect = useCallback(
    (c: Connection) => {
      if (c.source && c.target) onConnect?.(c.source, c.target);
    },
    [onConnect],
  );

  /**
   * A line's end was dragged to a handle. Only a move to another handle of the same box counts as choosing a point; an end
   * dropped on a different box changes nothing (a line's ends are its connection's elements, not a point to move).
   */
  const handleReconnect = useCallback(
    (previous: Edge, c: Connection) => {
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
    [onEdgeAnchorChange],
  );

  const keyResize = resizable && !readOnly && onNodesResize !== undefined;
  const keyDelete = !readOnly && onDelete !== undefined;

  /**
   * Handles the keys React Flow does not: Alt with an arrow key resizes the selected node, and Delete or Backspace asks
   * the consumer to delete the selection. Runs before React Flow's own key handling so Alt+arrow does not also move the node.
   */
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (!selection || target.closest("input, textarea, select, [contenteditable='true']")) return;
    const step = RESIZE_KEYS[event.key];
    if (keyResize && event.altKey && step && selection.kind === "node") {
      const node = flow.current?.getNode(selection.id);
      if (!node) return;
      event.preventDefault();
      event.stopPropagation();
      const width = Math.max(MIN_WIDTH, Math.round((node.width ?? DEFAULT_WIDTH) + step.width));
      const height = Math.max(MIN_HEIGHT, Math.round((node.height ?? DEFAULT_HEIGHT) + step.height));
      const base = nodes.find((n) => n.id === selection.id);
      setSized((m) => ({
        ...m,
        [selection.id]: { width, height, baseWidth: base?.width ?? DEFAULT_WIDTH, baseHeight: base?.height ?? DEFAULT_HEIGHT },
      }));
      onNodesResize?.([{ id: selection.id, x: Math.round(node.position.x), y: Math.round(node.position.y), width, height }]);
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
      role="group" aria-label={ariaLabel} aria-describedby={helpId} style={{ height }}
      onDragOver={allowDrop} onDrop={dropItem} onKeyDownCapture={handleKey}
    >
      <span id={helpId} className="sr-only">
        {text.keyboardHelp}
        {keyResize ? ` ${text.keyboardResizeHelp}` : ""}
        {keyDelete ? ` ${text.keyboardDeleteHelp}` : ""}
      </span>
      <ReactFlow
        className={readOnly ? "graph-canvas graph-canvas-readonly" : "graph-canvas"}
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onReconnect={handleReconnect}
        edgesReconnectable={!readOnly && onEdgeAnchorChange !== undefined}
        onInit={(instance) => { flow.current = instance; }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        nodesFocusable
        edgesFocusable
        elementsSelectable
        multiSelectionKeyCode={null}
        deleteKeyCode={null}
        connectionMode={ConnectionMode.Loose}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
