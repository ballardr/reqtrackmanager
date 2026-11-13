/**
 * Module: modules/architecture/DiagramEditorPage
 *
 * One diagram as a routed page and its editor (`/projects/:projectId/modules/architecture/diagrams/:diagramId`, also the
 * target other records' links follow). The record header sits above two tabs (`?tab=configuration`; Drawing is the default):
 * Drawing holds a toolbar (Undo, Redo, Save, the Add to diagram menu, Export), the shared graph canvas, the Outline and the
 * Selection card; Configuration holds the connection-detail setting and the view switches. Links and Activity are in the aside.
 * The pending layout, selection and undo history belong to the page, so a change of tab loses none of them.
 *
 * Editing model: boxes, notes, line anchors and boundary boxes are edited locally (move, resize, add, remove, drop from the Add menu, drag a line
 * between two boxes, drag a line's end to another attach point or choose it in the Selection card) with undo and redo, and stored together by Save, which quotes the diagram's version; a 409 offers a reload
 * instead of overwriting a newer save. Creating a connection or deleting an element writes to the model at once, so a
 * pending layout is saved first. Taking a box off the diagram never deletes its element; deleting the element is a separate,
 * confirmed action. View switches are stored when changed, but flipping one on the page changes only the address.
 * An Outline card (elements as a tree, lines as a table) is the text alternative to the canvas and shares its selection; the
 * canvas is keyboard operable (arrows move, Alt+arrows resize, Delete removes the box from the diagram) and the selection card
 * can start a connection from a list. Export (PNG, SVG, Mermaid text, copy Mermaid) saves a pending layout first, then asks
 * the server for the saved diagram drawn for the switch states on the page.
 * A diagram of an element's inside can draw the connections that cross the element's boundary as boundary boxes (Add to diagram,
 * "Outside this element"); a line drawn from an inner element to a box (or the box's "Connect to" list) creates a connection and
 * marks it as realising the outer connection, and a line's Selection card can set what it realises.
 * Lines, bridging and roll-up are worked out in the browser from the diagram's model data (`GET .../model`) by
 * `diagramLines`, so an added box or a flipped switch redraws at once; the server's resolved view (`GET .../view`) gives
 * the boxes, notes and switches on load and stays the authority for the SVG and documents.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { downloadBlob } from "../../utils/download";
import { svgToPngBlob } from "../../utils/svgToPng";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Badge } from "../../components/Badge";
import { MenuButton } from "../../components/MenuButton";
import { DetailLayout } from "../../components/DetailLayout";
import { GraphCanvas, type GraphCanvasSelection } from "../../components/GraphCanvas";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { useFillViewportHeight } from "../../hooks/useFillViewportHeight";
import { RecordHeader } from "../../components/RecordHeader";
import { FieldHelp } from "../../components/FieldHelp";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { resolveEffectiveTheme, useTheme } from "../../context/ThemeContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useUrlChoice, useUrlList } from "../../hooks/useUrlFilter";
import { architectureTabPath } from "./architectureTabs";
import { ARCHITECTURE_HELP } from "./help";
import { capabilitiesApi, projectConnectionApi, projectDiagramApi, projectElementApi, projectSymbolUrl } from "./api";
import { diffDiagramFields, diffElementFields, valuesFromDiagram, valuesFromElement } from "./architectureFields";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { AddElementsDialog } from "./AddElementsDialog";
import { ConnectionFormModal } from "./ConnectionFormModal";
import {
  addBoundaries, addBoxes, addNote, boundaryFromConnection, boundaryNodeId, boundaryOutsideName, boxFromElement, canvasEdges,
  canvasNodes, editNote, moveItems, newNoteKey, nextFreePosition, removeBoundary, removeBox, removeNote, resizeItems,
  setLineAnchor, BOUNDARY_NODE_PREFIX, NOTE_HEIGHT, NOTE_NODE_PREFIX, NOTE_WIDTH,
} from "./diagramEditorModel";
import { outerSide } from "./diagramResolver";
import { exportFileName, toggleStates, type DiagramExportKind } from "./diagramExport";
import { DiagramFormModal } from "./DiagramFormModal";
import { DiagramAddMenu } from "./DiagramAddMenu";
import { DiagramOutline } from "./DiagramOutline";
import { ElementFormModal } from "./ElementFormModal";
import { DiagramSelectionPanel } from "./DiagramSelectionPanel";
import { DiagramSettingsButton } from "./DiagramSettingsButton";
import { DiagramTogglesPanel } from "./DiagramTogglesPanel";
import { resolveDiagram, type ResolvedDiagram } from "./diagramLines";
import { PALETTE_TYPE_PREFIX, toggleValues } from "./diagramToggles";
import { NewElementDialog } from "./NewElementDialog";
import { ToggleFormModal } from "./ToggleFormModal";
import { useArchitectureReference } from "./useArchitectureReference";
import { useCreateConnection } from "./useCreateConnection";
import { useDiagramEditor } from "./useDiagramEditor";
import { useSymbolSvgs } from "./useSymbolSvgs";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureConnection, type ArchitectureElement,
  type ArchitectureRecordStatus, type DiagramFieldValues, type DiagramToggle, type DiagramToggleValues, type ElementFieldValues, type PortValues, isOutOfUse,
} from "./types";

/** The smallest canvas height; a shorter window scrolls instead. Above it the canvas fills the window below its tabs. */
const CANVAS_MIN_HEIGHT = 300;

/** The project's Element Types settings. */
const SETUP_PATH = (projectId: string) => `/projects/${projectId}/admin/architecture/architecture-element-types`;

const EDITOR_TABS = [
  { key: "drawing", label: "Drawing" },
  { key: "outline", label: "Outline" },
  { key: "configuration", label: "Configuration" },
] as const;
type EditorTab = (typeof EDITOR_TABS)[number]["key"];

const NO_LINES: ResolvedDiagram = { edges: [], hidden: new Set(), internal: new Map() };

export function DiagramEditorPage() {
  const { projectId = "", diagramId = "" } = useParams<{ projectId: string; diagramId: string }>();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const reference = useArchitectureReference(projectId);
  const diagramApi = useMemo(() => projectDiagramApi(projectId), [projectId]);
  const base = `/projects/${projectId}/modules/architecture`;

  const [toggleOn, setToggleOn] = useUrlList("toggle_on");
  const [toggleOff, setToggleOff] = useUrlList("toggle_off");
  // The Drawing tab is the default and so leaves the address unmarked; the pending layout, selection and undo history live
  // in this page, so they survive a change of tab.
  const [tabChoice, setTabChoice] = useUrlChoice("tab", ["outline", "configuration"] as const);
  const tab: EditorTab = tabChoice || "drawing";
  const editor = useDiagramEditor(projectId, diagramId);
  const { diagram, view, model, layout, dirty } = editor;

  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [connections, setConnections] = useState<ArchitectureConnection[]>([]);
  const [selection, setSelection] = useState<GraphCanvasSelection | null>(null);
  const [canvasBox, setCanvasBox] = useState<HTMLElement | null>(null);
  const canvasHeight = useFillViewportHeight(canvasBox, CANVAS_MIN_HEIGHT);
  const [editingDiagram, setEditingDiagram] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newElement, setNewElement] = useState<{ typeId: string; at: { x: number; y: number } } | null>(null);
  const [newElementError, setNewElementError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<{ source: string; target: string; realises?: string } | null>(null);
  const [toggleForm, setToggleForm] = useState<{ initial?: DiagramToggleValues } | null>(null);
  const [leaveFor, setLeaveFor] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [canManageTypes, setCanManageTypes] = useState(false);
  const [leaveForSetup, setLeaveForSetup] = useState(false);
  const [editingElement, setEditingElement] = useState<ArchitectureElement | null>(null);
  const [elementFormError, setElementFormError] = useState<string | null>(null);

  const reloadModelLists = useCallback(() => {
    if (!projectId) return;
    const elementApi = projectElementApi(projectId);
    Promise.all([elementApi.list({ open_only: true }), elementApi.listShared({ open_only: true })])
      .then(([own, shared]) => setElements([...own, ...shared]))
      .catch(() => setElements([]));
    projectConnectionApi(projectId).list({ open_only: true }).then(setConnections).catch(() => setConnections([]));
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

  /** Stores the edited element, then redraws from the new data; the pending layout is kept (a merge, not a replace). */
  async function saveElementEdit(values: ElementFieldValues) {
    const element = editingElement;
    if (!element) return;
    setElementFormError(null);
    const changed = diffElementFields(valuesFromElement(element), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditingElement(null);
      return;
    }
    try {
      await projectElementApi(projectId).update(element.id, element.version, changed);
      showToast("Element updated.");
      setEditingElement(null);
      reloadModelLists();
      void editor.reload(false);
    } catch (err) {
      setElementFormError(toErrorMessage(err, "Could not update this element."));
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

  const createConnection = useCreateConnection(projectId, (id) => {
    const outerId = connecting?.realises;
    setConnecting(null);
    reloadModelLists();
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
    })();
  });

  // A switch's state on this page: the address overrides the saved default (the choice is never stored).
  const toggles = useMemo(
    () => (view?.toggles ?? []).map((t) => ({ ...t, on: toggleOff.includes(t.id) ? false : toggleOn.includes(t.id) || t.default_on })),
    [view, toggleOn, toggleOff],
  );
  const connectionDetail = diagram?.connection_detail ?? false;
  const scopeId = diagram?.scope_element_id ?? null;
  const resolved = useMemo(
    () => (model
      ? resolveDiagram(model, {
        placed: layout.boxes.map((b) => b.elementId), togglesOff: new Set(toggles.filter((t) => !t.on).map((t) => t.id)), connectionDetail,
        scopeId, boundaries: layout.boundaries.map((b) => ({ id: boundaryNodeId(b.connectionId), connectionId: b.connectionId })),
      })
      : NO_LINES),
    [model, layout.boxes, layout.boundaries, toggles, connectionDetail, scopeId],
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

  const symbolSvg = useSymbolSvgs(projectId, layout.boxes.map((b) => b.symbol_id));
  const effectiveTheme = resolveEffectiveTheme(theme);
  const nodes = useMemo(
    () => canvasNodes(layout, {
      theme: effectiveTheme, symbolSvg, lockedLabel: (code) => `${code} (not visible)`, emptyNote: "Empty note", noteCaption: "Note",
      hidden: resolved.hidden, covered: new Set(realisedBy.keys()), coverageLabel: (isCovered) => (isCovered ? "Covered" : "Not covered"),
    }),
    [layout, effectiveTheme, symbolSvg, resolved.hidden, realisedBy],
  );
  const edges = useMemo(
    () => canvasEdges(resolved.edges, layout, resolved.hidden, effectiveTheme),
    [resolved, layout, effectiveTheme],
  );

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
    setConnecting({ source, target });
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
    setConnecting({
      source: fromInner ? elementId : box.outside_element_id, target: fromInner ? box.outside_element_id : elementId, realises: connectionId,
    });
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

  async function createElementAt(name: string) {
    if (!newElement || !diagram) return;
    setNewElementError(null);
    try {
      const created = await projectElementApi(projectId).create({
        name, description: "", element_type_id: newElement.typeId, parent_id: diagram.scope_element_id, owner: null,
        symbol_id: null, activate: false, ports: [],
      });
      const type = elementTypes.find((t) => t.id === created.element_type_id);
      editor.edit((l) => addBoxes(l, [boxFromElement(created, type, newElement.at)]));
      setSelection({ kind: "node", id: created.id });
      setNewElement(null);
      reloadModelLists();
      void editor.reloadModel();
      showToast("Element created.");
    } catch (err) {
      setNewElementError(toErrorMessage(err, "Could not create the element."));
    }
  }

  function addExisting(chosen: ArchitectureElement[]) {
    editor.edit((l) => addBoxes(l, chosen.map((e, i) =>
      boxFromElement(e, elementTypes.find((t) => t.id === e.element_type_id), nextFreePosition(l, i)))));
    setAdding(false);
  }

  function addNewNote() {
    const key = newNoteKey(layout);
    const at = nextFreePosition(layout);
    editor.edit((l) => addNote(l, { key, id: null, text: "", x: at.x, y: at.y, width: NOTE_WIDTH, height: NOTE_HEIGHT }));
    setSelection({ kind: "node", id: NOTE_NODE_PREFIX + key });
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
        activate: false, populate: true,
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

  /** Removes the selected box or note from the diagram (an undoable local edit; the element itself is never touched). */
  function removeSelected(chosen: GraphCanvasSelection) {
    if (!editable || chosen.kind !== "node") return;
    if (chosen.id.startsWith(NOTE_NODE_PREFIX)) editor.edit((l) => removeNote(l, chosen.id.slice(NOTE_NODE_PREFIX.length)));
    else if (chosen.id.startsWith(BOUNDARY_NODE_PREFIX)) editor.edit((l) => removeBoundary(l, chosen.id.slice(BOUNDARY_NODE_PREFIX.length)));
    else editor.edit((l) => removeBox(l, chosen.id));
    setSelection(null);
  }

  /**
   * Exports the saved diagram as the server draws it for the switch states on this page. A pending layout is saved first,
   * since the export is of the stored diagram.
   */
  async function exportDiagram(kind: DiagramExportKind) {
    if (!diagram || exporting) return;
    setExporting(true);
    try {
      if (!(await ensureSaved())) return;
      const states = toggleStates(toggles);
      const file = (extension: string) => exportFileName(diagram.unique_code, diagram.name, extension);
      if (kind === "svg") {
        downloadBlob(new Blob([await diagramApi.svg(diagram.id, states)], { type: "image/svg+xml" }), file("svg"));
      } else if (kind === "png") {
        downloadBlob(await svgToPngBlob(await diagramApi.svg(diagram.id, states)), file("png"));
      } else if (kind === "mermaid") {
        downloadBlob(new Blob([await diagramApi.mermaid(diagram.id, states)], { type: "text/plain" }), file("mmd"));
      } else {
        await navigator.clipboard.writeText(await diagramApi.mermaid(diagram.id, states));
        showToast("Mermaid text copied.");
        return;
      }
      showToast("Diagram exported.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not export the diagram."), "error");
    } finally {
      setExporting(false);
    }
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

  const placed = new Set(layout.boxes.map((b) => b.elementId));
  const candidates = elements.filter((e) => !placed.has(e.id) && !e.is_archived && !isOutOfUse(e.status));
  const scopeLabel = diagram.scope_element_id ? (
    `Inside ${[diagram.scope_element_code, diagram.scope_element_name].filter(Boolean).join(" ") || "an element you cannot read"}`
  ) : (
    <>System context <FieldHelp label="System context" help={ARCHITECTURE_HELP.systemContext} /></>
  );
  const openBoxInside = (nodeId: string) => {
    const box = layout.boxes.find((b) => b.elementId === nodeId);
    if (!box || box.locked) return;
    if (dirty) setLeaveFor(box.elementId);
    else void openInside(box.elementId);
  };

  const toolbar = (
    <div className="row" role="toolbar" aria-label="Diagram editing" style={{ alignItems: "center", gap: "var(--space-2)" }}>
      <button type="button" className="btn btn-sm" disabled={!editable || !editor.canUndo} onClick={editor.undo}>Undo</button>
      <button type="button" className="btn btn-sm" disabled={!editable || !editor.canRedo} onClick={editor.redo}>Redo</button>
      <button
        type="button" className="btn btn-primary btn-sm" disabled={!editable || !dirty || editor.saving || editor.conflict}
        onClick={() => void saveLayout()}
      >
        Save
      </button>
      <DiagramAddMenu
        elementTypes={elementTypes} disabled={!editable}
        onAddType={(typeId) => setNewElement({ typeId, at: nextFreePosition(layout) })}
        onAddExisting={() => setAdding(true)} onAddNote={addNewNote}
        outerConnections={outerChoices.map((c) => ({ id: c.connection.id, label: `${c.connection.unique_code} · ${boundaryOutsideName(c.box)}` }))}
        onAddOuter={addOuter}
        onSetup={canManageTypes ? () => (dirty ? setLeaveForSetup(true) : navigate(SETUP_PATH(projectId))) : undefined}
      />
      <MenuButton
        label="Export" menuLabel="Export diagram" disabled={exporting}
        items={[
          { label: "PNG image", group: "Image", onSelect: () => void exportDiagram("png") },
          { label: "SVG image", group: "Image", onSelect: () => void exportDiagram("svg") },
          { label: "Download Mermaid text", key: "mermaid", group: "Text", onSelect: () => void exportDiagram("mermaid") },
          { label: "Copy Mermaid text", key: "copy-mermaid", group: "Text", onSelect: () => void exportDiagram("copy-mermaid") },
        ]}
      />
      <DiagramSettingsButton
        connectionDetail={diagram.connection_detail} disabled={!editable || editor.saving}
        onConnectionDetailChange={(next) => void editor.updateFields({ connection_detail: next })}
      />
      {dirty && <span className="text-muted" role="status">Unsaved changes.</span>}
    </div>
  );
  const selectionColumn = (
    <div className="stack" style={{ flex: "1 1 18rem", minWidth: 0 }}>
      <DiagramSelectionPanel
        projectId={projectId} selection={selection} boxes={layout.boxes} notes={layout.notes} edges={resolved.edges} anchors={layout.anchors} hidden={resolved.hidden} editable={editable}
        boundaries={layout.boundaries} connectionsById={connectionsById} realisedBy={realisedBy}
        onRemoveBoundary={(box) => { editor.edit((l) => removeBoundary(l, box.connectionId)); setSelection(null); }}
        onConnectBoundary={(box, elementId) => void startBoundaryConnection(box.connectionId, elementId)}
        onSetRealises={setRealises}
        elements={elements} connectionTypes={reference.connectionTypes}
        onEditElement={(box) => { setElementFormError(null); setEditingElement(elements.find((e) => e.id === box.elementId) ?? null); }}
        onAddPort={portsApi.add} onChangePort={portsApi.change} onRemovePort={portsApi.remove}
        onRemoveBox={(box) => { editor.edit((l) => removeBox(l, box.elementId)); setSelection(null); }}
        onConnect={(box, targetId) => void startConnection(box.elementId, targetId)}
        onOpenInside={(box) => (dirty ? setLeaveFor(box.elementId) : void openInside(box.elementId))}
        onDeleteElement={(box) => void deleteElement(box.elementId)}
        onAnchorChange={(line, change) => editor.edit((l) => setLineAnchor(l, line.source_element_id, line.target_element_id, change))}
        onEditNote={(key, text) => editor.edit((l) => editNote(l, key, text))}
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
        title={diagram.name}
        code={diagram.unique_code}
        tagsInline tags={<RecordTags inline projectId={projectId} artefactType="architecture_diagram" artefactId={diagram.id} />}
        back={{ to: architectureTabPath(projectId, "diagrams"), label: "Diagrams" }}
        badges={
          <>
            {diagram.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[diagram.status]}>{ARCHITECTURE_STATUS_LABEL[diagram.status]}</Badge>
          </>
        }
        version={diagram.version}
        subtitle={<>{scopeLabel}{diagram.purpose ? ` · ${diagram.purpose}` : ""}</>}
        onEdit={editable ? () => setEditingDiagram(true) : undefined}
        actions={[archive.item, remove.item]}
        stateMenu={<ArchitectureStatusControls status={diagram.status} moves={diagram.allowed_status_moves} onMove={moveTo} />}
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
              nodes={nodes} edges={edges} ariaLabel={`Diagram ${diagram.name}`} height={canvasHeight}
              readOnly={!editable} resizable fitMaxZoom={1} showViewToggle={false} selected={selection} onSelect={setSelection}
              onNodesMove={(moves) => editor.edit((l) => moveItems(l, moves))}
              onNodesResize={(changes) => editor.edit((l) => resizeItems(l, changes))}
              onEdgeAnchorChange={(edgeId, change) => {
                const line = resolved.edges.find((e) => e.id === edgeId);
                if (line && !line.source_is_boundary && !line.target_is_boundary) editor.edit((l) => setLineAnchor(l, line.source_element_id, line.target_element_id, change));
              }}
              onConnect={(source, target) => void startConnection(source, target)} onDelete={removeSelected} onNodeOpen={openBoxInside}
              onDropItem={(payload, at) => {
                if (payload.startsWith(PALETTE_TYPE_PREFIX)) setNewElement({ typeId: payload.slice(PALETTE_TYPE_PREFIX.length), at });
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
              boxes={layout.boxes} notes={layout.notes} boundaries={layout.boundaries} covered={new Set(realisedBy.keys())}
              edges={resolved.edges} parents={model.parents} hidden={resolved.hidden}
              selection={selection} onSelect={setSelection}
            />
          </div>
          {selectionColumn}
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
      {editingElement && reference.project && (
        <ElementFormModal
          initial={editingElement} elementTypes={elementTypes} connectionTypes={reference.connectionTypes}
          candidates={elements.filter((e) => !e.shared)} symbols={reference.symbols} symbolUrl={(id) => projectSymbolUrl(projectId, id)}
          orgUsers={reference.orgUsers} organizationId={reference.project.organization_id} projectId={projectId} error={elementFormError}
          onCancel={() => { setEditingElement(null); setElementFormError(null); }} onSave={saveElementEdit}
        />
      )}
      {adding && <AddElementsDialog projectId={projectId} candidates={candidates} elementTypes={elementTypes} onCancel={() => setAdding(false)} onAdd={addExisting} />}
      {newElement && (
        <NewElementDialog
          typeName={elementTypes.find((t) => t.id === newElement.typeId)?.name ?? "element"} error={newElementError}
          onCancel={() => { setNewElement(null); setNewElementError(null); }} onCreate={(name) => void createElementAt(name)}
        />
      )}
      {connecting && (
        <ConnectionFormModal
          connectionTypes={reference.connectionTypes} elementTypes={reference.elementTypes} elements={elements}
          projectId={projectId} defaultSourceId={connecting.source} defaultTargetId={connecting.target} error={createConnection.error}
          onCancel={() => { setConnecting(null); createConnection.clearError(); }} onSave={createConnection.create}
        />
      )}
      {leaveForSetup && (
        <ConfirmDialog
          title="Leave this diagram?" message="Your unsaved changes to this diagram will be lost." confirmLabel="Leave"
          onConfirm={() => { setLeaveForSetup(false); navigate(SETUP_PATH(projectId)); }} onCancel={() => setLeaveForSetup(false)}
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
          initial={toggleForm.initial} elementTypes={elementTypes} connectionTypes={reference.connectionTypes}
          elements={elements} connections={connections} onCancel={() => setToggleForm(null)} onSave={(t) => void storeToggle(t)}
        />
      )}
    </DetailLayout>
  );
}
