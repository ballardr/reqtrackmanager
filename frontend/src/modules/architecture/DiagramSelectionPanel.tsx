/**
 * Module: modules/architecture/DiagramSelectionPanel
 *
 * The editor's "Selection" card: what the selected box, note or line is and what can be done with it.
 * - A box: open the element, open its inside as a diagram of its own, take it off this diagram (the element is not
 *   changed), or delete the element from the model (a separate, confirmed action that needs the code typed).
 * - A note: edit its text (applied when the field loses focus, as one undo step) or remove it.
 * - A line: the connections behind it (a rolled-up or merged line stands for several) and, for a bridged line, the hidden
 *   elements it passes through.
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
import { LabeledSelect } from "../../components/LabeledSelect";
import { useRecordCode } from "../../hooks/useRecordCode";
import { NOTE_NODE_PREFIX, type EditorBox, type EditorNote } from "./diagramEditorModel";
import { boxName } from "./diagramOutlineModel";
import { ARCHITECTURE_HELP } from "./help";
import type { DiagramViewEdge } from "./types";

/**
 * @param projectId The diagram's project, for the links.
 * @param selection What is selected on the canvas, or null.
 * @param boxes Every box of the layout.
 * @param notes Every note of the layout.
 * @param edges The resolved lines.
 * @param hidden The boxes a view switch hides (not offered as the other end of a connection).
 * @param editable False hides every action that changes the diagram or the model.
 * @param onRemoveBox Takes an element off the diagram.
 * @param onConnect Starts a connection from a box to the element with the given id.
 * @param onOpenInside Opens (or creates) the diagram of the element's inside.
 * @param onDeleteElement Deletes the element from the model.
 * @param onEditNote Sets a note's text.
 * @param onRemoveNote Removes a note.
 */
export function DiagramSelectionPanel({
  projectId, selection, boxes, notes, edges, hidden, editable, onRemoveBox, onConnect, onOpenInside, onDeleteElement, onEditNote, onRemoveNote,
}: {
  projectId: string;
  selection: GraphCanvasSelection | null;
  boxes: EditorBox[];
  notes: EditorNote[];
  edges: DiagramViewEdge[];
  hidden: ReadonlySet<string>;
  editable: boolean;
  onRemoveBox: (box: EditorBox) => void;
  onConnect: (box: EditorBox, targetId: string) => void;
  onOpenInside: (box: EditorBox) => void;
  onDeleteElement: (box: EditorBox) => void;
  onEditNote: (key: string, text: string) => void;
  onRemoveNote: (key: string) => void;
}) {
  const formatCode = useRecordCode();
  const [deleting, setDeleting] = useState<EditorBox | null>(null);
  const base = `/projects/${projectId}/modules/architecture`;

  const noteKey = selection?.kind === "node" && selection.id.startsWith(NOTE_NODE_PREFIX) ? selection.id.slice(NOTE_NODE_PREFIX.length) : null;
  const note = noteKey === null ? null : notes.find((n) => n.key === noteKey) ?? null;
  const box = selection?.kind === "node" && noteKey === null ? boxes.find((b) => b.elementId === selection.id) ?? null : null;
  const edge = selection?.kind === "edge" ? edges.find((e) => e.id === selection.id) ?? null : null;

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
          {!box.locked && <button type="button" className="btn btn-sm" onClick={() => onOpenInside(box)}>Open inside as diagram</button>}
          {editable && <button type="button" className="btn btn-sm" onClick={() => onRemoveBox(box)}>Remove from diagram</button>}
          {editable && !box.locked && !box.shared && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setDeleting(box)}>Delete element…</button>
          )}
        </div>
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
