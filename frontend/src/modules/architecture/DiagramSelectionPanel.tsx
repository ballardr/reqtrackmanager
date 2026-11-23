/**
 * Module: modules/architecture/DiagramSelectionPanel
 *
 * The editor's "Selection" card: what the selected box, note or line is and what can be done with it.
 * - A box: open the element, edit it in place (`ElementSelectionFields`, the shared element field group), open its inside as a
 *   diagram of its own, take it off this diagram (the element is not changed), or delete the element from the model (a separate,
 *   confirmed action that needs the code typed). A box that is shared, locked or on a read-only diagram shows its description
 *   and display note as text instead. Its ports are listed with the shared `PortList`; each change is stored at
 *   once, as on the element's page. Its project components (the shared `RecordTags` chip row, also saved at once) are set
 *   here too; a box shared from another owner shows none, since a component belongs to one project and its own
 *   project's tree is not disclosed to another.
 * - A note (an annotation): edit its text (applied when the field loses focus, as one undo step) and its tone, list its leader
 *   lines and add one, or remove it (`DiagramNoteEditor`).
 * - A leader (a note's line to what it describes): what it points at (a box or connection from a list, or a spot with X and Y),
 *   where it starts, how its two ends look and its vertices, or remove it; the note stays (`DiagramLeaderEditor`).
 * - A line: the connections behind it (a rolled-up or merged line stands for several), for a bridged line the hidden
 *   elements it passes through, and the attach points of its two ends (Automatic or one of the box's eight points), the
 *   keyboard route to dragging a line's end. A line that stands for one connection of this project edits it in place
 *   (`ConnectionSelectionFields`, the shared connection field group); a line that stands for several lists them as compact rows
 *   (`ConnectionSummaryList`); choosing a row (the chosen connection, kept by the page) shows that connection under a heading
 *   with Back, Open and (for one of this project) its fields edited in place, the line's own attach point and vertex fields
 *   staying below it; Escape on the card, outside a text field, goes back. Each row also has Open (the record's page) and Edit
 *   (the shared connection form, `onEditConnection`); one shared from another project is listed without Edit.
 * - A box can also start a connection to another box from a list ("Connect to"), the keyboard route to what dragging a
 *   line between two boxes does.
 * - A boundary box (an outer connection of the diagram's element): the connection, the element outside, its direction and
 *   whether it is covered, the connections that realise it, and a "Connect to" list of the inner elements that starts a
 *   realising connection (the keyboard route to drawing a line to the box).
 * - A line that stands for one connection also offers "Realises": the outer connections (the boundary boxes on this diagram)
 *   it is marked as realising, each removable, and a list to add another; the change is stored at once.
 * A box the viewer cannot read shows its code only and offers no actions beyond removing it from the diagram.
 * Actions are icon buttons from the shared `SelectionActions` (the state machine card uses the same set); a connection row's
 * Edit and a realised connection's Remove are the same `IconAction`.
 */
import { ArrowLeft, ExternalLink, Merge, Pencil, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ActivityNote } from "../../components/ActivityNote";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { returnFocusToCanvas } from "../../utils/canvasFocus";
import { overlayIsOpen } from "../../utils/keyboardTargets";
import { FieldCaption } from "../../components/FieldHelp";
import { IconAction } from "../../components/IconAction";
import { ItemRow } from "../../components/ItemRow";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordTags } from "../../components/RecordTags";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage } from "../../context/ToastContext";
import { useRecordCode } from "../../hooks/useRecordCode";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, pointXY, type AttachPoint } from "../../components/graphAttachPoints";
import type { LineEnds } from "../../components/graphLineAnchors";
import { suggestWaypoint, type LineShape } from "../../components/graphLinePath";
import { BOUNDARY_NODE_PREFIX, BOUNDARY_SHAPE_LABEL, boundaryOutsideName, boxFrame, leaderIsDrawn, leaderSummary, routedConnectionOf, routeOf, sharesItsPair, type EditorBoundary, type EditorBox } from "./diagramEditorModel";
import { NOTE_NODE_PREFIX, leaderVertexSuggestion, type EditorLeader, type EditorNote, type NoteLeaderTarget, type NotePatch } from "./noteModel";
import { boxName } from "./diagramOutlineModel";
import { DiagramLeaderEditor } from "./DiagramLeaderEditor";
import { DiagramNoteEditor } from "./DiagramNoteEditor";
import { ARCHITECTURE_HELP } from "./help";
import { ConnectionSelectionFields } from "./ConnectionSelectionFields";
import { ConnectionSummaryList, ConnectionSummaryRow } from "./ConnectionSummaryList";
import { ElementSelectionFields } from "./ElementSelectionFields";
import { LineVertexFields } from "./LineVertexFields";
import { PortList } from "./PortList";
import { selectionAction, type SelectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import type {
  ArchitectureConnection, ArchitectureElement, ArchitectureSymbol, ConnectionFieldValues, ConnectionRef, ConnectionType, DiagramAnchor, LineRouteChange,
  DiagramViewEdge, ElementFieldValues, ElementType, ModelStateMachine, PortValues, ArchitectureDomain,
} from "./types";
import type { OrgUser } from "../../api/types";
import { MarkdownView } from "../../components/MarkdownView";

/** What an element's in-place fields need beyond the element itself (the owner's vocabularies and people). */
export interface ElementEditorReference {
  elementTypes: ElementType[];
  symbols: ArchitectureSymbol[];
  symbolUrl: (symbolId: string) => string;
  orgUsers: OrgUser[];
  organizationId: string;
  /** Reloads `symbols` after the symbol picker uploaded one. */
  onSymbolsChanged?: () => void;
}

/**
 * The Selection card's actions for an element's state machine diagrams.
 *
 * @param machines The diagrams that describe the element.
 * @param open Opens one.
 * @param formatCode Writes a record code the way the person's settings ask (project-qualified or bare).
 * @returns Nothing for none; an icon action for one; one overflow menu entry per diagram for several.
 */
function stateMachineActions(
  machines: readonly ModelStateMachine[], open: (machine: ModelStateMachine) => void, formatCode: (code: string) => string,
): SelectionAction[] {
  if (machines.length === 0) return [];
  if (machines.length === 1) return [selectionAction.stateMachine("Open state machine diagram", () => open(machines[0]))];
  return machines.map((m) => selectionAction.stateMachineChoice(`Open state machine diagram ${formatCode(m.unique_code)} ${m.name}`, () => open(m)));
}

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
 * @param defaultShape The diagram's default line shape (a line with no shape of its own follows it).
 * @param lineEnds The attach points a line's ends use and would use if left automatic (`lineEndsOf`).
 * @param hidden The boxes a view switch hides (not offered as the other end of a connection).
 * @param editable False hides every action that changes the diagram or the model.
 * @param elements The elements the editor knows (their ports are listed for a selected box).
 * @param connectionTypes The connection types a port may name.
 * @param elementEditor What the element's in-place fields need; without it a box is shown as text.
 * @param elementTypes The project's element types (a connection's type guidance reads them).
 * @param domains The project's domains, whose names a connection's type warning uses.
 * @param onSaveElement Stores changed fields of an element (version lock); resolves true when stored.
 * @param onSaveConnection Stores changed fields of a connection (version lock); resolves true when stored.
 * @param focusNew The id of the element or connection just added, whose name field takes the focus, or null.
 * @param onFocused Called once that name has taken the focus.
 * @param chosenConnectionId The connection of the selected line the person chose, or null for the line's list (ignored when the line does not stand for it).
 * @param onChooseConnection Chooses a connection of the selected line, or null to go back to the list; not part of the undo history.
 * @param onEditConnection Opens a connection's edit form (a line that stands for several connections).
 * @param onAddPort Adds a port to an element.
 * @param onChangePort Changes one field of an element's port.
 * @param onRemovePort Removes an element's port.
 * @param onRemoveBox Takes an element off the diagram.
 * @param onConnect Starts a connection from a box to the element with the given id.
 * @param onOpenInside Opens (or creates) the diagram of the element's inside.
 * @param stateMachinesOf The state machine diagrams that describe an element (none for one the person cannot read).
 * @param onOpenMachine Opens a state machine diagram from this diagram (the page asks before leaving unsaved changes). One diagram is an icon
 *   action, several are entries of the overflow menu: the keyboard route to the badge on the box.
 * @param onDeleteElement Deletes the element from the model.
 * @param onAnchorChange Sets the attach point of one or both ends of a line (`null` makes an end automatic), or its vertices; the page decides whether that routes the line's pair of boxes or one connection.
 * @param onJoinLine Takes the own route of a connection away, so it is drawn with the line of its pair of boxes again.
 * @param drawnEdgeIds The ids of the lines the canvas draws (a note's leader to a connection needs one of them).
 * @param onNoteChange Changes a note's title, text, tone or alignment.
 * @param onAddLeader Adds a leader to a note (a line to a free spot beside it, which becomes the selection).
 * @param onSelectLeader Selects a leader (by key).
 * @param onSelectNote Selects a note (by key).
 * @param onLeaderTarget Points a leader at a box, connection or spot.
 * @param onLeaderChange Changes a leader's start point, vertices, curve or end styles.
 * @param onRemoveLeader Removes a leader (its note stays).
 * @param onRemoveNote Removes a note.
 * @param onRemoveBoundary Takes a boundary box off the diagram (the connection is not changed).
 * @param onConnectBoundary Starts a connection between an inner element and the element outside a boundary box.
 * @param onSetRealises Sets the outer connections a connection realises (stored at once; may reject).
 * @param onComment Starts a comment on the selected box or line (the keyboard route to what a click in comment mode does); when absent no button is shown.
 */
export function DiagramSelectionPanel({
  projectId, selection, boxes, notes, edges, anchors, lineEnds, defaultShape, hidden, editable, onRemoveBox, onConnect, onOpenInside, onDeleteElement,
  onAnchorChange, onJoinLine, drawnEdgeIds, onNoteChange, onAddLeader, onSelectLeader, onSelectNote, onLeaderTarget, onLeaderChange, onRemoveLeader, onRemoveNote, elements, connectionTypes, elementEditor, elementTypes, domains, onSaveElement, onSaveConnection, focusNew, onFocused, chosenConnectionId, onChooseConnection, onEditConnection, onAddPort, onChangePort, onRemovePort, maxHeight,
  boundaries, connectionsById, realisedBy, onRemoveBoundary, onConnectBoundary, onSetRealises, onComment, stateMachinesOf, onOpenMachine,
}: {
  projectId: string;
  stateMachinesOf: (elementId: string) => readonly ModelStateMachine[];
  onOpenMachine: (machine: ModelStateMachine) => void;
  selection: GraphCanvasSelection | null;
  boxes: EditorBox[];
  notes: EditorNote[];
  boundaries: EditorBoundary[];
  connectionsById: ReadonlyMap<string, ArchitectureConnection>;
  realisedBy: ReadonlyMap<string, readonly string[]>;
  onRemoveBoundary: (box: EditorBoundary) => void;
  onConnectBoundary: (box: EditorBoundary, elementId: string) => void;
  onSetRealises: (connection: ArchitectureConnection, outerIds: string[]) => Promise<void>;
  onComment?: (target: { kind: "node" | "edge"; id: string }) => void;
  edges: DiagramViewEdge[];
  anchors: DiagramAnchor[];
  lineEnds: (edgeId: string) => LineEnds | null;
  /** The diagram's default line shape, for a line or leader with none of its own. */
  defaultShape: LineShape;
  hidden: ReadonlySet<string>;
  editable: boolean;
  onRemoveBox: (box: EditorBox) => void;
  onConnect: (box: EditorBox, targetId: string) => void;
  onOpenInside: (box: EditorBox) => void;
  onDeleteElement: (box: EditorBox) => void;
  onAnchorChange: (edge: DiagramViewEdge, change: LineRouteChange) => void;
  onJoinLine: (connectionId: string) => void;
  drawnEdgeIds: ReadonlySet<string>;
  onNoteChange: (key: string, patch: NotePatch) => void;
  onAddLeader: (noteKey: string) => void;
  onSelectLeader: (leaderKey: string) => void;
  onSelectNote: (noteKey: string) => void;
  onLeaderTarget: (leaderKey: string, target: NoteLeaderTarget) => void;
  onLeaderChange: (leaderKey: string, change: Partial<EditorLeader>) => void;
  onRemoveLeader: (leaderKey: string) => void;
  onRemoveNote: (key: string) => void;
  elements: ArchitectureElement[];
  connectionTypes: ConnectionType[];
  elementEditor: ElementEditorReference | null;
  elementTypes: ElementType[];
  domains: ArchitectureDomain[];
  onSaveElement: (element: ArchitectureElement, changed: Partial<ElementFieldValues>) => Promise<boolean>;
  onSaveConnection: (connection: ArchitectureConnection, changed: Partial<ConnectionFieldValues>) => Promise<boolean>;
  focusNew: string | null;
  onFocused: () => void;
  chosenConnectionId: string | null;
  onChooseConnection: (connectionId: string | null) => void;
  onEditConnection: (connection: ArchitectureConnection) => void;
  onAddPort: (elementId: string, values: PortValues) => Promise<void>;
  onChangePort: (elementId: string, portId: string, change: Partial<PortValues>) => Promise<void>;
  onRemovePort: (elementId: string, portId: string) => Promise<void>;
  /** The tallest the card may be (the drawing's height); it scrolls inside beyond that. */
  maxHeight?: number;
}) {
  const formatCode = useRecordCode();
  const commentText = useStrings().canvasComments;
  const [deleting, setDeleting] = useState<EditorBox | null>(null);
  /** The connection whose row takes the focus after Back, so the keyboard returns to where it was. */
  const [returnedTo, setReturnedTo] = useState<string | null>(null);
  const base = `/projects/${projectId}/modules/architecture`;

  const noteKey = selection?.kind === "node" && selection.id.startsWith(NOTE_NODE_PREFIX) ? selection.id.slice(NOTE_NODE_PREFIX.length) : null;
  const note = noteKey === null ? null : notes.find((n) => n.key === noteKey) ?? null;
  const found = selection?.kind === "leader"
    ? notes.flatMap((n) => n.leaders.map((l, i) => ({ note: n, leader: l, index: i + 1 }))).find((x) => x.leader.key === selection.id) ?? null
    : null;
  const boundaryKey = selection?.kind === "node" && selection.id.startsWith(BOUNDARY_NODE_PREFIX) ? selection.id.slice(BOUNDARY_NODE_PREFIX.length) : null;
  const boundary = boundaryKey === null ? null : boundaries.find((b) => b.connectionId === boundaryKey) ?? null;
  const box = selection?.kind === "node" && noteKey === null && boundaryKey === null ? boxes.find((b) => b.elementId === selection.id) ?? null : null;
  const edge = selection?.kind === "edge" ? edges.find((e) => e.id === selection.id) ?? null : null;

  const element = box ? elements.find((e) => e.id === box.elementId) ?? null : null;
  const editorFields = box && editable && !box.locked && !box.shared ? elementEditor : null;
  // A line that stands for one connection of this project edits it in place; a rolled-up or merged line lists its connections.
  const ownConnection = edge && editable && edge.connections.length === 1 && edge.connections[0].project_id === projectId
    ? edge.connections[0] : null;
  // A line that stands for several connections is a second level of selection: one of them may be chosen, which shows its
  // fields instead of the list. The choice belongs to the page; it is ignored when the selected line has no such connection.
  const chosen = edge && edge.connections.length > 1 ? edge.connections.find((c) => c.id === chosenConnectionId) ?? null : null;
  const chooseBack = () => { if (chosen) setReturnedTo(chosen.id); onChooseConnection(null); };
  // The connection a change to the line's route belongs to (the line's own, or the chosen one that can have a route of its own),
  // named by its code; none means the route is the line's and moves every connection on it.
  const routedConnection = edge ? edge.connections.find((c) => c.id === routedConnectionOf(edge, chosenConnectionId, sharesItsPair(edges, edge))) ?? null : null;
  const routeCode = routedConnection ? formatCode.code(routedConnection.unique_code, routedConnection.from_project_code) : null;

  let body;
  // The card's title is what is selected, so the heading line (with the Save button beside it) says what the card is about.
  let title: string | undefined;
  if (box) {
    title = box.locked ? box.unique_code : `${box.unique_code} ${box.name}`;
    body = (
      <>
        {!box.locked && <p className="text-muted">{box.element_type_name}</p>}
        {!(editorFields && element) && !box.locked && box.display_note && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Display note" help={ARCHITECTURE_HELP.elementDisplayNote} />
            <ActivityNote text={box.display_note} />
          </div>
        )}
        {!(editorFields && element) && !box.locked && element?.description && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Description" help={ARCHITECTURE_HELP.elementDescription} />
            <MarkdownView text={element.description} />
          </div>
        )}
        <SelectionActions
          actions={[
            !box.locked && selectionAction.open("Open element", `${base}/elements/${box.elementId}`),
            !box.locked && { ...selectionAction.inside("Open inside as diagram", () => onOpenInside(box)), help: ARCHITECTURE_HELP.openInside },
            ...(box.locked ? [] : stateMachineActions(stateMachinesOf(box.elementId), onOpenMachine, formatCode.code)),
            onComment && !box.locked && selectionAction.comment(commentText.commentOnBox, () => onComment({ kind: "node", id: box.elementId })),
            editable && selectionAction.remove("Remove from diagram", () => onRemoveBox(box)),
            editable && !box.locked && !box.shared && selectionAction.delete("Delete element…", () => setDeleting(box)),
          ]}
        />
        {editorFields && element && (
          <ElementSelectionFields
            key={`fields-${element.id}`} element={element} elementTypes={editorFields.elementTypes} symbols={editorFields.symbols}
            candidates={elements.filter((e) => !e.shared)} symbolUrl={editorFields.symbolUrl} orgUsers={editorFields.orgUsers}
            organizationId={editorFields.organizationId} projectId={projectId} autoFocusName={focusNew === element.id}
            onFocused={onFocused} onSave={(changed) => onSaveElement(element, changed)} onSymbolsChanged={editorFields.onSymbolsChanged}
          />
        )}
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
          <RecordTags key={`tags-${box.elementId}`} projectId={projectId} artefactType="architecture_element" artefactId={box.elementId} />
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
    title = boundary.connection_code;
    body = (
      <>
        <FieldCaption label="Boundary box" help={ARCHITECTURE_HELP.boundaryBox} muted />
        {!boundary.locked && boundary.type_name && <p className="text-muted">{boundary.type_name}</p>}
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
        <SelectionActions
          actions={[
            selectionAction.open("Open connection", `${base}/connections/${boundary.connectionId}`),
            editable && selectionAction.remove("Remove from diagram", () => onRemoveBoundary(boundary)),
          ]}
        />
        {editable && !boundary.locked && (
          <LabeledSelect
            label="Connect to" help={ARCHITECTURE_HELP.diagramBoundaryConnectTo} value="" placeholder="Choose an element…"
            options={boxes.filter((b) => !b.locked && !hidden.has(b.elementId)).map((b) => ({ value: b.elementId, label: boxName(b) }))}
            onChange={(elementId) => { if (elementId) onConnectBoundary(boundary, elementId); }}
          />
        )}
      </>
    );
  } else if (found || note) {
    const drawnBoxes = boxes.filter((b) => !hidden.has(b.elementId));
    const drawnBoxIds = new Set(drawnBoxes.map((b) => b.elementId));
    const drawnConnections = new Map<string, ArchitectureConnection>();
    for (const e of edges) if (drawnEdgeIds.has(e.id)) for (const c of e.connections) drawnConnections.set(c.id, c);
    if (found) {
      title = `Leader ${found.index}`;
      body = (
        <DiagramLeaderEditor
          key={found.leader.key} leader={found.leader} editable={editable}
          targets={[
            ...drawnBoxes.map((b) => ({ value: `element:${b.elementId}`, label: `Box: ${boxName(b)}` })),
            ...[...drawnConnections.values()].map((c) => ({ value: `connection:${c.id}`, label: `Connection: ${c.unique_code}${c.name ? ` ${c.name}` : ""}` })),
          ]}
          drawn={leaderIsDrawn(found.leader, drawnBoxIds, edges, drawnEdgeIds)} defaultShape={defaultShape}
          newPoint={leaderVertexSuggestion(found.note, found.leader, (target) => {
            const target_box = target.kind === "element" ? boxes.find((b) => b.elementId === target.elementId) : undefined;
            if (target.kind === "point") return { x: target.x, y: target.y };
            if (!target_box) return null;
            const size = boxFrame(target_box);
            return { x: target_box.x + size.width / 2, y: target_box.y + size.height / 2 };
          })}
          onTarget={(target) => onLeaderTarget(found.leader.key, target)} onChange={(change) => onLeaderChange(found.leader.key, change)}
          onOpenNote={() => onSelectNote(found.note.key)} onRemove={() => onRemoveLeader(found.leader.key)}
        />
      );
    } else if (note) {
      title = "Note";
      body = (
        <DiagramNoteEditor
          key={note.key} note={note} editable={editable} autoFocusText={focusNew === NOTE_NODE_PREFIX + note.key} onFocused={onFocused}
          leaders={note.leaders.map((l) => ({
            key: l.key, summary: leaderSummary(l, boxes, edges, true).replace(/ \(not drawn\)$/, ""),
            drawn: leaderIsDrawn(l, drawnBoxIds, edges, drawnEdgeIds),
          }))}
          onChange={(patch) => onNoteChange(note.key, patch)}
          onAddLeader={() => onAddLeader(note.key)} onOpenLeader={onSelectLeader} onRemove={() => onRemoveNote(note.key)}
        />
      );
    }
  } else if (edge) {
    const lineHeading = (
      <p>
        {edge.count > 1 ? `${edge.count} connections` : "1 connection"}
        {edge.bridged ? " (bridged across hidden elements)" : edge.rolled_up ? " (rolled up to the placed parents)" : ""}
      </p>
    );
    const passesThrough = edge.hops.length > 0 && (
      <p className="text-muted">Passes through: {edge.hops.map((h) => `${h.unique_code} ${h.name}`).join(", ")}</p>
    );
    const open = (c: ArchitectureConnection) => (
      <IconAction label={`Open ${formatCode.code(c.unique_code, c.from_project_code)}`} to={`${base}/connections/${c.id}`}><ExternalLink /></IconAction>
    );
    const chosenFields = chosen && editable && chosen.project_id === projectId ? chosen : null;
    const named = (c: ArchitectureConnection) => `${formatCode.code(c.unique_code, c.from_project_code)}${c.name ? ` ${c.name}` : ""}`;
    const endName = (id: string, boundaryEnd: boolean) => boundaryEnd ? "Boundary" : boxes.find((b) => b.elementId === id)?.name ?? "Element";
    title = chosen ? named(chosen)
      : edge.connections.length === 1 ? named(edge.connections[0])
        : `${endName(edge.source_element_id, edge.source_is_boundary)} → ${endName(edge.target_element_id, edge.target_is_boundary)}`;
    body = (
      <>
        {lineHeading}
        {passesThrough}
        {chosen ? (
          <ChosenConnection
            key={`chosen-${chosen.id}`} connection={chosen} count={edge.count} code={formatCode.code(chosen.unique_code, chosen.from_project_code)}
            open={open(chosen)} onBack={chooseBack}
            fields={chosenFields && (
              <>
                <ConnectionSelectionFields
                  key={`fields-${chosenFields.id}`} connection={chosenFields} connectionTypes={connectionTypes} elementTypes={elementTypes} domains={domains}
                  elements={elements} projectId={projectId} autoFocusName={false} onFocused={onFocused}
                  onSave={(changed) => onSaveConnection(chosenFields, changed)}
                />
                <RecordTags
                  key={`tags-${chosenFields.id}`} projectId={projectId} artefactType="architecture_connection" artefactId={chosenFields.id}
                  components={false}
                />
              </>
            )}
          />
        ) : (
          <ConnectionSummaryList
            connections={edge.connections} label="Connections of this line" codeOf={(c) => formatCode.code(c.unique_code, c.from_project_code)}
            onChoose={edge.connections.length > 1 ? (c) => onChooseConnection(c.id) : undefined}
            focusId={returnedTo} onFocused={() => setReturnedTo(null)}
            actionsOf={(c) => (
              <>
                {open(c)}
                {editable && ownConnection === null && c.project_id === projectId && (
                  <IconAction label={`Edit ${c.unique_code}`} onClick={() => onEditConnection(c)}><Pencil /></IconAction>
                )}
              </>
            )}
          />
        )}
        <SelectionActions actions={[onComment && selectionAction.comment(commentText.commentOnLine, () => onComment({ kind: "edge", id: edge.id }))]} />
        {ownConnection && (
          <ConnectionSelectionFields
            key={`fields-${ownConnection.id}`} connection={ownConnection} connectionTypes={connectionTypes} elementTypes={elementTypes} domains={domains}
            elements={elements} projectId={projectId} autoFocusName={focusNew === ownConnection.id} onFocused={onFocused}
            onSave={(changed) => onSaveConnection(ownConnection, changed)}
          />
        )}
        {ownConnection && (
          <RecordTags
            key={`tags-${ownConnection.id}`} projectId={projectId} artefactType="architecture_connection" artefactId={ownConnection.id}
            components={false}
          />
        )}
        {editable && !edge.source_is_boundary && !edge.target_is_boundary && (
          <LineEnds
            edge={edge} boxes={boxes} anchors={anchors} ends={lineEnds(edge.id)} defaultShape={defaultShape} onChange={(change) => onAnchorChange(edge, change)}
            routeCode={routeCode} lineCount={edge.count}
            onJoin={edge.route_connection_id ? () => onJoinLine(edge.route_connection_id as string) : undefined}
          />
        )}
        {editable && (edge.source_is_boundary || edge.target_is_boundary) && (
          <p className="text-muted">A line to a boundary box is placed automatically, so it has no attach points or vertices to set.</p>
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
    <DetailCard
      heading="Selection" title={title} maxHeight={maxHeight}
      onKeyDown={(event) => {
        returnFocusToCanvas(event, selection);
        if (chosen && leavesChosenConnection(event)) { event.preventDefault(); chooseBack(); }
      }}
    >
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
 * Whether a key press on the card means "back to the line's connection list": Escape that nothing else has used. A text
 * field and a select keep Escape for leaving the field (the card returns the focus to the canvas, as for any field) and an
 * open menu or dialog for closing itself.
 */
function leavesChosenConnection(event: KeyboardEvent<HTMLElement>): boolean {
  if (event.key !== "Escape" || event.defaultPrevented || overlayIsOpen()) return false;
  const target = event.target;
  return !(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement);
}

/**
 * The connection chosen from a merged line: a heading naming it (which takes the focus, so a screen reader announces the
 * change) with Back to the list and Open for its page, then its fields (or a read-only summary when it cannot be edited here).
 *
 * @param connection The chosen connection.
 * @param count How many connections the line stands for (the Back control names them).
 * @param code The connection's code, formatted by the code rule.
 * @param open The Open action (a link to the record's page).
 * @param onBack Returns to the line's list.
 * @param fields The editable fields, or null to show the connection as a read-only summary.
 */
function ChosenConnection({
  connection, count, code, open, onBack, fields,
}: {
  connection: ArchitectureConnection;
  count: number;
  code: string;
  open: ReactNode;
  onBack: () => void;
  fields: ReactNode;
}) {
  const heading = useRef<HTMLParagraphElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return (
    <div className="stack" role="group" aria-label="Chosen connection">
      <div>
        <button type="button" className="btn btn-sm" onClick={onBack}><ArrowLeft aria-hidden="true" /> Back to the {count} connections</button>
      </div>
      <ItemRow actions={open}>
        <p ref={heading} tabIndex={-1} style={{ margin: 0 }}>
          <strong>{code}</strong>
          {connection.name && <span> {connection.name}</span>}
        </p>
      </ItemRow>
      {fields ?? (
        <ul className="item-row-list" aria-label="Connection summary">
          <ConnectionSummaryRow connection={connection} code={code} />
        </ul>
      )}
    </div>
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
              <IconAction label={`Stop realising ${c.unique_code}`} onClick={() => void change(current.filter((x) => x.id !== c.id).map((x) => x.id))}>
                <X />
              </IconAction>
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
 * points, then its vertices. A line whose end is not a box of the layout offers nothing. A line that stands for several
 * connections, or is drawn for one on its own route, says whose route the fields set (`routeCode` names one connection, else
 * the route is the line's and every connection on it follows); a connection's own route can be given up with `onJoin`.
 */
function LineEnds({
  edge, boxes, anchors, ends, defaultShape, onChange, routeCode, lineCount, onJoin,
}: {
  edge: DiagramViewEdge;
  boxes: EditorBox[];
  anchors: DiagramAnchor[];
  ends: LineEnds | null;
  defaultShape: LineShape;
  onChange: (change: LineRouteChange) => void;
  routeCode: string | null;
  lineCount: number;
  onJoin?: () => void;
}) {
  const from = boxes.find((b) => b.elementId === edge.source_element_id);
  const to = boxes.find((b) => b.elementId === edge.target_element_id);
  if (!from || !to || !ends) return null;
  const chosen = routeOf(anchors, edge);
  // What Automatic would give each end with the other end as it is now, looking at every other line of the diagram.
  const [sourceAutomatic, targetAutomatic] = ends.automatic;
  const [a, b] = ends.current;
  const newPoint = suggestWaypoint(pointXY(from, a), chosen.points, pointXY(to, b));
  const options = (automatic: AttachPoint) => [
    { value: "", label: `Automatic (${ATTACH_POINT_LABEL[automatic]})` },
    ...ATTACH_POINTS.map((p) => ({ value: p, label: ATTACH_POINT_LABEL[p] })),
  ];
  const parse = (value: string): AttachPoint | null => (ATTACH_POINTS.find((p) => p === value) ?? null);
  return (
    <>
      {(routeCode !== null || lineCount > 1) && (
        <FieldCaption
          label={routeCode !== null ? `Route of ${routeCode}` : "Route of the line"}
          help={routeCode !== null ? ARCHITECTURE_HELP.routeOfConnection : ARCHITECTURE_HELP.routeOfLine}
          extra={onJoin && <IconAction label="Use the shared route" onClick={onJoin}><Merge /></IconAction>}
        />
      )}
      <LabeledSelect
        label="Line starts at" help={ARCHITECTURE_HELP.diagramLineFrom} placeholder={null} value={chosen.sourcePoint ?? ""}
        options={options(sourceAutomatic)} onChange={(value) => onChange({ sourcePoint: parse(value) })}
      />
      <LabeledSelect
        label="Line ends at" help={ARCHITECTURE_HELP.diagramLineTo} placeholder={null} value={chosen.targetPoint ?? ""}
        options={options(targetAutomatic)} onChange={(value) => onChange({ targetPoint: parse(value) })}
      />
      <LineVertexFields points={chosen.points} lineShape={chosen.lineShape} defaultShape={defaultShape} editable newPoint={newPoint} onChange={onChange} />
    </>
  );
}
