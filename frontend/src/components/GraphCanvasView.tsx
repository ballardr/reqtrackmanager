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
 * - Keep the canvas keyboard operable: nodes and connections take focus, Enter/Space selects, arrow keys move the
 *   selected node (React Flow's own handling, off in read-only mode), each with a spoken name.
 *
 * Design decisions:
 * - Labels are React text children (nodes) or React Flow's SVG text (connections), never markup. A symbol is an
 *   `<img>` of a sanitised data URI (`utils/safeSvgImage`), so it cannot run script or reach the page's DOM.
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
  Position,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useId, useMemo, useState, type CSSProperties } from "react";

import { useStrings } from "../context/TerminologyContext";
import { safeSvgImage } from "../utils/safeSvgImage";
import "./GraphCanvasView.css";
import type { GraphCanvasProps, GraphCanvasSelection } from "./GraphCanvas";

const DEFAULT_WIDTH = 160;
const DEFAULT_HEIGHT = 64;

type NodeData = { label: string; symbol: string | null; accent?: string; dashed?: boolean };
type FlowNode = Node<NodeData, "graph">;

/** One box on the canvas: accent edge, optional symbol and the text label; handles are for drawing lines. */
function GraphNodeBox({ data }: NodeProps<FlowNode>) {
  return (
    <div
      className={data.dashed ? "graph-node graph-node-dashed" : "graph-node"}
      style={data.accent ? ({ "--graph-node-accent": data.accent } as CSSProperties) : undefined}
    >
      <Handle type="target" position={Position.Left} />
      {data.symbol && <img className="graph-node-symbol" src={data.symbol} alt="" />}
      <span className="graph-node-label">{data.label}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES = { graph: GraphNodeBox };

type Moved = Record<string, { x: number; y: number; baseX: number; baseY: number }>;

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
  height = 480,
}: GraphCanvasProps) {
  const text = useStrings().graphCanvas;
  const helpId = useId();
  const [moved, setMoved] = useState<Moved>({});
  const [localSelection, setLocalSelection] = useState<GraphCanvasSelection | null>(null);
  const selection = selected !== undefined ? selected : localSelection;

  const labels = useMemo(() => new Map(nodes.map((n) => [n.id, n.label])), [nodes]);

  const flowNodes = useMemo<FlowNode[]>(
    () =>
      nodes.map((n) => {
        const o = moved[n.id];
        const position = o && o.baseX === n.x && o.baseY === n.y ? { x: o.x, y: o.y } : { x: n.x, y: n.y };
        return {
          id: n.id,
          type: "graph",
          position,
          width: n.width ?? DEFAULT_WIDTH,
          height: n.height ?? DEFAULT_HEIGHT,
          selected: selection?.kind === "node" && selection.id === n.id,
          ariaLabel: text.nodeAria(n.label),
          data: { label: n.label, symbol: n.symbolSvg ? safeSvgImage(n.symbolSvg) : null, accent: n.accent, dashed: n.dashed },
        };
      }),
    [nodes, moved, selection, text],
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => {
        const direction = e.direction ?? "forward";
        const marker = { type: MarkerType.ArrowClosed, color: e.color };
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          label: e.label,
          selected: selection?.kind === "edge" && selection.id === e.id,
          ariaLabel: text.edgeAria(labels.get(e.source) ?? e.source, labels.get(e.target) ?? e.target, e.label),
          markerEnd: direction === "none" ? undefined : marker,
          markerStart: direction === "both" ? marker : undefined,
          style: { stroke: e.color, strokeDasharray: e.dashed ? "6 4" : undefined },
        };
      }),
    [edges, selection, labels, text],
  );

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
      const finished: { id: string; x: number; y: number }[] = [];
      const patch: Moved = {};
      for (const c of changes) {
        if (c.type !== "position" || !c.position || readOnly) continue;
        const n = base.get(c.id);
        if (!n) continue;
        patch[c.id] = { x: c.position.x, y: c.position.y, baseX: n.x, baseY: n.y };
        if (c.dragging !== true) finished.push({ id: c.id, x: Math.round(c.position.x), y: Math.round(c.position.y) });
      }
      if (Object.keys(patch).length > 0) setMoved((m) => ({ ...m, ...patch }));
      if (finished.length > 0) onNodesMove?.(finished);
    },
    [applySelect, nodes, readOnly, onNodesMove],
  );

  const onEdgesChange = useCallback((changes: EdgeChange[]) => applySelect("edge", changes), [applySelect]);

  const handleConnect = useCallback(
    (c: Connection) => {
      if (c.source && c.target) onConnect?.(c.source, c.target);
    },
    [onConnect],
  );

  return (
    <div role="group" aria-label={ariaLabel} aria-describedby={helpId} style={{ height }}>
      <span id={helpId} className="sr-only">
        {text.keyboardHelp}
      </span>
      <ReactFlow
        className={readOnly ? "graph-canvas graph-canvas-readonly" : "graph-canvas"}
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
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
