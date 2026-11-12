/**
 * Module: modules/architecture/DiagramOutline
 *
 * The editor's "Outline" card: the text alternative to the canvas, with the same content in a form a keyboard or screen
 * reader can use. It lists the elements shown as a tree (nested by their parent among the elements placed), the notes, and the
 * lines drawn as a table with their ends, direction, type, count and, for a bridged line, the hidden elements it passes
 * through.
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
 * - Built on the shared `TreeView` shell and the shared table styles; every row is a real button, so the whole outline is
 *   operable from the keyboard.
 */
import { DetailCard } from "../../components/DetailCard";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { TreeView } from "../../components/TreeView";
import { NOTE_NODE_PREFIX, type EditorBox, type EditorNote } from "./diagramEditorModel";
import { boxName, connectionRows, outlineSize, outlineTree, type ConnectionRow } from "./diagramOutlineModel";
import type { DiagramViewEdge } from "./types";

const ROUTE_LABEL: Record<ConnectionRow["route"], string> = { direct: "Direct", rolled_up: "Rolled up", bridged: "Bridged" };

/** A note's text shortened for a list. */
function noteSummary(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (!flat) return "Empty note";
  return flat.length > 60 ? `${flat.slice(0, 59)}…` : flat;
}

/**
 * @param boxes Every box of the layout.
 * @param notes Every note of the layout.
 * @param edges The lines resolved for the current view.
 * @param parents `{element id: parent id}` for the placed elements and their ancestors.
 * @param hidden The placed elements a view switch hides.
 * @param selection What is selected on the canvas, or null.
 * @param onSelect Selects an element, note or line.
 */
export function DiagramOutline({
  boxes, notes, edges, parents, hidden, selection, onSelect,
}: {
  boxes: EditorBox[];
  notes: EditorNote[];
  edges: DiagramViewEdge[];
  parents: Record<string, string | null>;
  hidden: ReadonlySet<string>;
  selection: GraphCanvasSelection | null;
  onSelect: (selection: GraphCanvasSelection) => void;
}) {
  const tree = outlineTree(boxes, parents, hidden);
  const rows = connectionRows(edges, boxes);
  const hiddenCount = boxes.filter((b) => hidden.has(b.elementId)).length;
  const isSelected = (kind: GraphCanvasSelection["kind"], id: string) => selection?.kind === kind && selection.id === id;

  return (
    <DetailCard heading="Outline">
      <p className="text-muted">
        {outlineSize(tree)} {outlineSize(tree) === 1 ? "element" : "elements"}, {rows.length} {rows.length === 1 ? "line" : "lines"}
        {notes.length > 0 ? `, ${notes.length} ${notes.length === 1 ? "note" : "notes"}` : ""}.
        {hiddenCount > 0 ? ` ${hiddenCount} hidden by view switches.` : ""}
      </p>

      <section className="stack" aria-label="Elements">
        <h3 className="detail-card__title">Elements</h3>
        <TreeView
          nodes={tree}
          nodeLabel={(node) => boxName(node.box)}
          emptyText="No elements are shown on this diagram."
          renderNode={(node) => (
            <button
              type="button" className={isSelected("node", node.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
              aria-current={isSelected("node", node.id) ? "true" : undefined} onClick={() => onSelect({ kind: "node", id: node.id })}
            >
              {boxName(node.box)}
              {!node.box.locked && <span className="text-muted"> · {node.box.element_type_name}</span>}
            </button>
          )}
        />
      </section>

      {notes.length > 0 && (
        <section className="stack" aria-label="Notes">
          <h3 className="detail-card__title">Notes</h3>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {notes.map((n) => (
              <li key={n.key}>
                <button
                  type="button" className={isSelected("node", NOTE_NODE_PREFIX + n.key) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                  aria-current={isSelected("node", NOTE_NODE_PREFIX + n.key) ? "true" : undefined}
                  onClick={() => onSelect({ kind: "node", id: NOTE_NODE_PREFIX + n.key })}
                >
                  {noteSummary(n.text)}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="stack" aria-label="Lines">
        <h3 className="detail-card__title">Lines</h3>
        {rows.length === 0 ? (
          <p className="text-muted">No lines are shown on this diagram.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Type</th>
                  <th scope="col">Connections</th>
                  <th scope="col">Route</th>
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </DetailCard>
  );
}
