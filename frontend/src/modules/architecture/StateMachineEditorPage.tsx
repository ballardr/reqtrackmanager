/**
 * Module: modules/architecture/StateMachineEditorPage
 *
 * One state machine diagram as a routed page and its editor
 * (`/projects/:projectId/modules/architecture/state-machine-diagrams/:diagramId`, also the target other records' links and
 * search results follow; `?state=` opens it with that state selected). The record header sits above four tabs (`?tab=`;
 * Drawing is the default): Drawing (toolbar, the shared graph canvas, the Selection card and the toolbar's Validation list), Outline (states
 * as a tree, transitions as a table), Comments and Configuration (the diagram's details). Links and Activity are in the aside.
 *
 * Editing model: what a state or transition *is* (name, kind, entry, exit and do lines, event, guard, action) is stored
 * at once by its form, because the validation and the state's code come from the server. What the drawing *looks like*
 * (a state's position, size and nesting, a transition's attach points) is edited locally with undo and redo and stored together
 * by Save, which quotes the diagram's version; a stale version offers a reload instead of overwriting a newer save. A state
 * is added at once, with a default name, by choosing it in the Add to diagram menu or dropping it on the canvas; it is then
 * selected with the cursor in its name, and its values are set in the Selection card (double-clicking a state opens the same
 * fields in a dialog). A transition is added the same way, at once and empty, by drawing a line between two states or from the
 * Selection card's "Add transition to" list (the same state draws a loop); its event (its guard for a line leaving a
 * choice) takes the focus, and double-clicking a line opens its fields in a dialog. Keyboard operation: undo and redo
 * through `EditHistoryButtons`; the canvas moves a selected state with the arrow keys and removes it with Delete (which
 * asks first); the Selection card is the keyboard route to nesting a state and to the attach points.
 * The status moves are the server's; a move to Active is refused with the list of errors while the checks find any.
 * Export (PNG and SVG images, Mermaid `stateDiagram-v2` text to download or copy) saves a pending drawing first, then asks the
 * server for its own drawing and text of the stored diagram, so a file shows what the editor shows.
 *
 * Design decisions:
 * - The validation issues are the server's (`state_machine_checks`); the page only displays them (the toolbar's
 *   Validation list and the Selection card's one-line note) and tints the states they name.
 * - Comments are anchored to a state or a transition by its id and stored at once, never making the drawing look unsaved.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { useCanvasComments } from "../../components/CanvasCommentLayer";
import { useAttachPointVisibility } from "../../hooks/useAttachPointVisibility";
import { useSnapToGrid } from "../../hooks/useSnapToGrid";
import { CommentModeToggle } from "../../components/CommentModeToggle";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { EditHistoryButtons } from "../../components/EditHistoryButtons";
import { GraphCanvas, type GraphCanvasSelection, type GraphLeaderTarget } from "../../components/GraphCanvas";
import type { AttachPoint } from "../../components/graphAttachPoints";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useEscapeToLeaveMode } from "../../hooks/useEscapeToLeaveMode";
import { useFillViewportHeight } from "../../hooks/useFillViewportHeight";
import { useUrlChoice } from "../../hooks/useUrlFilter";
import { projectElementApi, projectStateApi, projectStateMachineApi } from "./api";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { architectureTabPath } from "./architectureTabs";
import { DiagramCommentsPanel } from "./DiagramCommentsPanel";
import { DiagramSwitcher } from "./DiagramSwitcher";
import { ReturnToDiagram } from "./ReturnToDiagram";
import { StateFormModal } from "./StateFormModal";
import { blankStateValues, defaultStateName, diffStateFields, valuesFromState } from "./stateFields";
import { StateMachineAddMenu } from "./StateMachineAddMenu";
import { StateMachineSettingsButton } from "./StateMachineSettingsButton";
import { diffStateMachineFields, valuesFromStateMachine } from "./stateMachineFieldValues";
import { StateMachineFormModal } from "./StateMachineFormModal";
import { DiagramExportMenu } from "./DiagramExportMenu";
import { useDiagramExport } from "./useDiagramExport";
import {
  PALETTE_KIND_PREFIX, addStateBox, boxOfState, canvasEdges, canvasLeaders, canvasNodes, defaultSize, frameAt, growAround, markerOffsets, moveStates,
  nextFreeSpot, resizeStates, setParent, setTransitionPoints,
} from "./stateMachineModel";
import { NoteModeToggle } from "./NoteModeToggle";
import type { StateMachineNoteHandlers } from "./StateMachineNoteCards";
import {
  LEADER_REACH, MAX_NOTE_LEADERS, NOTE_HEIGHT, NOTE_NODE_PREFIX, NOTE_WIDTH, addLeader, addNote, newLeader, newLeaderKey, newNote, newNoteKey,
  noteFrame, noteKeyOf, patchLeader, removeLeader, removeNote, setLeaderTarget, updateNote, type EditorLeader, type NoteLeaderTarget,
} from "./noteModel";
import { statePinAnchorOf, statePinDescriber, statePinPlaceOf } from "./stateMachineComments";
import { StateMachineOutline } from "./StateMachineOutline";
import { lineEndsOf } from "../../components/graphLineAnchors";
import { StateMachineSelectionPanel } from "./StateMachineSelectionPanel";
import type { TransitionFocusField } from "./TransitionFieldGroup";
import { TransitionFormModal } from "./TransitionFormModal";
import { blankTransitionValues, diffTransitionFields, valuesFromTransition } from "./transitionFields";
import { useStateLabel } from "./useStateLabel";
import { useStateMachineEditor } from "./useStateMachineEditor";
import { ValidationButton } from "./ValidationButton";
import { MarkdownView } from "../../components/MarkdownView";
import { markdownPlainText } from "../../utils/markdownPlain";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureElement, type ArchitectureState, type StateFieldValues,
  type StateKind, type StateMachineFieldValues, type StateTransition, type TransitionFieldValues,
} from "./types";

/** The smallest canvas height; a shorter window scrolls instead. Above it the canvas fills the window below its tabs. */
const CANVAS_MIN_HEIGHT = 300;

const EDITOR_TABS = [
  { key: "drawing", label: "Drawing" },
  { key: "outline", label: "Outline" },
  { key: "comments", label: "Comments" },
  { key: "configuration", label: "Configuration" },
] as const;
type EditorTab = (typeof EDITOR_TABS)[number]["key"];

/** A delete waiting for the person's confirmation. */
type PendingDelete =
  | { kind: "state"; state: ArchitectureState; impact: { transitions: number; links: number } }
  | { kind: "transition"; transition: StateTransition };

export function StateMachineEditorPage() {
  const { projectId = "", diagramId = "" } = useParams<{ projectId: string; diagramId: string }>();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const { user: currentUser } = useAuth();
  const api = useMemo(() => projectStateMachineApi(projectId), [projectId]);
  const stateApi = useMemo(() => projectStateApi(projectId), [projectId]);
  const stateLabels = useStateLabel();

  const [tabChoice, setTabChoice] = useUrlChoice("tab", ["outline", "comments", "configuration"] as const);
  const tab: EditorTab = tabChoice || "drawing";
  const editor = useStateMachineEditor(projectId, diagramId);
  const { model, layout, dirty } = editor;
  const diagramRecord = model?.diagram ?? null;
  const stateMachineApi = useMemo(() => projectStateMachineApi(projectId), [projectId]);
  // Export is of the stored diagram, so a pending drawing is saved first.
  const { exporting, exportDiagram } = useDiagramExport(
    diagramRecord && {
      code: diagramRecord.unique_code, name: diagramRecord.name,
      ensureSaved: async () => !dirty || (await editor.save()),
      loadSvg: () => stateMachineApi.svg(diagramRecord.id),
      loadMermaid: () => stateMachineApi.mermaid(diagramRecord.id),
    },
  );

  const [selection, setSelection] = useState<GraphCanvasSelection | null>(null);
  const [canvasBox, setCanvasBox] = useState<HTMLElement | null>(null);
  const canvasHeight = useFillViewportHeight(canvasBox, CANVAS_MIN_HEIGHT);
  const [focusNameOf, setFocusNameOf] = useState<string | null>(null);
  const [focusNoteKey, setFocusNoteKey] = useState<string | null>(null);
  const [editingState, setEditingState] = useState<ArchitectureState | null>(null);
  const [focusTransition, setFocusTransition] = useState<{ id: string; field: TransitionFocusField } | null>(null);
  const [editingTransition, setEditingTransition] = useState<StateTransition | null>(null);
  const [editingDiagram, setEditingDiagram] = useState(false);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  // The Validation list: open from the toolbar button or from a state's card (which marks that state's rows).
  const [validation, setValidation] = useState<{ open: boolean; subject: string | null }>({ open: false, subject: null });

  // A link to a state (`?state=`, from a search result or the States list) opens the diagram with that state selected.
  const [searchParams] = useSearchParams();
  const linkedState = searchParams.get("state");
  const selectedLinked = useRef(false);
  useEffect(() => {
    if (linkedState && model && !selectedLinked.current && model.states.some((s) => s.id === linkedState)) {
      selectedLinked.current = true;
      setSelection({ kind: "node", id: linkedState });
    }
  }, [linkedState, model]);

  // Unsaved drawing edits are lost on leaving the page, so the browser is asked before it closes or reloads.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!projectId || !editingDiagram) return;
    let live = true;
    const elementApi = projectElementApi(projectId);
    Promise.all([elementApi.list({ open_only: true }), elementApi.listShared({ open_only: true })])
      .then(([own, shared]) => { if (live) setElements([...own, ...shared]); })
      .catch(() => { if (live) setElements([]); });
    return () => { live = false; };
  }, [projectId, editingDiagram]);

  const kinds = useMemo(() => new Map((model?.states ?? []).map((s) => [s.id, s.kind])), [model]);
  const nodes = useMemo(() => (model ? canvasNodes(model, layout, { issues: model.validation, codeOf: stateLabels.code }) : []), [model, layout, stateLabels]);
  const edges = useMemo(() => (model ? canvasEdges(model, layout) : []), [model, layout]);
  const lineEnds = useMemo(() => lineEndsOf(nodes, edges), [nodes, edges]);
  const leaders = useMemo(() => (model ? canvasLeaders(layout, model) : []), [model, layout]);

  // Comments are stored at once and apart from the drawing, so they never make it look unsaved.
  const anchorOfPin = useCallback(
    (place: Parameters<typeof statePinAnchorOf>[0]) => (model ? statePinAnchorOf(place, model) : undefined),
    [model],
  );
  const placeOfClick = useCallback(
    (position: { x: number; y: number }, anchor: Parameters<typeof statePinPlaceOf>[1]) => (
      model ? statePinPlaceOf(position, anchor, model, layout) : { anchor_kind: "none" as const, anchor_key: null, x: Math.round(position.x), y: Math.round(position.y) }
    ),
    [model, layout],
  );
  const snap = useSnapToGrid();
  const attachPoints = useAttachPointVisibility();
  const commentLayer = useCanvasComments({
    projectId, artefactType: "architecture_state_machine_diagram", recordId: diagramId, anchorOf: anchorOfPin, placeOf: placeOfClick,
  });

  // Note mode and Comment mode are never both on: turning one on turns the other off, and a comment started elsewhere (Pin to
  // diagram) wins while it lasts.
  const [noteMode, setNoteMode] = useState(false);
  const placingNote = noteMode && !commentLayer.commentMode;
  const chooseCommentMode = (on: boolean) => { if (on) setNoteMode(false); commentLayer.setCommentMode(on); };
  const chooseNoteMode = (on: boolean) => { if (on) commentLayer.setCommentMode(false); setNoteMode(on); };
  useEscapeToLeaveMode(placingNote || commentLayer.commentMode, () => { setNoteMode(false); commentLayer.setCommentMode(false); });

  const diagram = model?.diagram ?? null;
  const archive = useArchiveAction({
    noun: "State machine diagram",
    isArchived: diagram?.is_archived ?? false,
    hidden: !diagram,
    archiveBody: "This state machine diagram will no longer appear in lists. Nothing is deleted, and the element it describes is untouched.",
    onToggle: async () => {
      if (!diagram) return;
      try {
        await (diagram.is_archived ? api.unarchive(diagram.id) : api.archive(diagram.id));
        await editor.reload(false);
        showToast(diagram.is_archived ? "State machine diagram unarchived." : "State machine diagram archived.");
      } catch (err) {
        showToast(toErrorMessage(err, "Could not update this state machine diagram."), "error");
      }
    },
  });
  const remove = useConfirmedAction(diagram ? {
    label: "Delete permanently", danger: true, title: "Delete this state machine diagram permanently?",
    message: "The diagram, its states and transitions, and the links that name its states are deleted. The element it describes is not changed. This cannot be undone.",
    confirmLabel: "Delete", requireTypedText: diagram.unique_code,
    onConfirm: async () => {
      try {
        await api.remove(diagram.id);
        showToast("State machine diagram deleted.");
        navigate(architectureTabPath(projectId, "diagrams"));
      } catch (err) {
        showToast(toErrorMessage(err, "Could not delete this state machine diagram."), "error");
      }
    },
  } : null);

  if (!projectId || !diagramId) return null;
  if (editor.loadError) return <p className="text-muted">{editor.loadError}</p>;
  if (model === null || diagram === null) return <Spinner />;

  const editable = !diagram.is_archived;

  async function saveDrawing() {
    if (await editor.save()) showToast("State machine diagram saved.");
  }

  /**
   * Adds a state of `kind` to the diagram at once, with a default name that is not in use: at `at` (the centre of a drop; a
   * position inside a composite state's frame nests the new state in it) or at the next free spot. The new state is selected and
   * its name takes the focus; a refusal is shown and nothing is added.
   */
  async function addState(kind: StateKind, at: { x: number; y: number } | null) {
    if (!model || editor.saving) return;
    const size = defaultSize(kind);
    const place = at ? { x: Math.round(at.x - size.width / 2), y: Math.round(at.y - size.height / 2) } : nextFreeSpot(layout, size);
    const parentId = at ? frameAt(layout, kinds, at) : null;
    const values = { ...blankStateValues(kind), name: defaultStateName(kind, model.states.map((s) => s.name)) };
    const created = await editor.write((version) => api.addState(diagramId, version, {
      ...values, parent_state_id: parentId, x: place.x, y: place.y, width: size.width, height: size.height,
    }));
    if (created === null) {
      showToast("Could not add the state.", "error");
      return;
    }
    editor.edit((l) => growAround(addStateBox(l, boxOfState(created)), created.id));
    setFocusNameOf(created.id);
    setSelection({ kind: "node", id: created.id });
    showToast("State added.");
  }

  /** Stores the fields changed in the Selection card; resolves true when stored (a refusal is shown at the top of the page). */
  async function saveStateFields(state: ArchitectureState, changed: Partial<StateFieldValues>): Promise<boolean> {
    if ((await editor.write((version) => stateApi.update(state.id, version, changed))) === null) return false;
    showToast("State updated.");
    return true;
  }

  async function saveState(values: StateFieldValues) {
    const state = editingState;
    if (!state) return;
    setFormError(null);
    const changed = diffStateFields(valuesFromState(state), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditingState(null);
      return;
    }
    if ((await editor.write((version) => stateApi.update(state.id, version, changed))) !== null) {
      showToast("State updated.");
      setEditingState(null);
    } else {
      setFormError("Could not update this state.");
    }
  }

  /**
   * Adds a transition from `sourceId` to `targetId` at once, with an empty event, guard and action: it is selected and its first
   * field takes the focus (the guard for a line leaving a choice, whose lines are told apart by their conditions; else the event).
   * A refusal is shown and nothing is added.
   */
  async function addTransition(sourceId: string, targetId: string) {
    if (!model || editor.saving) return;
    const created = await editor.write((version) => api.addTransition(diagramId, version, blankTransitionValues(sourceId, targetId)));
    if (created === null) {
      showToast("Could not add the transition.", "error");
      return;
    }
    setFocusTransition({ id: created.id, field: kinds.get(sourceId) === "choice" ? "guard" : "event" });
    setSelection({ kind: "edge", id: created.id });
    showToast("Transition added.");
  }

  /** Stores the fields changed in the Selection card; resolves true when stored (a refusal is shown at the top of the page). */
  async function saveTransitionFields(transition: StateTransition, changed: Partial<TransitionFieldValues>): Promise<boolean> {
    if ((await editor.write((version) => api.updateTransition(diagramId, transition.id, version, changed))) === null) return false;
    showToast("Transition updated.");
    return true;
  }

  async function saveTransition(values: TransitionFieldValues) {
    const transition = editingTransition;
    if (!transition) return;
    setFormError(null);
    const changed = diffTransitionFields(valuesFromTransition(transition), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditingTransition(null);
      return;
    }
    if ((await editor.write((version) => api.updateTransition(diagramId, transition.id, version, changed))) !== null) {
      showToast("Transition updated.");
      setEditingTransition(null);
    } else {
      setFormError("Could not update this transition.");
    }
  }

  /** Adds an empty note with its top-left corner at `at`, selects it and puts the cursor in its text (add, then edit). */
  function addNoteAt(at: { x: number; y: number }) {
    const key = newNoteKey(layout);
    editor.edit((l) => addNote(l, newNote(key, at)));
    setSelection({ kind: "node", id: NOTE_NODE_PREFIX + key });
    setFocusNoteKey(key);
  }

  /** Whether a leader may end at `target`: a state or transition of this diagram, or a free spot. */
  function leaderTargetAllowed(target: NoteLeaderTarget): boolean {
    if (!model) return false;
    if (target.kind === "state") return model.states.some((s) => s.id === target.stateId);
    if (target.kind === "transition") return model.transitions.some((t) => t.id === target.transitionId);
    return target.kind === "point";
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

  /** The target a canvas drop names, as a leader target (a note is not one). */
  function leaderTargetOf(to: GraphLeaderTarget): NoteLeaderTarget | null {
    if (to.kind === "point") return { kind: "point", x: to.x, y: to.y };
    if (to.kind === "edge") return { kind: "transition", transitionId: to.id };
    return noteKeyOf(to.id) !== null ? null : { kind: "state", stateId: to.id };
  }

  /** Points a leader at another target (a drag of its end, or the "Points at" list). */
  function pointLeaderAt(leaderKey: string, target: NoteLeaderTarget | null) {
    if (target === null || !leaderTargetAllowed(target)) return;
    editor.edit((l) => setLeaderTarget(l, leaderKey, target));
  }

  const noteHandlers: StateMachineNoteHandlers = {
    focusNoteKey, onFocused: () => setFocusNoteKey(null),
    onChange: (key, patch) => editor.edit((l) => updateNote(l, key, patch)),
    onAddLeader: addLeaderFrom,
    onSelectLeader: (key) => setSelection({ kind: "leader", id: key }),
    onSelectNote: (key) => setSelection({ kind: "node", id: NOTE_NODE_PREFIX + key }),
    onLeaderTarget: pointLeaderAt,
    onLeaderChange: (key, change: Partial<EditorLeader>) => editor.edit((l) => patchLeader(l, key, change)),
    onRemoveLeader: (key) => { editor.edit((l) => removeLeader(l, key)); setSelection(null); },
    onRemoveNote: (key) => { editor.edit((l) => removeNote(l, key)); setSelection(null); },
  };

  async function askDeleteState(state: ArchitectureState) {
    try {
      setPendingDelete({ kind: "state", state, impact: await stateApi.impact(state.id) });
    } catch (err) {
      showToast(toErrorMessage(err, "Could not read what deleting this state would remove."), "error");
    }
  }

  async function confirmDelete(target: PendingDelete) {
    setPendingDelete(null);
    if (target.kind === "state") {
      if ((await editor.write((version) => stateApi.remove(target.state.id, version))) !== null) {
        showToast("State deleted.");
        setSelection(null);
      }
    } else if ((await editor.write((version) => api.removeTransition(diagramId, target.transition.id, version))) !== null) {
      showToast("Transition deleted.");
      setSelection(null);
    }
  }

  async function saveDiagramFields(values: StateMachineFieldValues) {
    if (!diagram) return;
    setFormError(null);
    const changed = diffStateMachineFields(valuesFromStateMachine(diagram), values);
    if (Object.keys(changed).length === 0) {
      setEditingDiagram(false);
      return;
    }
    if (await editor.updateFields(changed)) {
      showToast("State machine diagram updated.");
      setEditingDiagram(false);
    } else {
      setFormError("Could not update this state machine diagram.");
    }
  }

  /**
   * The canvas's Delete key: states and transitions are deleted after a confirmation, never at once; a note or a leader line is
   * removed from the drawing at once (an undoable local edit that Save stores).
   */
  function deleteSelected(chosen: GraphCanvasSelection) {
    if (!editable || !model) return;
    if (chosen.kind === "leader") {
      editor.edit((l) => removeLeader(l, chosen.id));
      setSelection(null);
      return;
    }
    const noteKey = chosen.kind === "node" ? noteKeyOf(chosen.id) : null;
    if (noteKey !== null) {
      editor.edit((l) => removeNote(l, noteKey));
      setSelection(null);
      return;
    }
    if (chosen.kind === "node") {
      const state = model.states.find((s) => s.id === chosen.id);
      if (state) void askDeleteState(state);
    } else {
      const transition = model.transitions.find((t) => t.id === chosen.id);
      if (transition) setPendingDelete({ kind: "transition", transition });
    }
  }

  async function moveTo(status: Parameters<typeof editor.setStatus>[0]) {
    if (await editor.setStatus(status)) showToast(`State machine diagram moved to ${ARCHITECTURE_STATUS_LABEL[status]}.`);
  }

  const toolbar = (
    <div className="row" role="toolbar" aria-label="State machine diagram editing" style={{ alignItems: "center", gap: "var(--space-2)" }}>
      <EditHistoryButtons editable={editable} canUndo={editor.canUndo} canRedo={editor.canRedo} undo={editor.undo} redo={editor.redo} />
      <button
        type="button" className="btn btn-primary btn-sm" disabled={!editable || !dirty || editor.saving || editor.conflict}
        onClick={() => void saveDrawing()} aria-label="Save diagram"
      >
        Save
      </button>
      <StateMachineAddMenu
        disabled={!editable || editor.saving} onAdd={(kind) => void addState(kind, null)}
        onAddNote={() => addNoteAt(nextFreeSpot(layout, { width: NOTE_WIDTH, height: NOTE_HEIGHT }))}
      />
      <DiagramExportMenu disabled={exporting} onExport={(kind) => void exportDiagram(kind)} />
      {tab === "drawing" && <NoteModeToggle on={placingNote} onChange={chooseNoteMode} disabled={!editable} />}
      {tab === "drawing" && <CommentModeToggle on={commentLayer.commentMode} onChange={chooseCommentMode} />}
      {model && (
        <ValidationButton
          issues={model.validation} open={validation.open} focusSubject={validation.subject}
          onOpenChange={(open) => setValidation({ open, subject: null })}
          onSelect={(code) => {
            const state = model.states.find((st) => st.unique_code === code);
            if (state) setSelection({ kind: "node", id: state.id });
          }}
        />
      )}
      <StateMachineSettingsButton
        lineHops={diagram?.line_hops ?? false} disabled={!editable || editor.saving}
        onLineHopsChange={(next) => void editor.updateFields({ line_hops: next })}
        lineShape={diagram?.line_shape ?? "straight"} onLineShapeChange={(next) => void editor.updateFields({ line_shape: next })}
        snapToGrid={snap.on} onSnapToGridChange={snap.setOn} attachPointsAlways={attachPoints.always} onAttachPointsAlwaysChange={attachPoints.setAlways} />
      {dirty && <span className="text-muted" role="status">Unsaved changes.</span>}
    </div>
  );

  const selectionColumn = (
    <div className="stack" style={{ flex: "1 1 18rem", minWidth: 0 }}>
      <StateMachineSelectionPanel
        maxHeight={canvasHeight}
        projectId={projectId} model={model} layout={layout} selection={selection} editable={editable}
        onSaveState={saveStateFields} focusNameOf={focusNameOf} onNameFocused={() => setFocusNameOf(null)}
        onSaveTransition={saveTransitionFields} focusTransition={focusTransition} onTransitionFocused={() => setFocusTransition(null)}
        onDeleteState={(state) => void askDeleteState(state)}
        onDeleteTransition={(transition) => setPendingDelete({ kind: "transition", transition })}
        onParentChange={(state, parentId) => editor.edit((l) => setParent(l, state.id, parentId, kinds))}
        lineEnds={lineEnds}
        onPointsChange={(transition, change) => editor.edit((l) => setTransitionPoints(l, transition.id, change))}
        onConnect={(state, targetId) => void addTransition(state.id, targetId)}
        notes={noteHandlers}
        onOpenValidation={(subject) => setValidation({ open: true, subject })}
        onComment={(target) => {
          // A transition has no position of its own here, so the comment starts at the middle of the states it joins.
          const line = target.kind === "edge" ? model.transitions.find((t) => t.id === target.id) : undefined;
          const from = layout.boxes.find((b) => b.id === line?.source_state_id);
          const to = layout.boxes.find((b) => b.id === line?.target_state_id);
          const at = from && to ? { x: (from.x + from.width / 2 + to.x + to.width / 2) / 2, y: (from.y + from.height / 2 + to.y + to.height / 2) / 2 } : { x: 0, y: 0 };
          setTabChoice("");
          commentLayer.setCommentMode(true);
          commentLayer.startAt(statePinPlaceOf(at, target, model, layout));
        }}
      />
    </div>
  );

  const elementLabel = [diagram.element_code, diagram.element_name].filter(Boolean).join(" ") || "an element you cannot read";

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="architecture_state_machine_diagram" artefactId={diagram.id} refreshToken={recordActivityKey(diagram)} />}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="architecture_state_machine_diagram" artefactId={diagram.id} onChanged={() => void editor.reload(false)} />}
    >
      <RecordHeader
        recordLabel="State machine diagram"
        title={diagram.name}
        titleAddon={<DiagramSwitcher kind="stateMachine" projectId={projectId} currentId={diagram.id} />}
        code={diagram.unique_code}
        tags={<RecordTags projectId={projectId} artefactType="architecture_state_machine_diagram" artefactId={diagram.id} />}
        back={{ to: architectureTabPath(projectId, "diagrams"), label: "Diagrams" }}
        returnTo={<ReturnToDiagram projectId={projectId} elementId={diagram.element_id} from={searchParams.get("from")} />}
        badges={
          <>
            {diagram.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[diagram.status]}>{ARCHITECTURE_STATUS_LABEL[diagram.status]}</Badge>
            {diagram.error_count > 0 && <Badge tone="danger">{diagram.error_count} {diagram.error_count === 1 ? "error" : "errors"}</Badge>}
            {diagram.warning_count > 0 && <Badge tone="warning">{diagram.warning_count} {diagram.warning_count === 1 ? "warning" : "warnings"}</Badge>}
          </>
        }
        version={diagram.version}
        subtitle={<>Describes <Link to={`/projects/${projectId}/modules/architecture/elements/${diagram.element_id}`}>{elementLabel}</Link>{diagram.description ? ` · ${markdownPlainText(diagram.description)}` : ""}</>}
        onEdit={editable ? () => { setFormError(null); setEditingDiagram(true); } : undefined}
        actions={[archive.item, remove.item]}
        stateMenu={<ArchitectureStatusControls status={diagram.status} moves={diagram.allowed_status_moves} onMove={moveTo} />}
      />
      {archive.dialog}
      {remove.dialog}

      {editor.conflict && (
        <div role="alert" className="card stack">
          <p>
            Someone else saved this state machine diagram after you opened it, so your changes were not stored. Reload to continue from
            their version; your unsaved changes will be lost.
          </p>
          <button type="button" className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => void editor.reload(true)}>
            Reload state machine diagram
          </button>
        </div>
      )}
      {editor.saveError && !editingState && !editingTransition && !editingDiagram && (
        <p role="alert" style={{ color: "var(--color-danger)" }}>{editor.saveError}</p>
      )}

      <Tabs idPrefix="state-machine-editor" tabs={[...EDITOR_TABS]} active={tab} onChange={(next) => setTabChoice(next === "drawing" ? "" : next)} />

      {tab !== "configuration" && toolbar}

      {tab === "drawing" && (
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }} {...tabPanelProps("state-machine-editor", "drawing")}>
          <div className="stack" style={{ flex: "3 1 32rem", minWidth: 0 }}>
            <div ref={setCanvasBox}>
              <GraphCanvas
                nodes={nodes} edges={edges} leaders={leaders} ariaLabel={`State machine diagram ${diagram.name}`} height={canvasHeight}
                readOnly={!editable} resizable fitMaxZoom={1} showViewToggle={false} selected={selection}
                // A note just placed from Note mode must not lose its selection when the same click clears it on the canvas.
                onSelect={(next) => { if (next !== null || !placingNote) { setSelection(next); setFocusNoteKey(null); } }}
                {...commentLayer.canvasProps} {...snap.canvasProps} {...attachPoints.canvasProps} lineHops={diagram?.line_hops ?? false}
                onNodesMove={(moves) => editor.edit((l) => moveStates(l, moves, markerOffsets(model.states, l)))}
                onNodesResize={(changes) => editor.edit((l) => resizeStates(l, changes))}
                onEdgeAnchorChange={(edgeId, change) => editor.edit((l) => setTransitionPoints(l, edgeId, change))}
                onEdgePointsChange={(edgeId, points) => editor.edit((l) => setTransitionPoints(l, edgeId, { points }))}
                onCanvasClick={(at) => {
                  if (placingNote) addNoteAt({ x: Math.round(at.x - NOTE_WIDTH / 2), y: Math.round(at.y - NOTE_HEIGHT / 2) });
                }}
                onLeaderTargetChange={(leaderKey, target) => pointLeaderAt(leaderKey, leaderTargetOf(target))}
                onLeaderPointsChange={(leaderKey, points) => editor.edit((l) => patchLeader(l, leaderKey, { points }))}
                onConnectEmpty={(source, to, via) => {
                  // A line drawn from a note and released on a state, a line or empty canvas is a leader; a state starts no such line.
                  const noteKey = noteKeyOf(source);
                  if (noteKey === null) return;
                  const target = leaderTargetOf(to);
                  if (target) addLeaderTo(noteKey, target, via.sourcePoint ?? null);
                }}
                onConnect={(source, target, via) => {
                  // A line from a note to a state is a leader, not a transition; nothing is drawn to a note.
                  const noteKey = noteKeyOf(source);
                  if (noteKey !== null) {
                    const to = leaderTargetOf({ kind: "node", id: target });
                    if (to) addLeaderTo(noteKey, to, via?.sourcePoint ?? null);
                    return;
                  }
                  if (noteKeyOf(target) === null) void addTransition(source, target);
                }}
                onDelete={deleteSelected} deleteKeyScope="page"
                onNodeOpen={(id) => {
                  const state = model.states.find((s) => s.id === id);
                  if (state && editable) { setFormError(null); setEditingState(state); }
                }}
                onEdgeOpen={(id) => {
                  const transition = model.transitions.find((t) => t.id === id);
                  if (transition && editable) { setFormError(null); setEditingTransition(transition); }
                }}
                onDropItem={(payload, at) => {
                  if (payload.startsWith(PALETTE_KIND_PREFIX)) void addState(payload.slice(PALETTE_KIND_PREFIX.length) as StateKind, at);
                }}
              />
            </div>
          </div>
          {selectionColumn}
        </div>
      )}

      {tab === "outline" && (
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }} {...tabPanelProps("state-machine-editor", "outline")}>
          <div className="stack" style={{ flex: "3 1 32rem", minWidth: 0 }}>
            <StateMachineOutline model={model} layout={layout} selection={selection} onSelect={setSelection} />
          </div>
          {selectionColumn}
        </div>
      )}

      {tab === "comments" && (
        <div className="stack" {...tabPanelProps("state-machine-editor", "comments")}>
          <DiagramCommentsPanel layer={commentLayer} describe={statePinDescriber(model, stateLabels)} currentUserId={currentUser?.id} onShow={() => setTabChoice("")} />
        </div>
      )}

      {tab === "configuration" && (
        <div className="stack" {...tabPanelProps("state-machine-editor", "configuration")}>
          {dirty && <p className="text-muted" role="status">The drawing has unsaved changes; they are kept and are saved from the Drawing tab.</p>}
          <DetailCard heading="Details">
            <dl style={{ margin: 0 }}>
              <dt className="text-muted">Element</dt>
              <dd style={{ margin: 0 }}>
                <Link to={`/projects/${projectId}/modules/architecture/elements/${diagram.element_id}`}>{elementLabel}</Link>
              </dd>
              <dt className="text-muted">Description</dt>
              <dd style={{ margin: 0 }}>{diagram.description ? <MarkdownView text={diagram.description} /> : "—"}</dd>
            </dl>
            {editable && (
              <button type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => { setFormError(null); setEditingDiagram(true); }}>
                Edit details
              </button>
            )}
          </DetailCard>
        </div>
      )}

      {editingDiagram && (
        <StateMachineFormModal
          initial={diagram} elements={elements} error={formError}
          onCancel={() => { setEditingDiagram(false); setFormError(null); }} onSave={(values) => void saveDiagramFields(values)}
        />
      )}
      {editingState && (
        <StateFormModal
          initial={editingState} error={formError} holdsStates={layout.boxes.some((b) => b.parent_state_id === editingState.id)}
          onCancel={() => { setEditingState(null); setFormError(null); }} onSave={(values) => void saveState(values)}
        />
      )}
      {editingTransition && (
        <TransitionFormModal
          states={model.states} initial={editingTransition} error={formError ?? editor.saveError}
          onCancel={() => { setEditingTransition(null); setFormError(null); editor.clearError(); }} onSave={(values) => void saveTransition(values)}
        />
      )}
      {pendingDelete?.kind === "state" && (
        <ConfirmDialog
          title="Delete this state?" confirmLabel="Delete" requireTypedText={pendingDelete.state.unique_code}
          message={`${stateLabels.label(pendingDelete.state)} is deleted with its ${pendingDelete.impact.transitions} ${pendingDelete.impact.transitions === 1 ? "transition" : "transitions"} and ${pendingDelete.impact.links} ${pendingDelete.impact.links === 1 ? "link" : "links"}. This cannot be undone.`}
          onCancel={() => setPendingDelete(null)} onConfirm={() => void confirmDelete(pendingDelete)}
        />
      )}
      {pendingDelete?.kind === "transition" && (
        <ConfirmDialog
          title="Delete this transition?" confirmLabel="Delete" message="The transition is deleted. The states it joined are not changed."
          onCancel={() => setPendingDelete(null)} onConfirm={() => void confirmDelete(pendingDelete)}
        />
      )}
    </DetailLayout>
  );
}
