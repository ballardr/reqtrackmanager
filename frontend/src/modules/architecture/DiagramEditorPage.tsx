/**
 * Module: modules/architecture/DiagramEditorPage
 *
 * One diagram as a routed page and its editor (`/projects/:projectId/modules/architecture/diagrams/:diagramId`, also the
 * target other records' links follow). The record header sits above two tabs (`?tab=configuration`; Drawing is the default):
 * Drawing holds a toolbar (Undo, Redo, Save, the Add to diagram menu, Export), the shared graph canvas, the Outline and the
 * Selection card; Configuration holds the connection-detail setting and the view switches. Links and Activity are in the
 * aside. The pending layout, selection and undo history belong to the page, so a change of tab loses none of them.
 *
 * Editing model: boxes, notes, line anchors and boundary boxes are edited locally (with undo and redo) and stored
 * together by Save, which quotes the diagram's version; a 409 offers a reload instead of overwriting a newer save.
 * Creating a connection or deleting an element writes to the model at once, so a pending layout is saved first. An
 * element (from the Add menu or a palette drop) and a connection (a line drawn between two boxes) are created at once
 * with defaults (a numbered name; the connection type the ends suggest), selected, and edited in the Selection card
 * through the shared field groups; only a project with no connection type opens the connection dialog, which links to
 * where types are set up. Taking a box off the diagram never deletes its element; deleting the element is a separate,
 * confirmed action. A line that stands for several connections edits each in the shared connection form.
 * View switches are stored when changed, but flipping one on the page changes only the address.
 * The Outline card (elements as a tree, lines as a table) is the text alternative to the canvas and shares its
 * selection; the canvas is keyboard operable (arrows move, Alt+arrows resize, Delete removes the box from the diagram;
 * undo and redo through `EditHistoryButtons`) and the selection card can start a connection from a list. Export (PNG,
 * SVG, Mermaid text, copy Mermaid) saves a pending layout first, then asks the server for the saved diagram drawn for
 * the switch states on the page.
 * A diagram of an element's inside can draw the connections that cross the element's boundary as boundary boxes (Add to
 * diagram, "Outside this element"); a line drawn from an inner element to such a box creates a connection that
 * realises the outer connection, and a line's Selection card can set what it realises.
 * Lines, bridging and roll-up are computed in the browser from the diagram's model data (`GET .../model`) by
 * `diagramLines`, so an added box or a flipped switch redraws at once; the server's resolved view (`GET .../view`) gives
 * the boxes, notes and switches on load and stays the authority for the SVG and documents.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Workflow } from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { CommentModeToggle } from "../../components/CommentModeToggle";
import { NoteModeToggle } from "./NoteModeToggle";
import { useEscapeToLeaveMode } from "../../hooks/useEscapeToLeaveMode";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Badge } from "../../components/Badge";
import { DetailLayout } from "../../components/DetailLayout";
import { EditHistoryButtons } from "../../components/EditHistoryButtons";
import { useCanvasComments } from "../../components/CanvasCommentLayer";
import { useAttachPointVisibility } from "../../hooks/useAttachPointVisibility";
import { useSnapToGrid } from "../../hooks/useSnapToGrid";
import { GraphCanvas, type GraphCanvasSelection, type GraphLeaderTarget, type GraphNodeBadge } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { useFillViewportHeight } from "../../hooks/useFillViewportHeight";
import { RecordHeader } from "../../components/RecordHeader";
import { Tooltip } from "../../components/Tooltip";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { resolveEffectiveTheme, useTheme } from "../../context/ThemeContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useRecordCode } from "../../hooks/useRecordCode";
import { useUrlChoice, useUrlFlag, useUrlList } from "../../hooks/useUrlFilter";
import { architectureTabPath } from "./architectureTabs";
import { stateMachinePath } from "./stateMachineLinks";
import { DiagramSwitcher } from "./DiagramSwitcher";
import { ARCHITECTURE_HELP } from "./help";
import { capabilitiesApi, projectConnectionApi, projectDiagramApi, projectElementApi, projectSymbolUrl } from "./api";
import {
  blankConnectionValues, defaultElementName, diffConnectionFields, diffDiagramFields, valuesFromConnection, valuesFromDiagram,
} from "./architectureFields";
import { defaultConnectionType } from "./connectionGuidance";
import { architectureLifecycle } from "./architectureLifecycle";
import { AddElementsDialog } from "./AddElementsDialog";
import { ConnectionFormModal } from "./ConnectionFormModal";
import { addBoundaries, addBoxes, boundaryFromConnection, boxWithElement, boundaryNodeId, boundaryOutsideName, boxFromElement, canvasEdges, canvasLeaders, canvasNodes, clearConnectionRoute, moveItems, nextFreePosition, removeBoundary, removeBox, resizeItems, routedConnectionOf, routedConnections, sharesItsPair, setConnectionRoute, setLineAnchor, boxFrame, lockedBoxLabel, BOUNDARY_NODE_PREFIX } from "./diagramEditorModel";
import {
  LEADER_REACH, MAX_NOTE_LEADERS, NOTE_HEIGHT, NOTE_NODE_PREFIX, NOTE_WIDTH, addLeader, addNote, newLeader, newLeaderKey, newNote, newNoteKey,
  noteFrame, patchLeader, removeLeader, removeNote, setLeaderTarget, updateNote, type EditorLeader, type NoteLeaderTarget,
} from "./noteModel";
import { outerSide } from "./diagramResolver";
import { toggleStates } from "./diagramExport";
import { DiagramExportMenu } from "./DiagramExportMenu";
import { useDiagramExport } from "./useDiagramExport";
import { DiagramCommentsPanel } from "./DiagramCommentsPanel";
import { blockPinDescriber, pinAnchorOf, pinPlaceOf } from "./diagramComments";
import { DiagramFormModal } from "./DiagramFormModal";
import { DiagramAddMenu } from "./DiagramAddMenu";
import { DiagramOutline } from "./DiagramOutline";
import { lineEndsOf } from "../../components/graphLineAnchors";
import { DiagramSelectionPanel, type ElementEditorReference } from "./DiagramSelectionPanel";
import { DiagramSettingsButton } from "./DiagramSettingsButton";
import { DiagramTogglesPanel } from "./DiagramTogglesPanel";
import { resolveDiagram, type ResolvedDiagram } from "./diagramLines";
import { PALETTE_TYPE_PREFIX, toggleValues } from "./diagramToggles";
import { ToggleFormModal } from "./ToggleFormModal";
import { useArchitectureReference } from "./useArchitectureReference";
import { useCreateConnection } from "./useCreateConnection";
import { useDiagramEditor } from "./useDiagramEditor";
import { useSymbolSvgs } from "./useSymbolSvgs";
import { markdownPlainText } from "../../utils/markdownPlain";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureConnection, type ArchitectureElement,
  type ArchitectureRecordStatus, type ConnectionFieldValues, type ModelStateMachine, type DiagramViewEdge, type LineRouteChange, type DiagramFieldValues, type DiagramToggle, type DiagramToggleValues, type ElementFieldValues, type PortValues, isOutOfUse,
} from "./types";

/** The smallest canvas height; a shorter window scrolls instead. Above it the canvas fills the window below its tabs. */
const CANVAS_MIN_HEIGHT = 300;
/** The project's Element Types settings. */
const SETUP_PATH = (projectId: string) => `/projects/${projectId}/admin/architecture/architecture-element-types`;
/** The project's Connection Types settings. */
const CONNECTION_SETUP_PATH = (projectId: string) => `/projects/${projectId}/admin/architecture/architecture-connection-types`;

const EDITOR_TABS = [
  { key: "drawing", label: "Drawing" },
  { key: "outline", label: "Outline" },
  { key: "comments", label: "Comments" },
  { key: "configuration", label: "Configuration" },
] as const;
type EditorTab = (typeof EDITOR_TABS)[number]["key"];

/** The resolved lines the canvas actually draws (a pin follows a drawn line, not one a switch has removed). */
function drawnLines(lines: readonly DiagramViewEdge[], drawn: ReadonlySet<string>): DiagramViewEdge[] {
  return lines.filter((line) => drawn.has(line.id));
}

const NO_LINES: ResolvedDiagram = { edges: [], hidden: new Set(), internal: new Map() };

export function DiagramEditorPage() {
  const { projectId = "", diagramId = "" } = useParams<{ projectId: string; diagramId: string }>();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const reference = useArchitectureReference(projectId);
  const diagramApi = useMemo(() => projectDiagramApi(projectId), [projectId]);
  const base = `/projects/${projectId}/modules/architecture`;

  const [showNotes, setShowNotes] = useUrlFlag("notes", true);
  const [toggleOn, setToggleOn] = useUrlList("toggle_on");
  const [toggleOff, setToggleOff] = useUrlList("toggle_off");
  // The Drawing tab is the default and so leaves the address unmarked; the pending layout, selection and undo history live
  // in this page, so they survive a change of tab.
  const [tabChoice, setTabChoice] = useUrlChoice("tab", ["outline", "comments", "configuration"] as const);
  const tab: EditorTab = tabChoice || "drawing";
  const editor = useDiagramEditor(projectId, diagramId);
  const { diagram, view, model, layout, dirty } = editor;

  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [connections, setConnections] = useState<ArchitectureConnection[]>([]);
  const [picked, setPicked] = useState<GraphCanvasSelection | null>(null);
  const [canvasBox, setCanvasBox] = useState<HTMLElement | null>(null);
  const canvasHeight = useFillViewportHeight(canvasBox, CANVAS_MIN_HEIGHT);
  const [editingDiagram, setEditingDiagram] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  /** The element or connection just added, whose name field in the Selection card takes the focus. */
  const [focusNew, setFocusNew] = useState<string | null>(null);
  /** The connection just added, which is the selection as soon as its line is drawn (any other selection replaces it). */
  const [selectConnection, setSelectConnection] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectParam = searchParams.get("select");
  /** The connection of a merged line the person chose in the Selection card; it belongs to that line and ends with its selection. */
  const [chosenConnection, setChosenConnection] = useState<{ edgeId: string; connectionId: string } | null>(null);
  const setSelection = useCallback((next: GraphCanvasSelection | null) => {
    setPicked(next);
    setSelectConnection(null);
    // Selecting the same line again (the canvas does so after a save redraws it) keeps the choice; anything else ends it.
    setChosenConnection((current) => (current && next?.kind === "edge" && next.id === current.edgeId ? current : null));
    // Selecting anything (or clearing the selection) ends the link's selection.
    if (selectParam) setSearchParams((current) => { const params = new URLSearchParams(current); params.delete("select"); return params; }, { replace: true });
  }, [selectParam, setSearchParams]);
  const [connecting, setConnecting] = useState<{ source: string; target: string; realises?: string } | null>(null);
  const [toggleForm, setToggleForm] = useState<{ initial?: DiagramToggleValues } | null>(null);
  const [leaveFor, setLeaveFor] = useState<string | null>(null);
  /** The address of a state machine diagram waiting for the person to confirm leaving unsaved changes. */
  const [leaveForMachine, setLeaveForMachine] = useState<string | null>(null);
  const formatCode = useRecordCode();
  const [canManageTypes, setCanManageTypes] = useState(false);
  const [leaveForSetup, setLeaveForSetup] = useState(false);
  const [editingConnection, setEditingConnection] = useState<ArchitectureConnection | null>(null);
  const [connectionFormError, setConnectionFormError] = useState<string | null>(null);

  /** Reads the project's elements and connections again; resolves once both lists are set. */
  const reloadModelLists = useCallback((): Promise<unknown> => {
    if (!projectId) return Promise.resolve();
    const elementApi = projectElementApi(projectId);
    return Promise.all([
      Promise.all([elementApi.list({ open_only: true }), elementApi.listShared({ open_only: true })])
        .then(([own, shared]) => setElements([...own, ...shared]))
        .catch(() => setElements([])),
      projectConnectionApi(projectId).list({ open_only: true }).then(setConnections).catch(() => setConnections([])),
    ]);
  }, [projectId]);
  useEffect(() => { reloadModelLists(); }, [reloadModelLists]);
  useEffect(() => {
    if (!projectId) return;
    let live = true;
    capabilitiesApi.get(projectId).then((c) => { if (live) setCanManageTypes(c.manage_types); }).catch(() => { if (live) setCanManageTypes(false); });
    return () => { live = false; };
  }, [projectId]);

  // Unsaved layout edits are lost on leaving the page, so the browser is asked before it closes or reloads.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /**
   * Stores changed fields of an element from the Selection card, then reads the lists and the diagram again (the pending layout
   * is kept: a merge, not a replace) so the card quotes the new version.
   *
   * @returns True when stored; a refusal is a toast and false, leaving the draft for correction.
   */
  async function saveElementFields(element: ArchitectureElement, changed: Partial<ElementFieldValues>): Promise<boolean> {
    try {
      const updated = await projectElementApi(projectId).update(element.id, element.version, changed);
      showToast("Element updated.");
      // A box added since the layout was last saved is not in the stored view, so the read below cannot rename it.
      const type = elementTypes.find((t) => t.id === updated.element_type_id);
      editor.refreshBoxes((box) => (box.elementId === updated.id ? boxWithElement(box, updated, type) : box));
      await Promise.all([reloadModelLists(), editor.reload(false)]);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this element."), "error");
      return false;
    }
  }

  /** Stores changed fields of a connection and reads the lists and the diagram again; throws the server's refusal. */
  async function storeConnectionFields(connection: ArchitectureConnection, changed: Partial<ConnectionFieldValues>) {
    await projectConnectionApi(projectId).update(connection.id, connection.version, changed);
    showToast("Connection updated.");
    await Promise.all([reloadModelLists(), editor.reload(false)]);
  }

  /** The Selection card's save of a connection: false, with a toast, when the server refuses. */
  async function saveConnectionFields(connection: ArchitectureConnection, changed: Partial<ConnectionFieldValues>): Promise<boolean> {
    try {
      await storeConnectionFields(connection, changed);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this connection."), "error");
      return false;
    }
  }

  /** The dialog's save of one connection of a line that stands for several. */
  async function saveConnectionEdit(values: ConnectionFieldValues) {
    const connection = editingConnection;
    if (!connection) return;
    setConnectionFormError(null);
    const changed = diffConnectionFields(valuesFromConnection(connection), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditingConnection(null);
      return;
    }
    try {
      await storeConnectionFields(connection, changed);
      setEditingConnection(null);
    } catch (err) {
      setConnectionFormError(toErrorMessage(err, "Could not update this connection."));
    }
  }

  /** The port calls of the Selection card: each is stored at once and the element list is read again. */
  const portsApi = useMemo(() => {
    const api = projectElementApi(projectId);
    return {
      add: async (elementId: string, values: PortValues) => { await api.addPort(elementId, values); reloadModelLists(); },
      change: async (elementId: string, portId: string, change: Partial<PortValues>) => { await api.updatePort(elementId, portId, change); reloadModelLists(); },
      remove: async (elementId: string, portId: string) => { await api.removePort(elementId, portId); reloadModelLists(); },
    };
  }, [projectId, reloadModelLists]);

  /**
   * After a connection exists: marks it as realising a boundary box's outer connection when it was drawn to one, reads the model
   * again and, once its line is drawn, selects it with the cursor in its name.
   */
  function connectionCreated(id: string, outerId?: string) {
    void reloadModelLists();
    void (async () => {
      if (outerId) {
        try {
          const created = await projectConnectionApi(projectId).get(id);
          await projectConnectionApi(projectId).setRealisations(id, created.version, [outerId]);
          showToast("The connection realises the outer connection.");
        } catch (err) {
          showToast(toErrorMessage(err, "The connection was created but could not be marked as realising the outer connection."), "error");
        }
      }
      await editor.reload(false);
      setFocusNew(id);
      setSelectConnection(id);
    })();
  }
  // The dialog is reached only by a project with no connection type, which cannot save one; the hook keeps its refusal shown.
  const createConnection = useCreateConnection(projectId, (id) => {
    const outerId = connecting?.realises;
    setConnecting(null);
    connectionCreated(id, outerId);
  });

  // A switch's state on this page: the address overrides the saved default (the choice is never stored).
  const toggles = useMemo(
    () => (view?.toggles ?? []).map((t) => ({ ...t, on: toggleOff.includes(t.id) ? false : toggleOn.includes(t.id) || t.default_on })),
    [view, toggleOn, toggleOff],
  );
  // Export is of the stored diagram, so a pending layout is saved first; the server draws it for the switch states on this page.
  const { exporting, exportDiagram } = useDiagramExport(
    diagram && {
      code: diagram.unique_code, name: diagram.name,
      ensureSaved: async () => !dirty || (await editor.save()),
      loadSvg: () => diagramApi.svg(diagram.id, toggleStates(toggles)),
      loadMermaid: () => diagramApi.mermaid(diagram.id, toggleStates(toggles)),
    },
  );
  const connectionDetail = diagram?.connection_detail ?? false;
  const showConnectionNames = diagram?.show_connection_names ?? false;
  const scopeId = diagram?.scope_element_id ?? null;
  const routed = useMemo(() => routedConnections(layout.anchors), [layout.anchors]);
  const resolved = useMemo(
    () => (model
      ? resolveDiagram(model, {
        placed: layout.boxes.map((b) => b.elementId), togglesOff: new Set(toggles.filter((t) => !t.on).map((t) => t.id)), connectionDetail, showConnectionNames,
        scopeId, boundaries: layout.boundaries.map((b) => ({ id: boundaryNodeId(b.connectionId), connectionId: b.connectionId })), routed,
      })
      : NO_LINES),
    [model, layout.boxes, layout.boundaries, toggles, connectionDetail, showConnectionNames, scopeId, routed],
  );
  /** The model's connections by id, the outer connections realised, and which connection realises which. */
  const connectionsById = useMemo(() => new Map((model?.connections ?? []).map((c) => [c.id, c])), [model]);
  const realisedBy = useMemo(() => {
    const found = new Map<string, string[]>();
    for (const r of model?.realisations ?? []) found.set(r.outer_connection_id, [...(found.get(r.outer_connection_id) ?? []), r.inner_connection_id]);
    return found;
  }, [model]);
  /** The connections that cross the scope's boundary and are not yet drawn, for the Add menu's "Outside this element" group. */
  const outerChoices = useMemo(() => {
    if (!model || !scopeId) return [];
    const parents = new Map(Object.entries(model.parents));
    const drawn = new Set(layout.boundaries.map((b) => b.connectionId));
    return model.connections.flatMap((c) => {
      const side = outerSide(scopeId, parents, c.source_element_id, c.target_element_id);
      if (side === null || drawn.has(c.id) || c.is_archived) return [];
      return [{ connection: c, side, box: boundaryFromConnection(c, side, { x: 0, y: 0 }) }];
    });
  }, [model, scopeId, layout.boundaries]);

  /** Each readable element's state machine diagrams, from the model. */
  const machinesOf = useMemo(
    () => new Map((model?.elements ?? []).filter((e) => !e.locked && e.state_machines.length > 0).map((e) => [e.id, e.state_machines])),
    [model],
  );
  /** Opens a state machine diagram from this one; with unsaved changes it first asks, since leaving discards them. */
  const openMachine = useCallback((machine: ModelStateMachine) => {
    const to = stateMachinePath(projectId, machine.id, diagramId);
    if (dirty) setLeaveForMachine(to);
    else navigate(to);
  }, [projectId, diagramId, dirty, navigate]);
  const badgesOf = useCallback((elementId: string): GraphNodeBadge[] => {
    const machines = machinesOf.get(elementId);
    if (!machines) return [];
    return [{
      id: "state-machines",
      label: machines.length === 1 ? "Open state machine diagram" : `Open a state machine diagram (${machines.length} available)`,
      icon: <Workflow />, count: machines.length > 1 ? machines.length : undefined,
      items: machines.map((m) => ({ id: m.id, label: `${formatCode.code(m.unique_code)} ${m.name}`, onSelect: () => openMachine(m) })),
    }];
  }, [machinesOf, openMachine, formatCode]);

  const descriptions = useMemo(() => new Map(elements.filter((e) => e.description).map((e) => [e.id, e.description])), [elements]);
  const symbolSvg = useSymbolSvgs(projectId, layout.boxes.map((b) => b.symbol_id));
  const effectiveTheme = resolveEffectiveTheme(theme);
  const nodes = useMemo(
    () => canvasNodes(layout, {
      theme: effectiveTheme, symbolSvg, lockedLabel: lockedBoxLabel, emptyNote: "Empty note", noteCaption: "Note",
      hidden: resolved.hidden, covered: new Set(realisedBy.keys()), coverageLabel: (isCovered) => (isCovered ? "Covered" : "Not covered"),
      showNotes, badges: badgesOf,
    }),
    [layout, effectiveTheme, symbolSvg, resolved.hidden, realisedBy, showNotes, badgesOf],
  );
  const edges = useMemo(
    () => canvasEdges(resolved.edges, layout, resolved.hidden, effectiveTheme, diagram?.line_shape),
    [resolved, layout, effectiveTheme, diagram?.line_shape],
  );
  const drawnEdgeIds = useMemo(() => new Set(edges.map((e) => e.id)), [edges]);
  const lineEnds = useMemo(() => lineEndsOf(nodes, edges), [nodes, edges]);
  const leaders = useMemo(() => canvasLeaders(layout, resolved.edges, drawnEdgeIds, diagram?.line_shape), [layout, resolved, drawnEdgeIds, diagram?.line_shape]);
  // A connection just added is the selection once a line for it is drawn (a switch may hide it, which leaves it unselected).
  const newLine = selectConnection === null ? undefined
    : resolved.edges.find((e) => drawnEdgeIds.has(e.id) && e.connections.some((c) => c.id === selectConnection));
  // A link that names an element (`?select=`, the way back from its state machine diagram) selects its box and centres the view
  // once the layout is loaded. It is the selection until the person selects anything else (which drops the parameter); an
  // element the diagram does not draw selects nothing.
  const linkedBox = selectParam && view !== null ? layout.boxes.find((b) => b.elementId === selectParam) : undefined;
  const selection: GraphCanvasSelection | null = newLine
    ? { kind: "edge", id: newLine.id }
    : picked ?? (linkedBox ? { kind: "node", id: linkedBox.elementId } : null);
  const chosenConnectionId = chosenConnection && selection?.kind === "edge" && selection.id === chosenConnection.edgeId ? chosenConnection.connectionId : null;
  // The canvas moves the view when `key` changes, so the same key while the box is dragged afterwards does not move it again.
  const linkedFrame = linkedBox ? boxFrame(linkedBox) : undefined;
  const selectCenter = linkedBox && linkedFrame ? { x: linkedBox.x + linkedFrame.width / 2, y: linkedBox.y + linkedFrame.height / 2, key: 1 } : undefined;



  // Comments are stored at once and apart from the layout, so they never make the drawing look unsaved; a link to a thread
  // (`?pin=`) is opened by `useCanvasComments`, after the drawing is fitted.
  const { user: currentUser } = useAuth();
  const anchorOfPin = useCallback((place: Parameters<typeof pinAnchorOf>[0]) => pinAnchorOf(place, layout.boxes, drawnLines(resolved.edges, drawnEdgeIds)), [layout.boxes, resolved.edges, drawnEdgeIds]);
  const placeOfClick = useCallback(
    (position: { x: number; y: number }, anchor: Parameters<typeof pinPlaceOf>[1]) => pinPlaceOf(position, anchor, layout.boxes, drawnLines(resolved.edges, drawnEdgeIds)),
    [layout.boxes, resolved.edges, drawnEdgeIds],
  );
  const snap = useSnapToGrid();
  const attachPoints = useAttachPointVisibility();
  const commentLayer = useCanvasComments({
    projectId, artefactType: "architecture_diagram", recordId: diagramId, anchorOf: anchorOfPin, placeOf: placeOfClick,
  });

  // Note mode and Comment mode are never both on: turning one on turns the other off, and a comment started elsewhere (Pin to
  // diagram) wins while it lasts.
  const [noteMode, setNoteMode] = useState(false);
  const placingNote = noteMode && !commentLayer.commentMode;
  const chooseCommentMode = (on: boolean) => { if (on) setNoteMode(false); commentLayer.setCommentMode(on); };
  const chooseNoteMode = (on: boolean) => { if (on) commentLayer.setCommentMode(false); setNoteMode(on); };
  useEscapeToLeaveMode(placingNote || commentLayer.commentMode, () => { setNoteMode(false); commentLayer.setCommentMode(false); });

  const archive = useArchiveAction({
    noun: "Diagram",
    isArchived: diagram?.is_archived ?? false,
    hidden: !diagram,
    archiveBody: "This diagram will no longer appear in lists. Nothing is deleted, and the model's elements and connections are untouched.",
    onToggle: async () => {
      if (!diagram) return;
      try {
        editor.setDiagram(await (diagram.is_archived ? diagramApi.unarchive(diagram.id) : diagramApi.archive(diagram.id)));
        showToast(diagram.is_archived ? "Diagram unarchived." : "Diagram archived.");
      } catch (err) {
        showToast(toErrorMessage(err, "Could not update this diagram."), "error");
      }
    },
  });
  const remove = useConfirmedAction(diagram ? {
    label: "Delete permanently", danger: true, title: "Delete this diagram permanently?",
    message: "The diagram, its boxes, notes and switches are deleted. The model's elements and connections are not changed. This cannot be undone.",
    confirmLabel: "Delete", requireTypedText: diagram.unique_code,
    onConfirm: async () => {
      try {
        await diagramApi.remove(diagram.id);
        showToast("Diagram deleted.");
        navigate(architectureTabPath(projectId, "diagrams"));
      } catch (err) {
        showToast(toErrorMessage(err, "Could not delete this diagram."), "error");
      }
    },
  } : null);

  if (!projectId || !diagramId) return null;
  if (editor.loadError) return <p className="text-muted">{editor.loadError}</p>;
  if (diagram === null || view === null || model === null || !reference.loaded) return <Spinner />;

  const editable = !diagram.is_archived;
  const elementTypes = reference.elementTypes;

  /** Stores a pending layout before an action that writes to the model; false when it could not be stored. */
  async function ensureSaved(): Promise<boolean> {
    return !dirty || (await editor.save());
  }

  async function saveLayout() {
    if (await editor.save()) showToast("Diagram saved.");
  }

  async function startConnection(source: string, target: string) {
    const boundaryId = [source, target].find((id) => id.startsWith(BOUNDARY_NODE_PREFIX));
    if (boundaryId !== undefined) {
      const element = boundaryId === source ? target : source;
      const box = layout.boundaries.find((b) => boundaryNodeId(b.connectionId) === boundaryId);
      if (box && !element.startsWith(BOUNDARY_NODE_PREFIX)) await startBoundaryConnection(box.connectionId, element);
      return;
    }
    const ends = layout.boxes.filter((b) => b.elementId === source || b.elementId === target);
    if (source.startsWith(NOTE_NODE_PREFIX) || target.startsWith(NOTE_NODE_PREFIX) || ends.some((b) => b.locked)) return;
    if (!(await ensureSaved())) return;
    await addConnection(source, target);
  }

  /**
   * Creates a connection between two elements at once, with the type the ends suggest (`defaultConnectionType`) and every other
   * field empty, to be edited in the Selection card. A project with no connection type cannot create one, so the dialog opens
   * with a link to where types are set up. A refusal is a toast and nothing is added.
   *
   * @param realises The outer connection a boundary box stands for, which the new connection is then marked as realising.
   */
  async function addConnection(source: string, target: string, realises?: string) {
    const endType = (id: string) => elementTypes.find((t) => t.id === elements.find((e) => e.id === id)?.element_type_id);
    const type = defaultConnectionType(reference.connectionTypes, [endType(source), endType(target)]);
    if (!type) {
      setConnecting({ source, target, realises });
      return;
    }
    try {
      const created = await projectConnectionApi(projectId).create({ ...blankConnectionValues(type.id, source, target, null, type.default_protocol), activate: false });
      showToast("Connection created.");
      connectionCreated(created.id, realises);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not create the connection."), "error");
    }
  }

  /**
   * Starts a connection between an inner element and the element outside a boundary box, to be marked as realising the box's
   * outer connection once created. The ends follow the outer connection's direction (an output starts at the inner element);
   * the form lets the person change them. Nothing is offered for a box whose outside element the viewer cannot read.
   */
  async function startBoundaryConnection(connectionId: string, elementId: string) {
    const box = layout.boundaries.find((b) => b.connectionId === connectionId);
    const inner = layout.boxes.find((b) => b.elementId === elementId);
    if (!box || !inner || inner.locked) return;
    if (box.locked) {
      showToast("The element outside is not visible to you, so a connection to it cannot be made here.", "error");
      return;
    }
    if (!(await ensureSaved())) return;
    const fromInner = box.shape !== "input";
    await addConnection(fromInner ? elementId : box.outside_element_id, fromInner ? box.outside_element_id : elementId, connectionId);
  }

  function addOuter(connectionId: string) {
    const choice = outerChoices.find((c) => c.connection.id === connectionId);
    if (!choice) return;
    editor.edit((l) => addBoundaries(l, [boundaryFromConnection(choice.connection, choice.side, nextFreePosition(l))]));
  }

  /** Stores what a connection realises at once, then reads the diagram again so the box shows its new coverage. */
  async function setRealises(connection: ArchitectureConnection, outerIds: string[]) {
    await projectConnectionApi(projectId).setRealisations(connection.id, connection.version, outerIds);
    await editor.reload(false);
  }

  /**
   * Creates an element of a type at once, named for its type with a number, inside the diagram's scope element, places it at
   * `at` and selects it with the cursor in its name. A refusal is a toast and nothing is added.
   */
  async function addElementAt(typeId: string, at: { x: number; y: number }) {
    if (!diagram) return;
    const type = elementTypes.find((t) => t.id === typeId);
    try {
      const created = await projectElementApi(projectId).create({
        name: defaultElementName(type?.name ?? "Element", elements.map((e) => e.name)), description: "", display_note: "",
        element_type_id: typeId, parent_id: diagram.scope_element_id, owner: null, symbol_id: null, folder_id: null, activate: false,
        ports: [],
      });
      editor.edit((l) => addBoxes(l, [boxFromElement(created, type, at)]));
      setElements((prev) => [...prev, created]);
      setSelection({ kind: "node", id: created.id });
      setFocusNew(created.id);
      void reloadModelLists();
      void editor.reloadModel();
      showToast("Element created.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not create the element."), "error");
    }
  }

  function addExisting(chosen: ArchitectureElement[]) {
    editor.edit((l) => addBoxes(l, chosen.map((e, i) =>
      boxFromElement(e, elementTypes.find((t) => t.id === e.element_type_id), nextFreePosition(l, i)))));
    setAdding(false);
  }

  /** Adds an empty note with its top-left corner at `at`, selects it and puts the cursor in its text (add, then edit). */
  function addNoteAt(at: { x: number; y: number }) {
    const key = newNoteKey(layout);
    editor.edit((l) => addNote(l, newNote(key, at)));
    setSelection({ kind: "node", id: NOTE_NODE_PREFIX + key });
    setFocusNew(NOTE_NODE_PREFIX + key);
  }

  function addNewNote() {
    addNoteAt(nextFreePosition(layout));
  }

  /**
   * Whether a leader may end at `target`: a box of this diagram (never a note or a boundary box, which have canvas ids of their
   * own) or a free spot. A connection is checked where it is chosen (from the drawn lines).
   */
  function leaderTargetAllowed(target: NoteLeaderTarget): boolean {
    return target.kind !== "element" || layout.boxes.some((b) => b.elementId === target.elementId);
  }

  /** Adds a leader to a note ending at `target` and selects it (add, then edit). The note keeps at most ten. */
  function addLeaderTo(noteKey: string, target: NoteLeaderTarget, start: AttachPoint | null = null) {
    if (!leaderTargetAllowed(target)) return;
    const note = layout.notes.find((n) => n.key === noteKey);
    if (!note || note.leaders.length >= MAX_NOTE_LEADERS) return;
    const key = newLeaderKey(layout);
    editor.edit((l) => addLeader(l, noteKey, newLeader(key, target, start)));
    setSelection({ kind: "leader", id: key });
  }

  /** Adds a leader to a free spot to the right of the note, the keyboard route to drawing one from the note. */
  function addLeaderFrom(noteKey: string) {
    const note = layout.notes.find((n) => n.key === noteKey);
    if (note) {
      const frame = noteFrame(note);
      addLeaderTo(noteKey, { kind: "point", x: Math.round(note.x + frame.width + LEADER_REACH), y: Math.round(note.y + frame.height / 2) });
    }
  }

  /**
   * What a leader dropped on a canvas line ends at: the first connection of that line, when it is this project's (a leader may
   * not name another project's connection), else nothing.
   */
  function connectionOfLine(lineId: string): NoteLeaderTarget | null {
    const line = resolved.edges.find((e) => e.id === lineId);
    const own = line?.connections.find((c) => c.project_id === projectId);
    return own ? { kind: "connection", connectionId: own.id } : null;
  }

  /** The target a canvas drop names, as a leader target (a note or boundary box is not one). */
  function leaderTargetOf(to: GraphLeaderTarget): NoteLeaderTarget | null {
    if (to.kind === "point") return { kind: "point", x: to.x, y: to.y };
    if (to.kind === "edge") return connectionOfLine(to.id);
    return to.id.startsWith(NOTE_NODE_PREFIX) || to.id.startsWith(BOUNDARY_NODE_PREFIX) ? null : { kind: "element", elementId: to.id };
  }

  /** Points a leader at another target (a drag of its end, or the "Points at" list). */
  function pointLeaderAt(leaderKey: string, target: NoteLeaderTarget | null) {
    if (target === null || !leaderTargetAllowed(target)) return;
    editor.edit((l) => setLeaderTarget(l, leaderKey, target));
  }

  /**
   * Routes a line. A line drawn for one connection on its own route, a merged line with a connection chosen in its card that
   * can have one, or the only connection of a line that shares its two boxes with another line, sets that connection's route only
   * (the connection becomes, or stays, a line of its own, which stays the selection); any other line sets the route of its pair of
   * boxes, which every connection on it follows.
   */
  function routeLine(line: DiagramViewEdge, change: LineRouteChange) {
    if (line.source_is_boundary || line.target_is_boundary) return;
    const connectionId = routedConnectionOf(line, chosenConnectionId, sharesItsPair(resolved.edges, line));
    if (connectionId === null) {
      editor.edit((l) => setLineAnchor(l, line.source_element_id, line.target_element_id, change));
      return;
    }
    editor.edit((l) => setConnectionRoute(l, connectionId, line.source_element_id, line.target_element_id, change));
    setChosenConnection(null);
    setSelectConnection(connectionId);
  }

  /** Takes a connection's own route away: it is drawn with the line of its pair of boxes again, and stays the selection. */
  function joinLine(connectionId: string) {
    editor.edit((l) => clearConnectionRoute(l, connectionId));
    setChosenConnection(null);
    setSelectConnection(connectionId);
  }

  /** Opens the diagram of an element's inside; with unsaved changes it first asks, since leaving discards them. */
  async function openInside(elementId: string) {
    try {
      const existing = (await diagramApi.list({ include_archived: false })).find((d) => d.scope_element_id === elementId);
      if (existing) {
        navigate(`${base}/diagrams/${existing.id}`);
        return;
      }
      const box = layout.boxes.find((b) => b.elementId === elementId);
      const created = await diagramApi.create({
        name: `${box?.name ?? "Element"} internals`, purpose: "", scope_element_id: elementId, connection_detail: false,
        folder_id: null, activate: false, populate: true,
      });
      showToast("Diagram created for the element's inside.");
      navigate(`${base}/diagrams/${created.id}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not open the element's inside."), "error");
    }
  }

  async function deleteElement(elementId: string) {
    if (!(await ensureSaved())) return;
    try {
      await projectElementApi(projectId).remove(elementId);
      showToast("Element deleted.");
      setSelection(null);
      reloadModelLists();
      await editor.reload(true);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete this element."), "error");
    }
  }

  /**
   * The canvas's Delete key: removes the selected box, note, boundary box or leader from the diagram (an undoable local edit; the
   * element itself is never touched, so there is no confirmation). A connection is a record of the model with no drawing-only
   * form, so the key says where it is deleted instead of doing nothing.
   */
  function removeSelected(chosen: GraphCanvasSelection) {
    if (!editable) return;
    if (chosen.kind === "leader") {
      editor.edit((l) => removeLeader(l, chosen.id));
      setSelection(null);
      return;
    }
    if (chosen.kind !== "node") {
      showToast("A connection belongs to the model, so the Delete key does not remove it from a drawing. Open the connection to delete it.");
      return;
    }
    if (chosen.id.startsWith(NOTE_NODE_PREFIX)) editor.edit((l) => removeNote(l, chosen.id.slice(NOTE_NODE_PREFIX.length)));
    else if (chosen.id.startsWith(BOUNDARY_NODE_PREFIX)) editor.edit((l) => removeBoundary(l, chosen.id.slice(BOUNDARY_NODE_PREFIX.length)));
    else editor.edit((l) => removeBox(l, chosen.id));
    setSelection(null);
  }

  function flipToggle(toggle: DiagramToggle, on: boolean) {
    // The saved default needs no override; a state that differs from it is kept in the address.
    const without = (list: string[]) => list.filter((id) => id !== toggle.id);
    setToggleOn(on && !toggle.default_on ? [...without(toggleOn), toggle.id] : without(toggleOn));
    setToggleOff(!on && toggle.default_on ? [...without(toggleOff), toggle.id] : without(toggleOff));
  }

  async function storeToggle(next: DiagramToggleValues) {
    const all = toggles.map(toggleValues);
    const merged = next.id && all.some((t) => t.id === next.id) ? all.map((t) => (t.id === next.id ? next : t)) : [...all, next];
    if (await editor.saveToggles(merged)) {
      setToggleForm(null);
      showToast("View switches saved.");
    }
  }

  async function removeToggle(toggle: DiagramToggle) {
    if (await editor.saveToggles(toggles.filter((t) => t.id !== toggle.id).map(toggleValues))) {
      showToast("View switch removed.");
    }
  }

  async function saveDiagramFields(values: DiagramFieldValues) {
    if (!diagram) return;
    setFormError(null);
    const changed = diffDiagramFields(valuesFromDiagram(diagram), values);
    if (Object.keys(changed).length === 0) {
      setEditingDiagram(false);
      return;
    }
    if (await editor.updateFields(changed)) {
      showToast("Diagram updated.");
      setEditingDiagram(false);
    } else {
      setFormError(editor.saveError ?? "Could not update this diagram.");
    }
  }

  async function moveTo(status: ArchitectureRecordStatus) {
    if (!diagram) return;
    try {
      editor.setDiagram(await diagramApi.setStatus(diagram.id, diagram.version, status));
      showToast(`Diagram moved to ${ARCHITECTURE_STATUS_LABEL[status]}.`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the status."), "error");
    }
  }

  const { lifecycle, menuRows } = architectureLifecycle(diagram.status, diagram.allowed_status_moves, moveTo);

  const elementEditor: ElementEditorReference | null = reference.project ? {
    elementTypes, symbols: reference.symbols, symbolUrl: (id) => projectSymbolUrl(projectId, id), orgUsers: reference.orgUsers,
    organizationId: reference.project.organization_id, onSymbolsChanged: reference.reloadSymbols,
  } : null;
  const placed = new Set(layout.boxes.map((b) => b.elementId));
  const candidates = elements.filter((e) => !placed.has(e.id) && !e.is_archived && !isOutOfUse(e.status));
  // What the diagram shows is read on hovering its title (a line of its own showed it on every visit, though it rarely changes).
  const scopeLabel = diagram.scope_element_id
    ? `Inside ${[diagram.scope_element_code && formatCode.code(diagram.scope_element_code), diagram.scope_element_name].filter(Boolean).join(" ") || "an element you cannot read"}`
    : `System context\n${ARCHITECTURE_HELP.systemContext}`;
  const openBoxInside = (nodeId: string) => {
    const box = layout.boxes.find((b) => b.elementId === nodeId);
    if (!box || box.locked) return;
    if (dirty) setLeaveFor(box.elementId);
    else void openInside(box.elementId);
  };

  const toolbar = (
    <div className="row" role="toolbar" aria-label="Diagram editing" style={{ alignItems: "center", gap: "var(--space-2)" }}>
      <EditHistoryButtons editable={editable} canUndo={editor.canUndo} canRedo={editor.canRedo} undo={editor.undo} redo={editor.redo} />
      <button
        type="button" className="btn btn-primary btn-sm" disabled={!editable || !dirty || editor.saving || editor.conflict}
        onClick={() => void saveLayout()} aria-label="Save diagram"
      >
        Save
      </button>
      <DiagramAddMenu
        elementTypes={elementTypes} domains={reference.domains} disabled={!editable}
        onAddType={(typeId) => void addElementAt(typeId, nextFreePosition(layout))}
        onAddExisting={() => setAdding(true)} onAddNote={addNewNote}
        outerConnections={outerChoices.map((c) => ({ id: c.connection.id, label: `${c.connection.unique_code} · ${boundaryOutsideName(c.box)}` }))}
        onAddOuter={addOuter}
        onSetup={canManageTypes ? () => (dirty ? setLeaveForSetup(true) : navigate(SETUP_PATH(projectId))) : undefined}
      />
      <DiagramExportMenu disabled={exporting} onExport={(kind) => void exportDiagram(kind)} />
      {tab === "drawing" && <NoteModeToggle on={placingNote} onChange={chooseNoteMode} disabled={!editable} />}
      {tab === "drawing" && <CommentModeToggle on={commentLayer.commentMode} onChange={chooseCommentMode} />}
      <DiagramSettingsButton
        connectionDetail={diagram.connection_detail} disabled={!editable || editor.saving}
        onConnectionDetailChange={(next) => void editor.updateFields({ connection_detail: next })}
        lineHops={diagram.line_hops} onLineHopsChange={(next) => void editor.updateFields({ line_hops: next })}
        showConnectionNames={diagram.show_connection_names} onShowConnectionNamesChange={(next) => void editor.updateFields({ show_connection_names: next })}
        lineShape={diagram.line_shape} onLineShapeChange={(next) => void editor.updateFields({ line_shape: next })}
        showNotes={showNotes} onShowNotesChange={setShowNotes}
        showComments={commentLayer.showComments} onShowCommentsChange={commentLayer.setShowComments}
        showResolved={commentLayer.showResolved} onShowResolvedChange={commentLayer.setShowResolved}
        snapToGrid={snap.on} onSnapToGridChange={snap.setOn}
        attachPointsAlways={attachPoints.always} onAttachPointsAlwaysChange={attachPoints.setAlways}
      />
      {dirty && <span className="text-muted" role="status">Unsaved changes.</span>}
    </div>
  );
  const selectionColumn = (
    <div className="stack" style={{ flex: "1 1 18rem", minWidth: 0 }}>
      <DiagramSelectionPanel
        maxHeight={canvasHeight}
        projectId={projectId} selection={selection} boxes={layout.boxes} notes={layout.notes} edges={resolved.edges} anchors={layout.anchors} lineEnds={lineEnds} defaultShape={diagram.line_shape} hidden={resolved.hidden} editable={editable}
        boundaries={layout.boundaries} connectionsById={connectionsById} realisedBy={realisedBy}
        onRemoveBoundary={(box) => { editor.edit((l) => removeBoundary(l, box.connectionId)); setSelection(null); }}
        onConnectBoundary={(box, elementId) => void startBoundaryConnection(box.connectionId, elementId)}
        onSetRealises={setRealises}
        onComment={(target) => {
          // A line has no position of its own here, so the comment starts at the middle of the boxes it joins.
          const line = target.kind === "edge" ? resolved.edges.find((e) => e.id === target.id) : undefined;
          const from = layout.boxes.find((b) => b.elementId === line?.source_element_id);
          const to = layout.boxes.find((b) => b.elementId === line?.target_element_id);
          const fromFrame = from ? boxFrame(from) : undefined;
          const toFrame = to ? boxFrame(to) : undefined;
          const at = from && to && fromFrame && toFrame
            ? { x: (from.x + fromFrame.width / 2 + to.x + toFrame.width / 2) / 2, y: (from.y + fromFrame.height / 2 + to.y + toFrame.height / 2) / 2 }
            : { x: 0, y: 0 };
          setTabChoice("");
          chooseCommentMode(true);
          commentLayer.startAt(pinPlaceOf(at, target, layout.boxes, drawnLines(resolved.edges, drawnEdgeIds)));
        }}
        elements={elements} connectionTypes={reference.connectionTypes}
        elementEditor={elementEditor} elementTypes={elementTypes} domains={reference.domains} onSaveElement={saveElementFields} onSaveConnection={saveConnectionFields}
        focusNew={focusNew} onFocused={() => setFocusNew(null)}
        chosenConnectionId={chosenConnectionId}
        onChooseConnection={(connectionId) => setChosenConnection(connectionId !== null && selection?.kind === "edge" ? { edgeId: selection.id, connectionId } : null)}
        onEditConnection={(connection) => { setConnectionFormError(null); setEditingConnection(connection); }}
        onAddPort={portsApi.add} onChangePort={portsApi.change} onRemovePort={portsApi.remove}
        onRemoveBox={(box) => { editor.edit((l) => removeBox(l, box.elementId)); setSelection(null); }}
        onConnect={(box, targetId) => void startConnection(box.elementId, targetId)}
        onOpenInside={(box) => (dirty ? setLeaveFor(box.elementId) : void openInside(box.elementId))}
        stateMachinesOf={(elementId) => machinesOf.get(elementId) ?? []} onOpenMachine={openMachine}
        onDeleteElement={(box) => void deleteElement(box.elementId)}
        onAnchorChange={routeLine} onJoinLine={joinLine}
        drawnEdgeIds={drawnEdgeIds}
        onNoteChange={(key, patch) => editor.edit((l) => updateNote(l, key, patch))}
        onAddLeader={addLeaderFrom}
        onSelectLeader={(key) => setSelection({ kind: "leader", id: key })}
        onSelectNote={(key) => setSelection({ kind: "node", id: NOTE_NODE_PREFIX + key })}
        onLeaderTarget={(key, target) => pointLeaderAt(key, target)}
        onLeaderChange={(key, change: Partial<EditorLeader>) => editor.edit((l) => patchLeader(l, key, change))}
        onRemoveLeader={(key) => { editor.edit((l) => removeLeader(l, key)); setSelection(null); }}
        onRemoveNote={(key) => { editor.edit((l) => removeNote(l, key)); setSelection(null); }}
      />
    </div>
  );

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="architecture_diagram" artefactId={diagram.id} refreshToken={recordActivityKey(diagram)} />}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="architecture_diagram" artefactId={diagram.id} onChanged={() => void editor.reload(false)} />}
    >
      <RecordHeader
        recordLabel="Diagram"
        title={<Tooltip label={scopeLabel} wrap>{diagram.name}</Tooltip>}
        titleAddon={<DiagramSwitcher kind="block" projectId={projectId} currentId={diagram.id} />}
        code={diagram.unique_code}
        tags={<RecordTags projectId={projectId} artefactType="architecture_diagram" artefactId={diagram.id} />}
        back={{ to: architectureTabPath(projectId, "diagrams"), label: "Diagrams" }}
        badges={
          <>
            {diagram.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[diagram.status]}>{ARCHITECTURE_STATUS_LABEL[diagram.status]}</Badge>
          </>
        }
        version={diagram.version}
        subtitle={diagram.purpose ? markdownPlainText(diagram.purpose) : undefined}
        onEdit={editable ? () => setEditingDiagram(true) : undefined}
        actions={[...menuRows, archive.item, remove.item]}
        lifecycle={lifecycle}
      />
      {archive.dialog}
      {remove.dialog}

      {editor.conflict && (
        <div role="alert" className="card stack">
          <p>
            Someone else saved this diagram after you opened it, so your changes were not stored. Reload to continue from
            their version; your unsaved changes will be lost.
          </p>
          <button type="button" className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => void editor.reload(true)}>
            Reload diagram
          </button>
        </div>
      )}
      {editor.saveError && !editingDiagram && <p role="alert" style={{ color: "var(--color-danger)" }}>{editor.saveError}</p>}

      <Tabs idPrefix="diagram-editor" tabs={[...EDITOR_TABS]} active={tab} onChange={(next) => setTabChoice(next === "drawing" ? "" : next)} />

      {tab !== "configuration" && toolbar}

      {tab === "drawing" && (
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }} {...tabPanelProps("diagram-editor", "drawing")}>
          <div className="stack" style={{ flex: "3 1 32rem", minWidth: 0 }}>
            {diagram.scope_element_id && layout.boxes.length === 0 && (
              <p className="text-muted" role="status">
                Nothing is inside this element yet. Use Add to diagram, then a type, to create its sub-elements here; each becomes a child of {diagram.scope_element_name || "it"}.
              </p>
            )}
            <div ref={setCanvasBox}>
            <GraphCanvas
              nodes={nodes} edges={edges} leaders={leaders} ariaLabel={`Diagram ${diagram.name}`} height={canvasHeight}
              readOnly={!editable} resizable fitMaxZoom={1} showViewToggle={false} selected={selection} {...commentLayer.canvasProps} {...snap.canvasProps} {...attachPoints.canvasProps} lineHops={diagram.line_hops} centerOn={selectCenter ?? commentLayer.canvasProps.centerOn}
              // A note just placed from Note mode must not lose its selection when the same click clears it on the canvas.
              onSelect={(next) => { if (next !== null || !placingNote) { setSelection(next); setFocusNew(null); } }}
              onCanvasClick={(at) => {
                if (placingNote) addNoteAt({ x: Math.round(at.x - NOTE_WIDTH / 2), y: Math.round(at.y - NOTE_HEIGHT / 2) });
              }}
              onLeaderTargetChange={(leaderKey, target) => pointLeaderAt(leaderKey, leaderTargetOf(target))}
              onLeaderPointsChange={(leaderKey, points) => editor.edit((l) => patchLeader(l, leaderKey, { points }))}
              onConnectEmpty={(source, to, via) => {
                // A line drawn from a note and released on a box, a line or empty canvas is a leader; a box starts no such line.
                if (!source.startsWith(NOTE_NODE_PREFIX)) return;
                const target = leaderTargetOf(to);
                if (target) addLeaderTo(source.slice(NOTE_NODE_PREFIX.length), target, via.sourcePoint ?? null);
              }}
              onNodesMove={(moves) => editor.edit((l) => moveItems(l, moves))}
              onNodesResize={(changes) => editor.edit((l) => resizeItems(l, changes))}
              onEdgeAnchorChange={(edgeId, change) => {
                const line = resolved.edges.find((e) => e.id === edgeId);
                if (line) routeLine(line, change);
              }}
              onEdgePointsChange={(edgeId, points) => {
                const line = resolved.edges.find((e) => e.id === edgeId);
                if (line) routeLine(line, { points });
              }}
              onConnect={(source, target, via) => {
                // A line from a note to a box is a leader, not a connection.
                if (source.startsWith(NOTE_NODE_PREFIX)) {
                  const to = leaderTargetOf({ kind: "node", id: target });
                  if (to) addLeaderTo(source.slice(NOTE_NODE_PREFIX.length), to, via?.sourcePoint ?? null);
                  return;
                }
                void startConnection(source, target);
              }}
              onDelete={removeSelected} deleteKeyScope="page" onNodeOpen={openBoxInside}
              onDropItem={(payload, at) => {
                if (payload.startsWith(PALETTE_TYPE_PREFIX)) void addElementAt(payload.slice(PALETTE_TYPE_PREFIX.length), at);
              }}
            />
            </div>
          </div>
          {selectionColumn}
        </div>
      )}

      {tab === "outline" && (
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }} {...tabPanelProps("diagram-editor", "outline")}>
          <div className="stack" style={{ flex: "3 1 32rem", minWidth: 0 }}>
            <DiagramOutline
              boxes={layout.boxes} notes={layout.notes} boundaries={layout.boundaries} anchors={layout.anchors} covered={new Set(realisedBy.keys())}
              edges={resolved.edges} drawnEdgeIds={drawnEdgeIds} parents={model.parents} hidden={resolved.hidden} descriptions={descriptions}
              selection={selection} onSelect={setSelection}
              stateMachinesOf={(elementId) => machinesOf.get(elementId) ?? []} onOpenMachine={openMachine}
            />
          </div>
          {selectionColumn}
        </div>
      )}

      {tab === "comments" && (
        <div className="stack" {...tabPanelProps("diagram-editor", "comments")}>
          <DiagramCommentsPanel
            layer={commentLayer} describe={blockPinDescriber(layout.boxes, drawnLines(resolved.edges, drawnEdgeIds))} currentUserId={currentUser?.id}
            onShow={() => setTabChoice("")}
          />
        </div>
      )}

      {tab === "configuration" && (
        <div className="stack" {...tabPanelProps("diagram-editor", "configuration")}>
          {dirty && <p className="text-muted" role="status">The drawing has unsaved changes; they are kept and are saved from the Drawing tab.</p>}
          <DiagramTogglesPanel
            toggles={toggles} editable={editable} onFlip={flipToggle}
            onAdd={() => setToggleForm({})} onEdit={(t) => setToggleForm({ initial: toggleValues(t) })} onRemove={(t) => void removeToggle(t)}
          />
        </div>
      )}

      {editingDiagram && (
        <DiagramFormModal
          initial={diagram} elements={elements} projectId={projectId} error={formError}
          onCancel={() => { setEditingDiagram(false); setFormError(null); }} onSave={saveDiagramFields}
        />
      )}
      {editingConnection && (
        <ConnectionFormModal
          initial={editingConnection} connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} domains={reference.domains} elements={elements}
          projectId={projectId} error={connectionFormError}
          onCancel={() => { setEditingConnection(null); setConnectionFormError(null); }} onSave={saveConnectionEdit}
        />
      )}
      {adding && <AddElementsDialog projectId={projectId} candidates={candidates} elementTypes={elementTypes} domains={reference.domains} onCancel={() => setAdding(false)} onAdd={addExisting} />}
      {connecting && (
        <ConnectionFormModal
          connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} domains={reference.domains} elements={elements}
          projectId={projectId} defaultSourceId={connecting.source} defaultTargetId={connecting.target} error={createConnection.error}
          setupPath={CONNECTION_SETUP_PATH(projectId)}
          onCancel={() => { setConnecting(null); createConnection.clearError(); }} onSave={createConnection.create}
        />
      )}
      {leaveForSetup && (
        <ConfirmDialog
          title="Leave this diagram?" message="Your unsaved changes to this diagram will be lost." confirmLabel="Leave"
          onConfirm={() => { setLeaveForSetup(false); navigate(SETUP_PATH(projectId)); }} onCancel={() => setLeaveForSetup(false)}
        />
      )}
      {leaveForMachine && (
        <ConfirmDialog
          title="Leave this diagram?" message="Your unsaved changes to this diagram will be lost." confirmLabel="Leave"
          onConfirm={() => { const to = leaveForMachine; setLeaveForMachine(null); navigate(to); }} onCancel={() => setLeaveForMachine(null)}
        />
      )}
      {leaveFor && (
        <ConfirmDialog
          title="Leave this diagram?" message="Your unsaved changes to this diagram will be lost." confirmLabel="Leave"
          onConfirm={() => { const id = leaveFor; setLeaveFor(null); void openInside(id); }} onCancel={() => setLeaveFor(null)}
        />
      )}
      {toggleForm && (
        <ToggleFormModal
          initial={toggleForm.initial} elementTypes={elementTypes} connectionTypes={reference.connectionTypes} domains={reference.domains}
          elements={elements} connections={connections} onCancel={() => setToggleForm(null)} onSave={(t) => void storeToggle(t)}
        />
      )}
    </DetailLayout>
  );
}
