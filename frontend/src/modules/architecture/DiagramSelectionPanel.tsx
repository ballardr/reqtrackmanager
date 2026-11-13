/**
 * Module: modules/architecture/DiagramSelectionPanel
 *
 * The editor's "Selection" card: what the selected box, note or line is and what can be done with it.
 * - A box: open the element, edit it in the shared element form (`onEditElement`), open its inside as a diagram of its
 *   own, take it off this diagram (the element is not changed), or delete the element from the model (a separate,
 *   confirmed action that needs the code typed). Its ports are listed with the shared `PortList`; each change is stored at
 *   once, as on the element's page.
 * - A note: edit its text (applied when the field loses focus, as one undo step) or remove it.
 * - A line: the connections behind it (a rolled-up or merged line stands for several), for a bridged line the hidden
 *   elements it passes through, and the attach points of its two ends (Automatic or one of the box's eight points), the
 *   keyboard route to dragging a line's end.
 * - A box can also start a connection to another box from a list ("Connect to"), the keyboard route to what dragging a
 *   line between two boxes does.
 * A box the viewer cannot read shows its code only and offers no actions beyond removing it from the diagram.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { TextAreaField } from "../../components/FormFields";
import { FieldCaption } from "../../components/FieldHelp";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Tooltip } from "../../components/Tooltip";
import { useRecordCode } from "../../hooks/useRecordCode";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, lineAttachPoints, type AttachPoint } from "../../components/graphAttachPoints";
import { NOTE_NODE_PREFIX, anchorOf, type EditorBox, type EditorNote } from "./diagramEditorModel";
import { boxName } from "./diagramOutlineModel";
import { ARCHITECTURE_HELP } from "./help";
import { PortList } from "./PortList";
import type { ArchitectureElement, ConnectionType, DiagramAnchor, DiagramViewEdge, PortValues } from "./types";

/**
 * @param projectId The diagram's project, for the links.
 * @param selection What is selected on the canvas, or null.
 * @param boxes Every box of the layout.
 * @param notes Every note of the layout.
 * @param edges The resolved lines.
 * @param anchors The attach points chosen for lines.
 * @param hidden The boxes a view switch hides (not offered as the other end of a connection).
 * @param editable False hides every action that changes the diagram or the model.
 * @param elements The elements the editor knows (their ports are listed for a selected box).
 * @param connectionTypes The connection types a port may name.
 * @param onEditElement Opens the element's edit form.
 * @param onAddPort Adds a port to an element.
 * @param onChangePort Changes one field of an element's port.
 * @param onRemovePort Removes an element's port.
 * @param onRemoveBox Takes an element off the diagram.
 * @param onConnect Starts a connection from a box to the element with the given id.
 * @param onOpenInside Opens (or creates) the diagram of the element's inside.
 * @param onDeleteElement Deletes the element from the model.
 * @param onAnchorChange Sets the attach point of one or both ends of a line (`null` makes an end automatic).
 * @param onEditNote Sets a note's text.
 * @param onRemoveNote Removes a note.
 */
export function DiagramSelectionPanel({
  projectId, selection, boxes, notes, edges, anchors, hidden, editable, onRemoveBox, onConnect, onOpenInside, onDeleteElement,
  onAnchorChange, onEditNote, onRemoveNote, elements, connectionTypes, onEditElement, onAddPort, onChangePort, onRemovePort,
}: {
  projectId: string;
  selection: GraphCanvasSelection | null;
  boxes: EditorBox[];
  notes: EditorNote[];
  edges: DiagramViewEdge[];
  anchors: DiagramAnchor[];
  hidden: ReadonlySet<string>;
  editable: boolean;
  onRemoveBox: (box: EditorBox) => void;
  onConnect: (box: EditorBox, targetId: string) => void;
  onOpenInside: (box: EditorBox) => void;
  onDeleteElement: (box: EditorBox) => void;
  onAnchorChange: (edge: DiagramViewEdge, change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null }) => void;
  onEditNote: (key: string, text: string) => void;
  onRemoveNote: (key: string) => void;
  elements: ArchitectureElement[];
  connectionTypes: ConnectionType[];
  onEditElement: (box: EditorBox) => void;
  onAddPort: (elementId: string, values: PortValues) => Promise<void>;
  onChangePort: (elementId: string, portId: string, change: Partial<PortValues>) => Promise<void>;
  onRemovePort: (elementId: string, portId: string) => Promise<void>;
}) {
  const formatCode = useRecordCode();
  const [deleting, setDeleting] = useState<EditorBox | null>(null);
  const base = `/projects/${projectId}/modules/architecture`;

  const noteKey = selection?.kind === "node" && selection.id.startsWith(NOTE_NODE_PREFIX) ? selection.id.slice(NOTE_NODE_PREFIX.length) : null;
  const note = noteKey === null ? null : notes.find((n) => n.key === noteKey) ?? null;
  const box = selection?.kind === "node" && noteKey === null ? boxes.find((b) => b.elementId === selection.id) ?? null : null;
  const edge = selection?.kind === "edge" ? edges.find((e) => e.id === selection.id) ?? null : null;

  const element = box ? elements.find((e) => e.id === box.elementId) ?? null : null;

  let body;
  if (box) {
    body = (
      <>
        <p>
          <strong>{box.locked ? box.unique_code : `${box.unique_code} ${box.name}`}</strong>
          {!box.locked && <span className="text-muted"> · {box.element_type_name}</span>}
        </p>
        <div className="row" style={{ gap: "var(--space-2)" }}>
          {!box.locked && <Link className="btn btn-sm" to={`${base}/elements/${box.elementId}`}>Open element</Link>}
          {!box.locked && (
            <Tooltip label={ARCHITECTURE_HELP.openInside} wrap>
              <button type="button" className="btn btn-sm" onClick={() => onOpenInside(box)}>Open inside as diagram</button>
            </Tooltip>
          )}
          {editable && !box.locked && !box.shared && <button type="button" className="btn btn-sm" onClick={() => onEditElement(box)}>Edit element</button>}
          {editable && <button type="button" className="btn btn-sm" onClick={() => onRemoveBox(box)}>Remove from diagram</button>}
          {editable && !box.locked && !box.shared && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setDeleting(box)}>Delete element…</button>
          )}
        </div>
        {element && !box.locked && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Ports" help={ARCHITECTURE_HELP.elementPorts} />
            <PortList
              ports={element.ports} connectionTypes={connectionTypes} readOnly={!editable || box.shared || element.is_archived}
              onAdd={(values) => onAddPort(element.id, values)} onChange={(id, change) => onChangePort(element.id, id, change)}
              onRemove={(id) => onRemovePort(element.id, id)}
            />
          </div>
        )}
        {editable && !box.locked && (
          <LabeledSelect
            label="Connect to" help={ARCHITECTURE_HELP.diagramConnectTo} value="" placeholder="Choose an element…"
            options={boxes.filter((b) => b.elementId !== box.elementId && !b.locked && !hidden.has(b.elementId))
              .map((b) => ({ value: b.elementId, label: boxName(b) }))}
            onChange={(targetId) => { if (targetId) onConnect(box, targetId); }}
          />
        )}
      </>
    );
  } else if (note) {
    body = (
      <NoteEditor
        key={note.key} note={note} editable={editable}
        onCommit={(text) => onEditNote(note.key, text)} onRemove={() => onRemoveNote(note.key)}
      />
    );
  } else if (edge) {
    body = (
      <>
        <p>
          {edge.count > 1 ? `${edge.count} connections` : "1 connection"}
          {edge.bridged ? " (bridged across hidden elements)" : edge.rolled_up ? " (rolled up to the placed parents)" : ""}
        </p>
        {edge.hops.length > 0 && (
          <p className="text-muted">Passes through: {edge.hops.map((h) => `${h.unique_code} ${h.name}`).join(", ")}</p>
        )}
        <table className="table">
          <thead>
            <tr><th scope="col">Code</th><th scope="col">Type</th><th scope="col">From</th><th scope="col">To</th></tr>
          </thead>
          <tbody>
            {edge.connections.map((c) => (
              <tr key={c.id}>
                <td><Link to={`${base}/connections/${c.id}`}>{formatCode.code(c.unique_code, c.from_project_code)}</Link></td>
                <td>{c.connection_type_name}{c.protocol ? ` · ${c.protocol}` : ""}</td>
                <td>{c.source_element_name || c.source_element_code}</td>
                <td>{c.target_element_name || c.target_element_code}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {editable && <LineEnds edge={edge} boxes={boxes} anchors={anchors} onChange={(change) => onAnchorChange(edge, change)} />}
      </>
    );
  } else {
    body = <p className="text-muted">Select a box, note or line to see its details.</p>;
  }

  return (
    <DetailCard heading="Selection">
      {body}
      {deleting && (
        <ConfirmDialog
          title="Delete this element permanently?"
          message={`${deleting.unique_code} ${deleting.name} is removed from the model, from every diagram and from its connections. This cannot be undone. An element that other records use cannot be deleted; retire it instead. To only take it off this diagram, use Remove from diagram.`}
          confirmLabel="Delete" requireTypedText={deleting.unique_code}
          onConfirm={() => { onDeleteElement(deleting); setDeleting(null); }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </DetailCard>
  );
}

/**
 * The attach points of a line's two ends, as two lists: Automatic (with the point it would use) or one of the box's eight
 * points. A line whose end is not a box of the layout offers nothing.
 */
function LineEnds({
  edge, boxes, anchors, onChange,
}: {
  edge: DiagramViewEdge;
  boxes: EditorBox[];
  anchors: DiagramAnchor[];
  onChange: (change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null }) => void;
}) {
  const from = boxes.find((b) => b.elementId === edge.source_element_id);
  const to = boxes.find((b) => b.elementId === edge.target_element_id);
  if (!from || !to) return null;
  const chosen = anchorOf(anchors, edge.source_element_id, edge.target_element_id);
  // What Automatic would give each end with the other end as it is now.
  const sourceAutomatic = lineAttachPoints(from, to, null, chosen.targetPoint)[0];
  const targetAutomatic = lineAttachPoints(from, to, chosen.sourcePoint, null)[1];
  const options = (automatic: AttachPoint) => [
    { value: "", label: `Automatic (${ATTACH_POINT_LABEL[automatic]})` },
    ...ATTACH_POINTS.map((p) => ({ value: p, label: ATTACH_POINT_LABEL[p] })),
  ];
  const parse = (value: string): AttachPoint | null => (ATTACH_POINTS.find((p) => p === value) ?? null);
  return (
    <>
      <LabeledSelect
        label="Line starts at" help={ARCHITECTURE_HELP.diagramLineFrom} placeholder={null} value={chosen.sourcePoint ?? ""}
        options={options(sourceAutomatic)} onChange={(value) => onChange({ sourcePoint: parse(value) })}
      />
      <LabeledSelect
        label="Line ends at" help={ARCHITECTURE_HELP.diagramLineTo} placeholder={null} value={chosen.targetPoint ?? ""}
        options={options(targetAutomatic)} onChange={(value) => onChange({ targetPoint: parse(value) })}
      />
    </>
  );
}

/** A note's text field: edited locally and applied on blur, so one edit is one undo step and not one per keystroke. */
function NoteEditor({
  note, editable, onCommit, onRemove,
}: { note: EditorNote; editable: boolean; onCommit: (text: string) => void; onRemove: () => void }) {
  const [draft, setDraft] = useState(note.text);
  return (
    <div className="stack" onBlur={() => { if (draft !== note.text) onCommit(draft); }}>
      <TextAreaField helpNotNeeded label="Note text" value={draft} onChange={setDraft} disabled={!editable} />
      {editable && <button type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }} onClick={onRemove}>Remove note</button>}
    </div>
  );
}
