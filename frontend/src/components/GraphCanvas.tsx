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
 *   A leader is a line from a node (an annotation) to another node, to the middle of a line or to a free point: selectable,
 *   shaped by vertices and a curve like any line, with an arrowhead or a dot at either end, and drawn by dragging from the node's attach point.
 * - Offer shapes beyond the plain box with no per-consumer code: a line from a node to itself (a loop), multi-line line labels,
 *   marker nodes (a consumer-supplied drawing, no box) and containers (a rounded frame holding the nodes whose `parentId` names it).
 * - Draw consumer-supplied badges (a button on a node's corner) with no per-consumer code.
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
import type { LinePoint, LineShape } from "./graphLinePath";
import { Spinner } from "./Spinner";

/**
 * The outline a node is drawn with. `rectangle` (the default) is the usual box; the others are flags: a tip on the right
 * (`pointed-right`), on the left (`pointed-left`), at both ends (`pointed-both`), or a rounded `ellipse`. A shaped node
 * draws no accent edge and does not clip its text.
 */
export type GraphNodeOutline = "rectangle" | "pointed-right" | "pointed-left" | "pointed-both" | "ellipse";

/**
 * The colour family of a node (an annotation), drawn from the theme's tokens so it follows light and dark. `none` draws the
 * text alone, with no fill, border or dashed edge; a faint outline shows only while the node is hovered, selected or a placeholder.
 */
export type GraphNodeTone = "none" | "neutral" | "info" | "success" | "warning" | "danger";

/**
 * Plain text drawn with a marker, one line per entry of `lines` (the consumer breaks them; none is wrapped or cut here). It is
 * centred inside the marker unless `block` places it elsewhere.
 */
export interface GraphMarkerText {
  /** The lines drawn, top to bottom. */
  lines: string[];
  /** True when the text sits on the marker's fill (drawn in a light colour); false when it sits on the page. */
  onFill: boolean;
  /**
   * Where the text block is, relative to the marker's top left corner, when it is outside the marker (a label beside a decision
   * symbol): its left, top, width and height in canvas units, and how its lines are aligned. The block may lie outside the marker's
   * frame (a negative offset, or beyond its width); it is part of the node for selecting and dragging but not for line attach points,
   * and the opening view leaves room for it. It is drawn on the page, so it needs `onFill` false.
   */
  block?: { x: number; y: number; width: number; height: number; align: "left" | "center" | "right" };
}

/** One target of a badge that leads to several (a state machine diagram of a block that has more than one). */
export interface GraphNodeBadgeItem {
  id: string;
  /** The entry's text; never interpreted as markup. */
  label: string;
  onSelect: () => void;
}

/**
 * A small button on a node's top left corner, inside its frame: a sign that the node has something more elsewhere and one
 * click to reach it. It is a real button (named by `label`, which is also its tooltip), reached by Tab right after its node,
 * and it never changes the node's size. The canvas opens nothing itself: `onActivate`, or the chosen item's `onSelect`, belongs
 * to the consumer, who must offer another route to the same place (a button on a canvas is not the only way in).
 */
export interface GraphNodeBadge {
  id: string;
  /** The accessible name and tooltip ("Open state machine diagram"). */
  label: string;
  /** The icon, drawn at a fixed small size. */
  icon: ReactNode;
  /** A count drawn beside the icon when above zero. */
  count?: number;
  /** Called when the badge is pressed and `items` is absent. */
  onActivate?: () => void;
  /** The targets: one is opened at once, several are offered in a small list. Takes precedence over `onActivate`. */
  items?: GraphNodeBadgeItem[];
}

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
  /**
   * The height in canvas units the symbol is drawn at (it keeps its proportions inside a square of that side and never shrinks), so
   * a consumer that sizes the box from its content can reserve exactly that room. Without it the symbol takes up to 60% of the box.
   */
  symbolHeight?: number;
  /** The least size a resize may make the node (the content's need); defaults to 80 x 40. */
  minWidth?: number;
  minHeight?: number;
  /** A CSS colour for the node's accent edge. */
  accent?: string;
  /** Draws the border dashed (a placeholder or hidden-for-this-viewer node). */
  dashed?: boolean;
  /**
   * The distance in canvas units from the box's edge to its text on every side, the border included (a node sized to its text, such
   * as an annotation, so a line that ends at its edge ends that far from the words). Without it the box has its default padding.
   */
  inset?: number;
  /** A short heading drawn in bold above the label (a note's title); text only. A node with a title and no label is named by the title. */
  title?: string;
  /**
   * How the title, label and caption sit in the box: `left`, `center` (the default look) or `right`. Line breaks in the label are
   * kept whatever the alignment; a line longer than the box wraps between words.
   */
  textAlign?: GraphTextAlign;
  /** A short second line under the label (a type name, a code); text only. */
  caption?: string;
  /** Buttons drawn on the node's top left corner (see `GraphNodeBadge`); ignored for a marker. */
  badges?: GraphNodeBadge[];
  /**
   * Longer plain text under the caption (a note about what the node is); line breaks are kept, it never takes markup, and
   * it is clipped with an ellipsis to the lines the box has room for, so a resize shows more or less of it.
   */
  body?: string;
  /** The outline; defaults to `rectangle`. */
  outline?: GraphNodeOutline;
  /** Tints the node (its border and background) in a tone's colour; left out, the node has the usual surface. */
  tone?: GraphNodeTone;
  /** Marks `label` as a stand-in for text the node does not have yet: drawn muted, with a faint outline so the node can be found. */
  placeholder?: boolean;
  /**
   * Draws the node as a marker: no box, border or text, only `symbolSvg` filling the node's frame (a dot, a ring, a diamond).
   * The label is spoken and listed but not drawn (a `markerText` is drawn inside it). A marker is met by lines only at the middle of its sides, is not
   * resizable and is not a container.
   */
  marker?: boolean;
  /** Text drawn with a marker (a label on a decision symbol); ignored for a node that is not a marker. Plain text, never markup. */
  markerText?: GraphMarkerText;
  /**
   * The attach points an open line end may choose on this node (a fixed end is used as given), in `ATTACH_POINTS` order. Left out,
   * a marker offers the middle of each side and any other node all eight. A consumer narrows it for a marker whose label sits on
   * one side, so an automatic line never runs through the text.
   */
  attachPoints?: readonly AttachPoint[];
  /**
   * Draws the node as a container: a rounded frame with its label in a strip across the top and a see-through body, drawn
   * behind the nodes whose `parentId` names it. A node does not need this to be named as a parent; it only changes how
   * the frame looks.
   */
  container?: boolean;
  /**
   * The id of the node this one sits inside. Positions stay absolute canvas units whatever the nesting, so a consumer
   * stores one coordinate system. The child is drawn above its parent and cannot be dragged outside it; dragging or
   * moving the parent moves the children with it, and `onNodesMove` then reports the parent and every node inside it. An
   * unknown id, the node's own id and a loop of parents are ignored (the node is not nested).
   */
  parentId?: string;
}

/** How a node's text is aligned in its box. */
export type GraphTextAlign = "left" | "center" | "right";

/** What a leader points at: a node, a line (its middle) or a free position in canvas units. */
export type GraphLeaderTarget = { kind: "node"; id: string } | { kind: "edge"; id: string } | { kind: "point"; x: number; y: number };

/** How a leader begins or ends: plain, with an arrowhead or with a dot. */
export type GraphLineEnd = "none" | "arrow" | "dot";

/**
 * A line from a node to something it describes (an annotation's pointer). It is selectable (as `{ kind: "leader", id }`), its
 * vertices can be changed on the canvas (`onLeaderPointsChange`) and a new one is drawn from the node's attach point
 * (`onConnect`, `onConnectEmpty`). The canvas skips a leader whose node, target node or target line is not on the canvas, so a
 * consumer can pass every leader and let a hidden target hide its leader.
 */
export interface GraphCanvasLeader {
  id: string;
  /** The node the line starts from. */
  from: string;
  to: GraphLeaderTarget;
  /** The attach point of the starting node the line leaves from; left out, the nearest to the first vertex or to the target. */
  fromPoint?: AttachPoint;
  /** The vertices in order from the node to the target, in canvas units. */
  points?: LinePoint[];
  /** How the line runs (default straight): a curve through the vertices, or with none a bowed arc, or straight segments (`graphLinePath`). */
  lineShape?: LineShape;
  /** The start decoration; defaults to none. */
  startEnd?: GraphLineEnd;
  /** The end decoration; defaults to an arrowhead. */
  endEnd?: GraphLineEnd;
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

/**
 * A line between two nodes. A line whose source and target are the same node is drawn as a loop at the box's top right
 * corner (a fixed shape, `graphSelfLoop`); `sourcePoint` and `targetPoint` do not apply to it.
 */
export interface GraphCanvasEdge {
  id: string;
  source: string;
  target: string;
  /** Text on the line; a line break starts a new line of text. Never interpreted as markup. */
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
  /**
   * Vertices in canvas units, in order from the source to the target (`graphLinePath`). An open end meets the point of
   * its box nearest the vertex beside it. Ignored for a loop.
   */
  points?: LinePoint[];
  /**
   * How the line runs (default straight): Straight is segments through the vertices, Spline a curve through them (straight with
   * none), Curved the same curve or, with no vertices, one arc bowed to the left of the line's direction. The consumer resolves a
   * line's own shape against its diagram's default, so this is always the shape drawn.
   */
  lineShape?: LineShape;
  /** False when the consumer cannot keep a route for this line: no vertex handles are offered on it. True when omitted. */
  routable?: boolean;
}

/** What is selected: one node, one connection or one leader. */
export interface GraphCanvasSelection {
  kind: "node" | "edge" | "leader";
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
  /**
   * Called when a person draws a line from one node to another. `via.sourcePoint` is the attach point the line was drawn from
   * (a consumer that wants a leader from a node, rather than a connection, starts it there).
   */
  onConnect?: (sourceId: string, targetId: string, via?: { sourcePoint?: AttachPoint }) => void;
  /**
   * Called when a line drawn from a node is released on something that is not another node's attach point: on a line (`edge`),
   * on empty canvas (`point`, in canvas units) or on a node's body (`node`). The canvas draws nothing itself; the consumer decides
   * whether the source may start such a line (an annotation's leader does, a connection does not).
   */
  onConnectEmpty?: (sourceId: string, to: GraphLeaderTarget, via: { sourcePoint?: AttachPoint }) => void;
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
   * Where Delete and Backspace are heard. `"canvas"` (the default): only while focus is on the canvas. `"page"`: wherever the
   * focus is on the page (the toolbar, a card, nowhere in particular), so a selection made from an outline or after a symbol
   * was added at once is still deleted by the key. Either way the key is left alone in a text field, a select, a dialog or an
   * open menu, and for a line's vertex handle (which removes only the vertex).
   */
  deleteKeyScope?: "canvas" | "page";
  /**
   * Called once when a person drags one end of a line to another attach point of the same box (not in read-only mode),
   * with the end or ends that moved. The canvas stores nothing: the consumer keeps the point and passes it back as the
   * edge's `sourcePoint`/`targetPoint`. Dragging an end to a different box is ignored.
   */
  onEdgeAnchorChange?: (edgeId: string, change: { sourcePoint?: AttachPoint; targetPoint?: AttachPoint }) => void;
  /**
   * Called once when a person changes a line's vertices on the canvas (not in read-only mode): dragging a segment's middle
   * adds a vertex, dragging a vertex moves it, and double-clicking it or pressing Delete on it removes it. `points` is the whole new
   * list. The canvas stores nothing: the consumer keeps it and passes it back as the edge's `points`.
   */
  onEdgePointsChange?: (edgeId: string, points: LinePoint[]) => void;
  /** The same as `onEdgePointsChange`, for a leader's vertices; vertex handles are offered on a selected leader only when it is given. */
  onLeaderPointsChange?: (leaderId: string, points: LinePoint[]) => void;
  /**
   * Called when a node is opened by a double-click. The canvas opens nothing itself; what "open" means (a detail page, an
   * inner diagram) belongs to the consumer, who must also offer a keyboard route (Enter is left to selecting).
   */
  onNodeOpen?: (nodeId: string) => void;
  /** Called when a line is opened by a double-click; the same contract as `onNodeOpen` (the consumer offers the keyboard route). */
  onEdgeOpen?: (edgeId: string) => void;
  /**
   * Called once when a person drags a leader's target end (not in read-only mode): dropped on a node it names that node, and
   * dropped on empty canvas (or dragged, for a free end) it names that position. The canvas stores nothing: the consumer
   * keeps the target and passes it back in `leaders`.
   */
  onLeaderTargetChange?: (leaderId: string, target: GraphLeaderTarget) => void;
  /** Called when empty canvas is clicked (not in read-only mode), with the position in canvas units, before the selection is cleared. */
  onCanvasClick?: (position: { x: number; y: number }) => void;
  /**
   * Called when empty canvas is clicked outside comment mode, in read-only mode too. The canvas swallows the press itself
   * (panning), so a pop-over that closes on a click outside never sees it: a consumer with one open closes it from here.
   */
  onBackgroundClick?: () => void;
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
  /**
   * The grid size in canvas units. Giving it makes snapping available (`graphSnap`): while snapping applies, a dragged box
   * lands with its edges on the grid, a resized box has its edges on the grid when released, an arrow key moves the selected
   * box by one grid step, and a dot grid is drawn. Without it the canvas never snaps and draws its plain dotted background.
   */
  snapGrid?: number;
  /**
   * When a box's eight attach points are drawn: `near` (default) shows them only while the pointer is within 24 screen pixels
   * of the box (a container only along its edge), on the selected box, on a box with keyboard focus, and, while a line is
   * drawn, on the box it starts from and on every box the pointer nears; `always` draws them on every box all the time. The
   * points stay in the page and keep their size when hidden, so a keyboard or test route to them is unchanged.
   */
  attachPointVisibility?: "near" | "always";
  /**
   * When true a line that crosses another is drawn with a small arc over it (`graphLineHops`: the line whose id sorts later hops;
   * connections and leaders are one set of lines, a loop is not in it). Off by default.
   */
  lineHops?: boolean;
  /** The person's Snap to grid setting; off by default. Switching it on moves no box that is already placed. */
  snapOn?: boolean;
  /**
   * A `KeyboardEvent.key` (for example `Shift`) that, held during a pointer drag or resize, inverts `snapOn` for that move
   * only. It never changes a key-driven move.
   */
  snapInvertKey?: string;
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
  const labels = new Map(nodes.map((n) => [n.id, n.title && n.label ? `${n.title}: ${n.label}` : n.title || n.label]));
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
              <td>{labels.get(n.id)}</td>
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
