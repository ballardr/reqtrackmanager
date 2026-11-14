/**
 * Module: modules/architecture/StateMachineEditorPage
 *
 * One state machine diagram as a routed page and its editor
 * (`/projects/:projectId/modules/architecture/state-machine-diagrams/:diagramId`, also the target other records' links and
 * search results follow; `?state=` opens it with that state selected). The record header sits above four tabs (`?tab=`;
 * Drawing is the default): Drawing (toolbar, the shared graph canvas, the Selection card and the findings), Outline (states
 * as a tree, transitions as a table), Comments and Configuration (the diagram's details). Links and Activity are in the aside.
 *
 * Editing model: what a state or transition *is* (name, kind, entry, exit and do lines, event, guard, action) is stored
 * at once by its form, because the findings and the state's code come from the server. What the drawing *looks like*
 * (a state's position, size and nesting, a transition's attach points) is edited locally with undo and redo and stored together
 * by Save, which quotes the diagram's version; a stale version offers a reload instead of overwriting a newer save. A state
 * is created by choosing it in the Add to diagram menu or dropping it on the canvas (the form opens; Cancel creates nothing),
 * a transition by drawing a line between two states or from the Selection card's "Add transition to" list (the same state
 * draws a loop). Keyboard operation: the canvas moves a selected state with the arrow keys and removes it with Delete (which
 * asks first); the Selection card is the keyboard route to nesting a state and to the attach points.
 * The status moves are the server's; a move to Active is refused with the list of errors while the checks find any.
 * Export (PNG and SVG images, Mermaid `stateDiagram-v2` text to download or copy) saves a pending drawing first, then asks the
 * server for its own drawing and text of the stored diagram, so a file shows what the editor shows.
 *
 * Design decisions:
 * - The findings are the server's (`state_machine_checks`); the page only displays them and tints the states they name.
 * - Comments are anchored to a state or a transition by its id and stored at once, never making the drawing look unsaved.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { useCanvasComments } from "../../components/CanvasCommentLayer";
import { CommentModeToggle } from "../../components/CommentModeToggle";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { GraphCanvas, type GraphCanvasSelection } from "../../components/GraphCanvas";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useArchiveAction, useConfirmedAction } from "../../components/useConfirmedAction";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useFillViewportHeight } from "../../hooks/useFillViewportHeight";
import { useUrlChoice } from "../../hooks/useUrlFilter";
import { projectElementApi, projectStateApi, projectStateMachineApi } from "./api";
import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import { architectureTabPath } from "./architectureTabs";
import { DiagramCommentsPanel } from "./DiagramCommentsPanel";
import { StateFormModal, type StateCreateExtras } from "./StateFormModal";
import { diffStateFields, valuesFromState } from "./stateFields";
import { StateMachineAddMenu } from "./StateMachineAddMenu";
import { diffStateMachineFields, valuesFromStateMachine } from "./stateMachineFieldValues";
import { StateMachineFindings } from "./StateMachineFindings";
import { StateMachineFormModal } from "./StateMachineFormModal";
import { DiagramExportMenu } from "./DiagramExportMenu";
import { useDiagramExport } from "./useDiagramExport";
import {
  PALETTE_KIND_PREFIX, addStateBox, boxOfState, canvasEdges, canvasNodes, defaultSize, frameAt, growAround, moveStates, nextFreeSpot,
  resizeStates, setParent, setTransitionPoints,
} from "./stateMachineModel";
import { statePinAnchorOf, statePinDescriber, statePinPlaceOf } from "./stateMachineComments";
import { StateMachineOutline } from "./StateMachineOutline";
import { StateMachineSelectionPanel } from "./StateMachineSelectionPanel";
import { TransitionFormModal } from "./TransitionFormModal";
import { diffTransitionFields, valuesFromTransition } from "./transitionFields";
import { useStateLabel } from "./useStateLabel";
import { useStateMachineEditor } from "./useStateMachineEditor";
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

/** A state waiting for its form: what kind it is, where it goes and which frame (if any) it is dropped into. */
interface PendingState {
  kind: StateKind;
  at: { x: number; y: number };
  parentId: string | null;
}

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
  const commitTags = useCommitTags(projectId, "architecture_state");
  const commitQuickLinks = useCommitQuickLinks(projectId, "architecture_state");
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
  const [pendingState, setPendingState] = useState<PendingState | null>(null);
  const [editingState, setEditingState] = useState<ArchitectureState | null>(null);
  const [connecting, setConnecting] = useState<{ source: string; target: string } | null>(null);
  const [editingTransition, setEditingTransition] = useState<StateTransition | null>(null);
  const [editingDiagram, setEditingDiagram] = useState(false);
  const [elements, setElements] = useState<ArchitectureElement[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);

  // A link to a state (`?state=`, from a search result or the States list) opens the diagram with that state selected.
  const [searchParams] = useSearchParams();
  const linkedState = searchParams.get("state");
  const linkedPin = searchParams.get("pin");
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
  const nodes = useMemo(() => (model ? canvasNodes(model, layout, { findings: model.findings, codeOf: stateLabels.code }) : []), [model, layout, stateLabels]);
  const edges = useMemo(() => (model ? canvasEdges(model, layout) : []), [model, layout]);

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
  const commentLayer = useCanvasComments({
    projectId, artefactType: "architecture_state_machine_diagram", recordId: diagramId, anchorOf: anchorOfPin, placeOf: placeOfClick,
    initialPin: linkedPin,
  });
  const linkedPinThread = commentLayer.comments.thread;
  const focusedLinkedPin = useRef(false);
  useEffect(() => {
    if (linkedPin && linkedPinThread && !focusedLinkedPin.current) {
      focusedLinkedPin.current = true;
      commentLayer.focusPin(linkedPin);
    }
  }, [linkedPin, linkedPinThread, commentLayer]);

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

  /** Opens the form for a new state; a position inside a composite state's frame nests the new state in it. */
  function startState(kind: StateKind, at: { x: number; y: number } | null) {
    const size = defaultSize(kind);
    const place = at ?? nextFreeSpot(layout, size);
    const parentId = at ? frameAt(layout, kinds, at) : null;
    setFormError(null);
    setPendingState({ kind, at: at ? { x: Math.round(at.x - size.width / 2), y: Math.round(at.y - size.height / 2) } : place, parentId });
  }

  async function createState(values: StateFieldValues, extras: StateCreateExtras) {
    const pending = pendingState;
    if (!pending) return;
    setFormError(null);
    const size = defaultSize(values.kind);
    const created = await editor.write((version) => api.addState(diagramId, version, {
      ...values, parent_state_id: pending.parentId, x: pending.at.x, y: pending.at.y, width: size.width, height: size.height,
    }));
    if (created === null) {
      setFormError("Could not create the state.");
      return;
    }
    await commitQuickLinks(created.id, extras.quickLinks);
    await commitTags(created.id, extras.tags);
    editor.edit((l) => growAround(addStateBox(l, boxOfState(created)), created.id));
    setSelection({ kind: "node", id: created.id });
    setPendingState(null);
    showToast("State created.");
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

  async function createTransition(values: TransitionFieldValues) {
    setFormError(null);
    const created = await editor.write((version) => api.addTransition(diagramId, version, values));
    if (created === null) {
      setFormError("Could not create the transition.");
      return;
    }
    setConnecting(null);
    setSelection({ kind: "edge", id: created.id });
    showToast("Transition created.");
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

  /** The canvas's Delete key: states and transitions are deleted after a confirmation, never at once. */
  function deleteSelected(chosen: GraphCanvasSelection) {
    if (!editable || !model) return;
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
      <button type="button" className="btn btn-sm" disabled={!editable || !editor.canUndo} onClick={editor.undo}>Undo</button>
      <button type="button" className="btn btn-sm" disabled={!editable || !editor.canRedo} onClick={editor.redo}>Redo</button>
      <button
        type="button" className="btn btn-primary btn-sm" disabled={!editable || !dirty || editor.saving || editor.conflict}
        onClick={() => void saveDrawing()}
      >
        Save
      </button>
      <StateMachineAddMenu disabled={!editable} onAdd={(kind) => startState(kind, null)} />
      <DiagramExportMenu disabled={exporting} onExport={(kind) => void exportDiagram(kind)} />
      {tab === "drawing" && <CommentModeToggle on={commentLayer.commentMode} onChange={commentLayer.setCommentMode} />}
      {dirty && <span className="text-muted" role="status">Unsaved changes.</span>}
    </div>
  );

  const selectionColumn = (
    <div className="stack" style={{ flex: "1 1 18rem", minWidth: 0 }}>
      <StateMachineSelectionPanel
        projectId={projectId} model={model} layout={layout} selection={selection} editable={editable}
        onEditState={(state) => { setFormError(null); setEditingState(state); }}
        onEditTransition={(transition) => { setFormError(null); setEditingTransition(transition); }}
        onDeleteState={(state) => void askDeleteState(state)}
        onDeleteTransition={(transition) => setPendingDelete({ kind: "transition", transition })}
        onParentChange={(state, parentId) => editor.edit((l) => setParent(l, state.id, parentId, kinds))}
        onPointsChange={(transition, change) => editor.edit((l) => setTransitionPoints(l, transition.id, change))}
        onConnect={(state, targetId) => { setFormError(null); setConnecting({ source: state.id, target: targetId }); }}
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
      <StateMachineFindings
        findings={model.findings}
        subjectLabel={(code) => {
          const state = model.states.find((s) => s.unique_code === code);
          return state ? stateLabels.code(state) : code;
        }}
        onSelect={(code) => {
          const state = model.states.find((s) => s.unique_code === code);
          if (state) setSelection({ kind: "node", id: state.id });
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
        code={diagram.unique_code}
        tagsInline tags={<RecordTags inline projectId={projectId} artefactType="architecture_state_machine_diagram" artefactId={diagram.id} />}
        back={{ to: architectureTabPath(projectId, "diagrams"), label: "Diagrams" }}
        badges={
          <>
            {diagram.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={ARCHITECTURE_STATUS_TONE[diagram.status]}>{ARCHITECTURE_STATUS_LABEL[diagram.status]}</Badge>
            {diagram.error_count > 0 && <Badge tone="danger">{diagram.error_count} {diagram.error_count === 1 ? "error" : "errors"}</Badge>}
            {diagram.warning_count > 0 && <Badge tone="warning">{diagram.warning_count} {diagram.warning_count === 1 ? "warning" : "warnings"}</Badge>}
          </>
        }
        version={diagram.version}
        subtitle={<>Describes <Link to={`/projects/${projectId}/modules/architecture/elements/${diagram.element_id}`}>{elementLabel}</Link>{diagram.description ? ` · ${diagram.description}` : ""}</>}
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
      {editor.saveError && !pendingState && !editingState && !connecting && !editingTransition && !editingDiagram && (
        <p role="alert" style={{ color: "var(--color-danger)" }}>{editor.saveError}</p>
      )}

      <Tabs idPrefix="state-machine-editor" tabs={[...EDITOR_TABS]} active={tab} onChange={(next) => setTabChoice(next === "drawing" ? "" : next)} />

      {tab !== "configuration" && toolbar}

      {tab === "drawing" && (
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }} {...tabPanelProps("state-machine-editor", "drawing")}>
          <div className="stack" style={{ flex: "3 1 32rem", minWidth: 0 }}>
            {model.states.length === 0 && (
              <p className="text-muted" role="status">
                No states yet. Use Add to diagram, then Initial state to mark where the machine starts, and State for each state it can be in.
              </p>
            )}
            <div ref={setCanvasBox}>
              <GraphCanvas
                nodes={nodes} edges={edges} ariaLabel={`State machine diagram ${diagram.name}`} height={canvasHeight}
                readOnly={!editable} resizable fitMaxZoom={1} showViewToggle={false} selected={selection} onSelect={setSelection}
                {...commentLayer.canvasProps}
                onNodesMove={(moves) => editor.edit((l) => moveStates(l, moves))}
                onNodesResize={(changes) => editor.edit((l) => resizeStates(l, changes))}
                onEdgeAnchorChange={(edgeId, change) => editor.edit((l) => setTransitionPoints(l, edgeId, change))}
                onConnect={(source, target) => { setFormError(null); setConnecting({ source, target }); }}
                onDelete={deleteSelected}
                onDropItem={(payload, at) => {
                  if (payload.startsWith(PALETTE_KIND_PREFIX)) startState(payload.slice(PALETTE_KIND_PREFIX.length) as StateKind, at);
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
              <dd style={{ margin: 0, whiteSpace: "pre-line" }}>{diagram.description || "—"}</dd>
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
      {pendingState && (
        <StateFormModal
          projectId={projectId} defaultKind={pendingState.kind} error={formError}
          onCancel={() => { setPendingState(null); setFormError(null); }} onSave={(values, extras) => void createState(values, extras)}
        />
      )}
      {editingState && (
        <StateFormModal
          projectId={projectId} initial={editingState} error={formError} holdsStates={layout.boxes.some((b) => b.parent_state_id === editingState.id)}
          onCancel={() => { setEditingState(null); setFormError(null); }} onSave={(values) => void saveState(values)}
        />
      )}
      {connecting && (
        <TransitionFormModal
          states={model.states} defaultSourceId={connecting.source} defaultTargetId={connecting.target} error={formError ?? editor.saveError}
          onCancel={() => { setConnecting(null); setFormError(null); editor.clearError(); }} onSave={(values) => void createTransition(values)}
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
