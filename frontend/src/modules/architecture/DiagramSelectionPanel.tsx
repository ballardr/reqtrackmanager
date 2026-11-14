/**
 * Module: modules/architecture/DiagramSelectionPanel
 *
 * The editor's "Selection" card: what the selected box, note or line is and what can be done with it.
 * - A box: open the element, edit it in the shared element form (`onEditElement`), open its inside as a diagram of its
 *   own, take it off this diagram (the element is not changed), or delete the element from the model (a separate,
 *   confirmed action that needs the code typed). Its ports are listed with the shared `PortList`; each change is stored at
 *   once, as on the element's page. Its project components (the shared `RecordPlacements`, also saved at once) are set
 *   here too; a box shared from another owner shows none, since a component belongs to one project and its own
 *   project's tree is not disclosed to another.
 * - A note (an annotation): edit its text (applied when the field loses focus, as one undo step), its tone, what its leader
 *   line points at (a box or connection from a list, or a spot on the canvas) and the arrowhead, or remove it
 *   (`DiagramNoteEditor`).
 * - A line: the connections behind it (a rolled-up or merged line stands for several), for a bridged line the hidden
 *   elements it passes through, and the attach points of its two ends (Automatic or one of the box's eight points), the
 *   keyboard route to dragging a line's end. Each connection of this project has an Edit button that opens the shared
 *   connection form (`onEditConnection`); one shared from another project is listed without it.
 * - A box can also start a connection to another box from a list ("Connect to"), the keyboard route to what dragging a
 *   line between two boxes does.
 * - A boundary box (an outer connection of the diagram's element): the connection, the element outside, its direction and
 *   whether it is covered, the connections that realise it, and a "Connect to" list of the inner elements that starts a
 *   realising connection (the keyboard route to drawing a line to the box).
 * - A line that stands for one connection also offers "Realises": the outer connections (the boundary boxes on this diagram)
 *   it is marked as realising, each removable, and a list to add another; the change is stored at once.
 * A box the viewer cannot read shows its code only and offers no actions beyond removing it from the diagram.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { ActivityNote } from "../../components/ActivityNote";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { FieldCaption } from "../../components/FieldHelp";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordPlacements } from "../../components/RecordPlacements";
import { Tooltip } from "../../components/Tooltip";
import { toErrorMessage } from "../../context/ToastContext";
import { useRecordCode } from "../../hooks/useRecordCode";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, lineAttachPoints, type AttachPoint } from "../../components/graphAttachPoints";
import {
  BOUNDARY_NODE_PREFIX, BOUNDARY_SHAPE_LABEL, NOTE_NODE_PREFIX, anchorOf, boundaryOutsideName, leaderIsDrawn, type EditorBoundary,
  type EditorBox, type EditorNote, type NoteLeaderTarget,
} from "./diagramEditorModel";
import { boxName } from "./diagramOutlineModel";
import { DiagramNoteEditor } from "./DiagramNoteEditor";
import { ARCHITECTURE_HELP } from "./help";
import { PortList } from "./PortList";
import type {
  ArchitectureConnection, ArchitectureElement, ConnectionRef, ConnectionType, DiagramAnchor, DiagramViewEdge, NoteTone, PortValues,
} from "./types";

/**
 * @param projectId The diagram's project, for the links.
 * @param selection What is selected on the canvas, or null.
 * @param boxes Every box of the layout.
 * @param notes Every note of the layout.
 * @param boundaries Every boundary box of the layout.
 * @param connectionsById The project's connections as the model lists them (a boundary box's realising connections are named from it).
 * @param realisedBy `{outer connection id: the connections that realise it}`.
 * @param edges The resolved lines.
 * @param anchors The attach points chosen for lines.
 * @param hidden The boxes a view switch hides (not offered as the other end of a connection).
 * @param editable False hides every action that changes the diagram or the model.
 * @param elements The elements the editor knows (their ports are listed for a selected box).
 * @param connectionTypes The connection types a port may name.
 * @param onEditElement Opens the element's edit form.
 * @param onEditConnection Opens a connection's edit form.
 * @param onAddPort Adds a port to an element.
 * @param onChangePort Changes one field of an element's port.
 * @param onRemovePort Removes an element's port.
 * @param onRemoveBox Takes an element off the diagram.
 * @param onConnect Starts a connection from a box to the element with the given id.
 * @param onOpenInside Opens (or creates) the diagram of the element's inside.
 * @param onDeleteElement Deletes the element from the model.
 * @param onAnchorChange Sets the attach point of one or both ends of a line (`null` makes an end automatic).
 * @param drawnEdgeIds The ids of the lines the canvas draws (a note's leader to a connection needs one of them).
 * @param pickingSpot The key of the note waiting for a click on the canvas to place its leader's end, or null.
 * @param onEditNote Sets a note's text.
 * @param onNoteTone Sets a note's tone.
 * @param onNoteArrow Sets whether a note's leader ends in an arrowhead.
 * @param onNotePointAt Points a note's leader at a box or connection, or removes it.
 * @param onPickSpot Starts (true) or cancels (false) waiting for the canvas click that places a note's leader end.
 * @param onRemoveNote Removes a note.
 * @param onRemoveBoundary Takes a boundary box off the diagram (the connection is not changed).
 * @param onConnectBoundary Starts a connection between an inner element and the element outside a boundary box.
 * @param onSetRealises Sets the outer connections a connection realises (stored at once; may reject).
 */
export function DiagramSelectionPanel({
  projectId, selection, boxes, notes, edges, anchors, hidden, editable, onRemoveBox, onConnect, onOpenInside, onDeleteElement,
  onAnchorChange, drawnEdgeIds, pickingSpot, onEditNote, onNoteTone, onNoteArrow, onNotePointAt, onPickSpot, onRemoveNote, elements, connectionTypes, onEditElement, onEditConnection, onAddPort, onChangePort, onRemovePort,
  boundaries, connectionsById, realisedBy, onRemoveBoundary, onConnectBoundary, onSetRealises,
}: {
  projectId: string;
  selection: GraphCanvasSelection | null;
  boxes: EditorBox[];
  notes: EditorNote[];
  boundaries: EditorBoundary[];
  connectionsById: ReadonlyMap<string, ArchitectureConnection>;
  realisedBy: ReadonlyMap<string, readonly string[]>;
  onRemoveBoundary: (box: EditorBoundary) => void;
  onConnectBoundary: (box: EditorBoundary, elementId: string) => void;
  onSetRealises: (connection: ArchitectureConnection, outerIds: string[]) => Promise<void>;
  edges: DiagramViewEdge[];
  anchors: DiagramAnchor[];
  hidden: ReadonlySet<string>;
  editable: boolean;
  onRemoveBox: (box: EditorBox) => void;
  onConnect: (box: EditorBox, targetId: string) => void;
  onOpenInside: (box: EditorBox) => void;
  onDeleteElement: (box: EditorBox) => void;
  onAnchorChange: (edge: DiagramViewEdge, change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null }) => void;
  drawnEdgeIds: ReadonlySet<string>;
  pickingSpot: string | null;
  onEditNote: (key: string, text: string) => void;
  onNoteTone: (key: string, tone: NoteTone) => void;
  onNoteArrow: (key: string, arrow: boolean) => void;
  onNotePointAt: (key: string, target: NoteLeaderTarget) => void;
  onPickSpot: (key: string, picking: boolean) => void;
  onRemoveNote: (key: string) => void;
  elements: ArchitectureElement[];
  connectionTypes: ConnectionType[];
  onEditElement: (box: EditorBox) => void;
  onEditConnection: (connection: ArchitectureConnection) => void;
  onAddPort: (elementId: string, values: PortValues) => Promise<void>;
  onChangePort: (elementId: string, portId: string, change: Partial<PortValues>) => Promise<void>;
  onRemovePort: (elementId: string, portId: string) => Promise<void>;
}) {
  const formatCode = useRecordCode();
  const [deleting, setDeleting] = useState<EditorBox | null>(null);
  const base = `/projects/${projectId}/modules/architecture`;

  const noteKey = selection?.kind === "node" && selection.id.startsWith(NOTE_NODE_PREFIX) ? selection.id.slice(NOTE_NODE_PREFIX.length) : null;
  const note = noteKey === null ? null : notes.find((n) => n.key === noteKey) ?? null;
  const boundaryKey = selection?.kind === "node" && selection.id.startsWith(BOUNDARY_NODE_PREFIX) ? selection.id.slice(BOUNDARY_NODE_PREFIX.length) : null;
  const boundary = boundaryKey === null ? null : boundaries.find((b) => b.connectionId === boundaryKey) ?? null;
  const box = selection?.kind === "node" && noteKey === null && boundaryKey === null ? boxes.find((b) => b.elementId === selection.id) ?? null : null;
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
        {!box.locked && box.display_note && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Display note" help={ARCHITECTURE_HELP.elementDisplayNote} />
            <ActivityNote text={box.display_note} />
          </div>
        )}
        {!box.locked && element?.description && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Description" help={ARCHITECTURE_HELP.elementDescription} />
            <ActivityNote text={element.description} />
          </div>
        )}
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
        {!box.locked && !box.shared && (
          <RecordPlacements
            key={box.elementId} projectId={projectId} artefactType="architecture_element" artefactId={box.elementId}
            captioned
          />
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
  } else if (boundary) {
    const realisers = (realisedBy.get(boundary.connectionId) ?? []).map((id) => connectionsById.get(id)).filter((c): c is ArchitectureConnection => c !== undefined);
    body = (
      <>
        <p>
          <strong>{boundary.connection_code}</strong>
          {!boundary.locked && boundary.type_name && <span className="text-muted"> · {boundary.type_name}</span>}
        </p>
        <p>
          Outside: {boundaryOutsideName(boundary)} <span className="text-muted">· {BOUNDARY_SHAPE_LABEL[boundary.shape]}</span>
        </p>
        <p>
          {realisers.length > 0 ? `Covered by ${realisers.length} ${realisers.length === 1 ? "connection" : "connections"}.` : "Not covered."}
        </p>
        {realisers.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
            {realisers.map((c) => (
              <li key={c.id}><Link to={`${base}/connections/${c.id}`}>{formatCode.code(c.unique_code, c.from_project_code)}</Link>{c.name ? ` ${c.name}` : ""}</li>
            ))}
          </ul>
        )}
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <Link className="btn btn-sm" to={`${base}/connections/${boundary.connectionId}`}>Open connection</Link>
          {editable && <button type="button" className="btn btn-sm" onClick={() => onRemoveBoundary(boundary)}>Remove from diagram</button>}
        </div>
        {editable && !boundary.locked && (
          <LabeledSelect
            label="Connect to" help={ARCHITECTURE_HELP.diagramBoundaryConnectTo} value="" placeholder="Choose an element…"
            options={boxes.filter((b) => !b.locked && !hidden.has(b.elementId)).map((b) => ({ value: b.elementId, label: boxName(b) }))}
            onChange={(elementId) => { if (elementId) onConnectBoundary(boundary, elementId); }}
          />
        )}
      </>
    );
  } else if (note) {
    const drawnBoxes = boxes.filter((b) => !hidden.has(b.elementId));
    const drawnConnections = new Map<string, ArchitectureConnection>();
    for (const e of edges) if (drawnEdgeIds.has(e.id)) for (const c of e.connections) drawnConnections.set(c.id, c);
    body = (
      <DiagramNoteEditor
        key={note.key} note={note} editable={editable} boxes={drawnBoxes} connections={[...drawnConnections.values()]}
        drawn={leaderIsDrawn(note, new Set(drawnBoxes.map((b) => b.elementId)), edges, drawnEdgeIds)} picking={pickingSpot === note.key}
        onText={(text) => onEditNote(note.key, text)} onTone={(tone) => onNoteTone(note.key, tone)}
        onArrow={(arrow) => onNoteArrow(note.key, arrow)} onPointAt={(target) => onNotePointAt(note.key, target)}
        onPickSpot={(picking) => onPickSpot(note.key, picking)} onRemove={() => onRemoveNote(note.key)}
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
            <tr><th scope="col">Code</th><th scope="col">Type</th><th scope="col">From</th><th scope="col">To</th>{editable && <th scope="col"><span className="sr-only">Actions</span></th>}</tr>
          </thead>
          <tbody>
            {edge.connections.map((c) => (
              <tr key={c.id}>
                <td><Link to={`${base}/connections/${c.id}`}>{formatCode.code(c.unique_code, c.from_project_code)}</Link></td>
                <td>{c.connection_type_name}{c.protocol ? ` · ${c.protocol}` : ""}</td>
                <td>{c.source_element_name || c.source_element_code}</td>
                <td>{c.target_element_name || c.target_element_code}</td>
                {editable && (
                  <td>
                    {c.project_id === projectId && (
                      <button type="button" className="btn btn-sm" aria-label={`Edit ${c.unique_code}`} onClick={() => onEditConnection(c)}>Edit</button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {editable && !edge.source_is_boundary && !edge.target_is_boundary && (
          <LineEnds edge={edge} boxes={boxes} anchors={anchors} onChange={(change) => onAnchorChange(edge, change)} />
        )}
        {editable && edge.connections.length === 1 && boundaries.length > 0 && (
          <RealisesControl connection={edge.connections[0]} boundaries={boundaries} onSet={onSetRealises} />
        )}
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
 * The outer connections a connection is marked as realising, each removable, and a list to add another from the boundary
 * boxes of the diagram. A refusal from the server (the connection does not lie inside that interface) is shown here.
 */
function RealisesControl({
  connection, boundaries, onSet,
}: {
  connection: ArchitectureConnection;
  boundaries: EditorBoundary[];
  onSet: (connection: ArchitectureConnection, outerIds: string[]) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const current: ConnectionRef[] = connection.realises;
  const change = async (ids: string[]) => {
    setError(null);
    try {
      await onSet(connection, ids);
    } catch (err) {
      setError(toErrorMessage(err, "Could not change what this connection realises."));
    }
  };
  const offered = boundaries.filter((b) => b.connectionId !== connection.id && !current.some((c) => c.id === b.connectionId));
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label="Realises" help={ARCHITECTURE_HELP.diagramRealises} />
      {current.length === 0 ? <p className="text-muted">No outer connection.</p> : (
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
          {current.map((c) => (
            <li key={c.id} className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
              <span>{c.unique_code}{c.name ? ` ${c.name}` : ""}</span>
              <button
                type="button" className="btn btn-sm" aria-label={`Stop realising ${c.unique_code}`}
                onClick={() => void change(current.filter((x) => x.id !== c.id).map((x) => x.id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {offered.length > 0 && (
        <LabeledSelect
          label="Add outer connection" helpNotNeeded value="" placeholder="Choose a connection…"
          options={offered.map((b) => ({ value: b.connectionId, label: `${b.connection_code} · ${boundaryOutsideName(b)}` }))}
          onChange={(id) => { if (id) void change([...current.map((c) => c.id), id]); }}
        />
      )}
      {error && <p role="alert" style={{ color: "var(--color-danger)" }}>{error}</p>}
    </div>
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
