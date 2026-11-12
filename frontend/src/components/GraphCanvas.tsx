/**
 * Module: components/GraphCanvas
 *
 * The one node-and-connection canvas the product shares (architecture diagrams today; workflow and glossary
 * graphs plan to reuse it). This file is the public, dependency-free entry: its types, the list fallback and a
 * lazy loader for the drawing itself (`GraphCanvasView`, the only file that imports `@xyflow/react`).
 *
 * Responsibilities:
 * - Define the plain data a consumer supplies (`GraphCanvasNode`, `GraphCanvasEdge`) and the events it gets back.
 * - Load the canvas on first use, so React Flow stays out of the main bundle, and show the list view while it
 *   loads, if it fails to load, or when the person (or consumer) asks for the list.
 *
 * Design decisions:
 * - Generic: nothing here knows what a node means. A consumer passes text labels and, optionally, a sanitised
 *   SVG drawing per node; labels are always rendered as text, never as markup.
 * - The list view is a real table of nodes and connections, so a person who cannot use a canvas has the same
 *   content; it is also what a failed chunk load degrades to.
 * - Positions come in as props and go out as `onNodesMove` on release; the consumer owns the data.
 *
 * Dependencies: `GraphCanvasView` (lazy), `TerminologyContext` strings.
 */
import { Component, lazy, Suspense, useState, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { Spinner } from "./Spinner";

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
}

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
}

/** What is selected: one node or one connection. */
export interface GraphCanvasSelection {
  kind: "node" | "edge";
  id: string;
}

export interface GraphCanvasProps {
  nodes: GraphCanvasNode[];
  edges: GraphCanvasEdge[];
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
  /** Canvas height (CSS length or pixels); defaults to 480. */
  height?: number | string;
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
