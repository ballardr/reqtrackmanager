/**
 * Module: components/GraphCanvas
 *
 * The one node-and-connection canvas the product shares (architecture diagrams today; workflow and glossary
 * graphs plan to reuse it). This file is the public, dependency-free entry: its types, the list fallback and a
 * lazy loader for the drawing itself (`GraphCanvasView`, the only file that imports `@xyflow/react`).
 *
 * Responsibilities:
 * - Define the plain data a consumer supplies (`GraphCanvasNode`, `GraphCanvasEdge`, `GraphCanvasLeader`, `GraphCanvasPin`)
 *   and the events it gets back. A box has eight attach points (`graphAttachPoints`); a line meets the nearest unless the consumer fixes an end.
 *   A leader is a thin line from a node (an annotation) to another node, to the middle of a line or to a free point.
 * - Offer a comment mode (a click reports what it landed on instead of selecting) and draw consumer-supplied pins at one
 *   screen size at any zoom, each rendered by the consumer (`renderPin`); a pin anchored to a node or line follows it.
 * - Load the canvas on first use, so React Flow stays out of the main bundle, and show the list view while it
 *   loads, if it fails to load, or when the person (or consumer) asks for the list.
 *
 * Design decisions:
 * - Generic: nothing here knows what a node means. A consumer passes text labels and, optionally, a sanitised
 *   SVG drawing per node; labels are always rendered as text, never as markup.
 * - The list view is a real table of nodes and connections, so a person who cannot use a canvas has the same
 *   content; it is also what a failed chunk load degrades to.
 * - Positions and sizes come in as props and go out as `onNodesMove` / `onNodesResize` on release; the consumer
 *   owns the data.
 *
 * Dependencies: `GraphCanvasView` (lazy), `TerminologyContext` strings.
 */
import { Component, lazy, Suspense, useState, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { AttachPoint } from "./graphAttachPoints";
import { Spinner } from "./Spinner";

/**
 * The outline a node is drawn with. `rectangle` (the default) is the usual box; the others are flags: a tip on the right
 * (`pointed-right`), on the left (`pointed-left`), at both ends (`pointed-both`), or a rounded `ellipse`. A shaped node
 * draws no accent edge and does not clip its text.
 */
export type GraphNodeOutline = "rectangle" | "pointed-right" | "pointed-left" | "pointed-both" | "ellipse";

/** The colour family of a node (an annotation), drawn from the theme's tokens so it follows light and dark. */
export type GraphNodeTone = "neutral" | "info" | "success" | "warning" | "danger";

/** A box on the canvas. `x`/`y` are the top-left corner in canvas units. */
export interface GraphCanvasNode {
  id: string;
  /** Text shown on the node; never interpreted as markup. */
  label: string;
  x: number;
  y: number;
  /** Size in canvas units; defaults to 160 x 64. */
  width?: number;
  height?: number;
  /** Server-sanitised SVG markup drawn on the node; a second sanitising pass runs before it is shown. */
  symbolSvg?: string;
  /** A CSS colour for the node's accent edge. */
  accent?: string;
  /** Draws the border dashed (a placeholder or hidden-for-this-viewer node). */
  dashed?: boolean;
  /** A short second line under the label (a type name, a code); text only. */
  caption?: string;
  /**
   * Longer plain text under the caption (a note about what the node is); line breaks are kept, it never takes markup, and
   * it is clipped with an ellipsis to the lines the box has room for, so a resize shows more or less of it.
   */
  body?: string;
  /** The outline; defaults to `rectangle`. */
  outline?: GraphNodeOutline;
  /** Tints the node (its border and background) in a tone's colour; none draws the usual surface. */
  tone?: GraphNodeTone;
}

/** What a leader points at: a node, a line (its middle) or a free position in canvas units. */
export type GraphLeaderTarget = { kind: "node"; id: string } | { kind: "edge"; id: string } | { kind: "point"; x: number; y: number };

/**
 * A thin line from a node to something it describes (an annotation's pointer). It is not selectable. The canvas skips a
 * leader whose node, target node or target line is not on the canvas, so a consumer can pass every leader and let a hidden
 * target hide its leader.
 */
export interface GraphCanvasLeader {
  id: string;
  /** The node the line starts from; it meets the nearest attach point of that node. */
  from: string;
  to: GraphLeaderTarget;
  /** Draws an arrowhead at the target end; defaults to true. */
  arrow?: boolean;
}

/** What a click in comment mode landed on: empty canvas, a node or a line. */
export type GraphPointAnchor = { kind: "none" } | { kind: "node"; id: string } | { kind: "edge"; id: string };

/**
 * A marker the consumer pins on the canvas (a comment). It is drawn at one screen size at any zoom. Anchored to a node it
 * sits on the node's top-right corner, anchored to a line on the line's middle (so it moves with them); otherwise, and
 * when its anchor is not on the canvas, it sits at `x`, `y` in canvas units.
 */
export interface GraphCanvasPin {
  id: string;
  x: number;
  y: number;
  anchor?: { kind: "node" | "edge"; id: string };
  /** Whether a person may drag it (and `onPinMove` is called). */
  movable?: boolean;
}

/** What `renderPin` is told besides the pin: whether its anchor is missing from the canvas (the pin sits at its last place). */
export interface GraphPinContext {
  detached: boolean;
}

/** The data-transfer type a consumer's draggable palette item sets, so a drop on the canvas reaches `onDropItem`. */
export const GRAPH_DROP_MIME = "application/x-graph-item";

/** A line between two nodes. */
export interface GraphCanvasEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  /** Draws the line dashed (a bridged or rolled-up connection). */
  dashed?: boolean;
  /** A CSS colour for the line. */
  color?: string;
  /** Arrow heads: toward the target (default), at both ends, or none. */
  direction?: "forward" | "both" | "none";
  /**
   * The attach point a person fixed on the source box, or null/undefined for automatic. An automatic end is the point
   * nearest the other end; with both automatic the line joins the two nearest points (see `graphAttachPoints`).
   */
  sourcePoint?: AttachPoint | null;
  /** The attach point fixed on the target box, or null/undefined for automatic. */
  targetPoint?: AttachPoint | null;
}

/** What is selected: one node or one connection. */
export interface GraphCanvasSelection {
  kind: "node" | "edge";
  id: string;
}

export interface GraphCanvasProps {
  nodes: GraphCanvasNode[];
  edges: GraphCanvasEdge[];
  /** Leaders (annotation pointers); none by default. */
  leaders?: GraphCanvasLeader[];
  /** Accessible name for the canvas and the list; required so every instance is named. */
  ariaLabel: string;
  /** The view shown first: `diagram` (default) or `list`. */
  initialView?: "diagram" | "list";
  /** Shows the "Show as list" / "Show as diagram" button. Defaults to true. */
  showViewToggle?: boolean;
  /** No moving, connecting or editing; selection and navigation still work. */
  readOnly?: boolean;
  /** Controlled selection; leave undefined for the canvas to keep its own. */
  selected?: GraphCanvasSelection | null;
  onSelect?: (selection: GraphCanvasSelection | null) => void;
  /** Called once when a drag ends, with every node that moved. */
  onNodesMove?: (moves: { id: string; x: number; y: number }[]) => void;
  /** Called when a person draws a line from one node to another. */
  onConnect?: (sourceId: string, targetId: string) => void;
  /** Shows resize handles on the selected node (not in read-only mode). */
  resizable?: boolean;
  /** Called once when a resize ends, with the node's final position and size. */
  onNodesResize?: (changes: { id: string; x: number; y: number; width: number; height: number }[]) => void;
  /**
   * Called when Delete or Backspace is pressed on the selected node or connection (not in read-only mode). The canvas
   * deletes nothing itself: what a delete means belongs to the consumer.
   */
  onDelete?: (selection: GraphCanvasSelection) => void;
  /**
   * Called once when a person drags one end of a line to another attach point of the same box (not in read-only mode),
   * with the end or ends that moved. The canvas stores nothing: the consumer keeps the point and passes it back as the
   * edge's `sourcePoint`/`targetPoint`. Dragging an end to a different box is ignored.
   */
  onEdgeAnchorChange?: (edgeId: string, change: { sourcePoint?: AttachPoint; targetPoint?: AttachPoint }) => void;
  /**
   * Called when a node is opened by a double-click. The canvas opens nothing itself; what "open" means (a detail page, an
   * inner diagram) belongs to the consumer, who must also offer a keyboard route (Enter is left to selecting).
   */
  onNodeOpen?: (nodeId: string) => void;
  /**
   * Called once when a person drags a leader's target end (not in read-only mode): dropped on a node it names that node, and
   * dropped on empty canvas (or dragged, for a free end) it names that position. The canvas stores nothing: the consumer
   * keeps the target and passes it back in `leaders`.
   */
  onLeaderTargetChange?: (leaderId: string, target: GraphLeaderTarget) => void;
  /** Called when empty canvas is clicked (not in read-only mode), with the position in canvas units, before the selection is cleared. */
  onCanvasClick?: (position: { x: number; y: number }) => void;
  /**
   * `select` (default) or `comment`. In comment mode nothing is moved, connected, selected or resized: a click on empty
   * canvas, a node or a line calls `onCanvasPoint` instead, and the canvas shows a crosshair.
   */
  mode?: "select" | "comment";
  /** Called by a click in comment mode with the position in canvas units and what the click landed on. */
  onCanvasPoint?: (position: { x: number; y: number }, anchor: GraphPointAnchor) => void;
  /** The pins to draw; none by default. */
  pins?: GraphCanvasPin[];
  /** Draws one pin's marker (and whatever opens from it); the canvas places it. Required to show pins. */
  renderPin?: (pin: GraphCanvasPin, context: GraphPinContext) => ReactNode;
  /**
   * Called once when a person drags a movable pin and drops it: on empty canvas (`none`) or on a node. The canvas stores
   * nothing: the consumer keeps the pin's place and passes it back in `pins`.
   */
  onPinMove?: (pinId: string, position: { x: number; y: number }, anchor: GraphPointAnchor) => void;
  /** Centres the canvas on a position when `key` changes (a link to a pin); the canvas keeps its zoom if it is already readable. */
  centerOn?: { x: number; y: number; key: number };
  /** Called when a palette item carrying `GRAPH_DROP_MIME` is dropped, with its text and the canvas position. */
  onDropItem?: (payload: string, position: { x: number; y: number }) => void;
  /** Canvas height (CSS length or pixels); defaults to 480. */
  height?: number | string;
  /**
   * The largest zoom the opening fit may use. With 1, a small graph opens at 100% (its text at the size of the page's
   * text) instead of being enlarged to fill the canvas; a graph too large for 100% still fits. Defaults to 2, the
   * canvas's own maximum zoom.
   */
  fitMaxZoom?: number;
}

const GraphCanvasView = lazy(() => import("./GraphCanvasView").then((m) => ({ default: m.GraphCanvasView })));

/**
 * Lists nodes and connections as two tables: the text alternative to the canvas and the fallback when it cannot
 * load.
 *
 * @param props Nodes, edges and the accessible name; selection is not shown here.
 */
export function GraphListView({ nodes, edges, ariaLabel }: Pick<GraphCanvasProps, "nodes" | "edges" | "ariaLabel">) {
  const text = useStrings().graphCanvas;
  const labels = new Map(nodes.map((n) => [n.id, n.label]));
  if (nodes.length === 0 && edges.length === 0) return <p className="text-muted">{text.empty}</p>;
  return (
    <div className="stack" role="group" aria-label={ariaLabel}>
      <table className="table">
        <caption className="text-muted">{text.nodesCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{text.nameColumn}</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((n) => (
            <tr key={n.id}>
              <td>{n.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {edges.length > 0 && (
        <table className="table">
          <caption className="text-muted">{text.edgesCaption}</caption>
          <thead>
            <tr>
              <th scope="col">{text.fromColumn}</th>
              <th scope="col">{text.toColumn}</th>
              <th scope="col">{text.labelColumn}</th>
            </tr>
          </thead>
          <tbody>
            {edges.map((e) => (
              <tr key={e.id}>
                <td>{labels.get(e.source) ?? e.source}</td>
                <td>{labels.get(e.target) ?? e.target}</td>
                <td>{e.label ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Catches a failed chunk load and shows the list instead, with a plain notice. */
class LoadBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * The shared canvas. Draws nodes and connections with React Flow (loaded on first use) or, in `list` view, as
 * tables.
 *
 * @param props See `GraphCanvasProps`.
 */
export function GraphCanvas(props: GraphCanvasProps) {
  const text = useStrings().graphCanvas;
  const { initialView = "diagram", showViewToggle = true } = props;
  const [view, setView] = useState(initialView);
  const list = <GraphListView nodes={props.nodes} edges={props.edges} ariaLabel={props.ariaLabel} />;
  return (
    <div className="stack">
      {showViewToggle && (
        <div className="row">
          <button type="button" className="btn" onClick={() => setView(view === "list" ? "diagram" : "list")}>
            {view === "list" ? text.showAsDiagram : text.showAsList}
          </button>
        </div>
      )}
      {view === "list" ? (
        list
      ) : (
        <LoadBoundary
          fallback={
            <>
              <p role="alert" className="text-muted">
                {text.loadFailed}
              </p>
              {list}
            </>
          }
        >
          <Suspense fallback={<Spinner label={text.loading} />}>
            <GraphCanvasView {...props} />
          </Suspense>
        </LoadBoundary>
      )}
    </div>
  );
}
