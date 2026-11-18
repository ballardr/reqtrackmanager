/**
 * Module: modules/architecture/DiagramOutline
 *
 * The editor's "Outline" card: the text alternative to the canvas, with the same content in a form a keyboard or screen
 * reader can use. It lists the elements shown as a tree (nested by their parent among the elements placed), the notes (each with
 * what its leader points at, and whether that is drawn), and the
 * lines drawn as a table with their ends, direction, type, count and, for a bridged line, the hidden elements it passes
 * through. On a diagram of an element's inside the outer connections (boundary boxes) are a table too, each with its
 * direction and whether it is covered.
 *
 * Responsibilities:
 * - Follow the page: it is built from the layout being edited, the lines resolved for the current view switches and the
 *   hidden set, so an unsaved box, a flipped switch or a bridged line shows here as on the canvas.
 * - Share the selection with the canvas: choosing an element, note or line here selects it on the canvas and in the
 *   Selection card, and the reverse.
 *
 * Design decisions:
 * - Elements a switch hides are not listed; only how many are hidden is stated, since that is what the person needs to see
 *   every time to read the diagram correctly.
 * - The elements can be read as a tree or as a table like the lines (the shared `ViewToggle`, remembered per person); the
 *   tree has Expand all and Collapse all, and each section collapses (the shared `CollapsibleSection`, remembered too).
 * - Built on the shared `TreeView` shell and the shared table styles; every row is a real button, so the whole outline is
 *   operable from the keyboard.
 */
import { useState } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { DetailCard } from "../../components/DetailCard";
import { HelpHeader } from "../../components/HelpHeader";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { TreeView } from "../../components/TreeView";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import { useRecordCode } from "../../hooks/useRecordCode";
import { BOUNDARY_SHAPE_LABEL, boundaryNodeId, boundaryOutsideName, leaderIsDrawn, leaderSummary, type EditorBoundary, type EditorBox } from "./diagramEditorModel";
import { NotesOutlineSection } from "./NotesOutlineSection";
import type { EditorNote } from "./noteModel";
import {
  boxName, connectionRows, elementRows, outlineBranchIds, outlineSize, outlineTree, type ConnectionRow,
} from "./diagramOutlineModel";
import type { DiagramAnchor, DiagramViewEdge, ModelStateMachine } from "./types";
import { ARCHITECTURE_HELP } from "./help";

const ROUTE_LABEL: Record<ConnectionRow["route"], string> = { direct: "Direct", rolled_up: "Rolled up", bridged: "Bridged" };

/**
 * @param boxes Every box of the layout.
 * @param notes Every note of the layout.
 * @param boundaries The boundary boxes (outer connections drawn on a diagram of an element's inside).
 * @param covered The outer connections at least one connection realises.
 * @param edges The lines resolved for the current view.
 * @param drawnEdgeIds The ids of the lines the canvas draws (a note's leader to a connection needs one of them).
 * @param parents `{element id: parent id}` for the placed elements and their ancestors.
 * @param hidden The placed elements a view switch hides.
 * @param descriptions `{element id: description}` for the elements that have one (the table's Description column).
 * @param selection What is selected on the canvas, or null.
 * @param onSelect Selects an element, note or line.
 * @param stateMachinesOf The state machine diagrams that describe an element (the table's State machine diagrams column).
 * @param onOpenMachine Opens a state machine diagram from this diagram (the page asks before leaving unsaved changes).
 */
export function DiagramOutline({
  boxes, notes, boundaries, anchors, covered, edges, drawnEdgeIds, parents, hidden, descriptions, selection, onSelect, stateMachinesOf, onOpenMachine,
}: {
  boxes: EditorBox[];
  anchors: DiagramAnchor[];
  notes: EditorNote[];
  boundaries: EditorBoundary[];
  covered: ReadonlySet<string>;
  edges: DiagramViewEdge[];
  drawnEdgeIds: ReadonlySet<string>;
  parents: Record<string, string | null>;
  hidden: ReadonlySet<string>;
  descriptions: ReadonlyMap<string, string>;
  selection: GraphCanvasSelection | null;
  onSelect: (selection: GraphCanvasSelection) => void;
  stateMachinesOf: (elementId: string) => readonly ModelStateMachine[];
  onOpenMachine: (machine: ModelStateMachine) => void;
}) {
  const formatCode = useRecordCode();
  /** The element's state machine diagrams as buttons, or a dash for none. */
  const machineButtons = (elementId: string) => {
    const machines = stateMachinesOf(elementId);
    if (machines.length === 0) return "—";
    return (
      <span className="row" style={{ gap: "var(--space-1)", flexWrap: "wrap" }}>
        {machines.map((m) => (
          <button key={m.id} type="button" className="btn btn-sm" onClick={() => onOpenMachine(m)}>
            {formatCode.code(m.unique_code)} {m.name}
          </button>
        ))}
      </span>
    );
  };
  const tree = outlineTree(boxes, parents, hidden);
  const rows = connectionRows(edges, boxes, boundaries, anchors);
  const [elementView, setElementView] = useViewMode("architecture_outline_elements", "tree");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const branchIds = outlineBranchIds(tree);
  const expanded = new Set(branchIds.filter((id) => !collapsed.has(id)));
  const elements = elementRows(tree);
  const visibleBoxIds = new Set(boxes.filter((b) => !hidden.has(b.elementId)).map((b) => b.elementId));
  const hiddenCount = boxes.filter((b) => hidden.has(b.elementId)).length;
  const isSelected = (kind: GraphCanvasSelection["kind"], id: string) => selection?.kind === kind && selection.id === id;

  return (
    <DetailCard heading="Outline">
      <p className="text-muted">
        {outlineSize(tree)} {outlineSize(tree) === 1 ? "element" : "elements"}, {rows.length} {rows.length === 1 ? "line" : "lines"}
        {boundaries.length > 0 ? `, ${boundaries.length} outer ${boundaries.length === 1 ? "connection" : "connections"}` : ""}
        {notes.length > 0 ? `, ${notes.length} ${notes.length === 1 ? "note" : "notes"}` : ""}.
        {hiddenCount > 0 ? ` ${hiddenCount} hidden by view switches.` : ""}
      </p>

      <CollapsibleSection sectionKey="architecture_outline_elements" title="Elements" variant="plain" summary={String(elements.length)}>
        <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <ViewToggle mode={elementView === "list" ? "list" : "tree"} onChange={setElementView} showTilesOption={false} showTreeOption />
          {elementView !== "list" && branchIds.length > 0 && (
            <>
              <button type="button" className="btn btn-sm" onClick={() => setCollapsed(new Set())}>Expand all</button>
              <button type="button" className="btn btn-sm" onClick={() => setCollapsed(new Set(branchIds))}>Collapse all</button>
            </>
          )}
        </div>
        {elementView === "list" ? (
          elements.length === 0 ? (
            <p className="text-muted">No elements are shown on this diagram.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="table" aria-label="Elements">
                <thead>
                  <tr>
                    <th scope="col">Element</th>
                    <HelpHeader label="Type" help={ARCHITECTURE_HELP.elementType} />
                    <HelpHeader label="Parent" help={ARCHITECTURE_HELP.elementParent} />
                    <HelpHeader label="Display note" help={ARCHITECTURE_HELP.elementDisplayNote} />
                    <HelpHeader label="Description" help={ARCHITECTURE_HELP.elementDescription} />
                    <HelpHeader label="State machine diagrams" help={ARCHITECTURE_HELP.outlineStateMachines} />
                  </tr>
                </thead>
                <tbody>
                  {elements.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <button
                          type="button" className={isSelected("node", row.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                          aria-current={isSelected("node", row.id) ? "true" : undefined} onClick={() => onSelect({ kind: "node", id: row.id })}
                        >
                          {boxName(row.box)}
                        </button>
                      </td>
                      <td>{row.box.locked ? "—" : row.box.element_type_name}</td>
                      <td>{row.parent ?? "—"}</td>
                      <td style={{ whiteSpace: "pre-line" }}>{row.box.locked ? "—" : row.box.display_note || "—"}</td>
                      <td style={{ whiteSpace: "pre-line" }}>{row.box.locked ? "—" : descriptions.get(row.id) || "—"}</td>
                      <td>{row.box.locked ? "—" : machineButtons(row.id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <TreeView
            nodes={tree}
            nodeLabel={(node) => boxName(node.box)}
            emptyText="No elements are shown on this diagram."
            expanded={expanded}
            onToggle={(id, open) => setCollapsed((current) => {
              const next = new Set(current);
              if (open) next.delete(id);
              else next.add(id);
              return next;
            })}
            renderNode={(node) => (
              <span className="row" style={{ gap: "var(--space-1)", flexWrap: "wrap" }}>
                <button
                  type="button" className={isSelected("node", node.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                  aria-current={isSelected("node", node.id) ? "true" : undefined} onClick={() => onSelect({ kind: "node", id: node.id })}
                >
                  {boxName(node.box)}
                  {!node.box.locked && <span className="text-muted"> · {node.box.element_type_name}</span>}
                </button>
                {!node.box.locked && stateMachinesOf(node.id).length > 0 && machineButtons(node.id)}
              </span>
            )}
          />
        )}
      </CollapsibleSection>

      {boundaries.length > 0 && (
        <CollapsibleSection sectionKey="architecture_outline_outer" title="Outer connections" help={ARCHITECTURE_HELP.outerConnections} variant="plain" summary={String(boundaries.length)}>
          <div style={{ overflowX: "auto" }}>
            <table className="table" aria-label="Outer connections">
              <thead>
                <tr>
                  <th scope="col">Connection</th>
                  <th scope="col">Outside element</th>
                  <HelpHeader label="Direction" help={ARCHITECTURE_HELP.outlineDirection} />
                  <HelpHeader label="Coverage" help={ARCHITECTURE_HELP.outlineCoverage} />
                </tr>
              </thead>
              <tbody>
                {boundaries.map((b) => (
                  <tr key={b.connectionId}>
                    <td>
                      <button
                        type="button" className={isSelected("node", boundaryNodeId(b.connectionId)) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                        aria-current={isSelected("node", boundaryNodeId(b.connectionId)) ? "true" : undefined}
                        onClick={() => onSelect({ kind: "node", id: boundaryNodeId(b.connectionId) })}
                      >
                        {b.connection_code}
                      </button>
                    </td>
                    <td>{boundaryOutsideName(b)}</td>
                    <td>{BOUNDARY_SHAPE_LABEL[b.shape]}</td>
                    <td>{covered.has(b.connectionId) ? "Covered" : "Not covered"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

      <NotesOutlineSection
        notes={notes} sectionKey="architecture_outline_notes" help={ARCHITECTURE_HELP.diagramNotes} selection={selection} onSelect={onSelect}
        pointsAt={(l) => leaderSummary(l, boxes, edges, leaderIsDrawn(l, visibleBoxIds, edges, drawnEdgeIds))}
      />

      <CollapsibleSection sectionKey="architecture_outline_lines" title="Lines" variant="plain" summary={String(rows.length)}>
        {rows.length === 0 ? (
          <p className="text-muted">No lines are shown on this diagram.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" aria-label="Lines">
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <HelpHeader label="Direction" help={ARCHITECTURE_HELP.outlineDirection} />
                  <HelpHeader label="Type" help={ARCHITECTURE_HELP.connectionType} />
                  <HelpHeader label="Connections" help={ARCHITECTURE_HELP.outlineConnections} />
                  <HelpHeader label="Route" help={ARCHITECTURE_HELP.outlineRoute} />
                  <HelpHeader label="Vertices" help={ARCHITECTURE_HELP.lineVertices} />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <button
                        type="button" className={isSelected("edge", row.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                        aria-current={isSelected("edge", row.id) ? "true" : undefined}
                        aria-label={`Line from ${row.from} to ${row.to}`} onClick={() => onSelect({ kind: "edge", id: row.id })}
                      >
                        {row.from}
                      </button>
                    </td>
                    <td>{row.to}</td>
                    <td>{row.twoWay ? "Two-way" : "One-way"}</td>
                    <td>{row.detail}</td>
                    <td>{row.count}</td>
                    <td>
                      {ROUTE_LABEL[row.route]}
                      {row.via.length > 0 && <span className="text-muted"> via {row.via.join(", ")}</span>}
                    </td>
                    <td>{row.vertices || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CollapsibleSection>
    </DetailCard>
  );
}
