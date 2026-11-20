/**
 * Module: modules/architecture/StateMachineSelectionPanel
 *
 * The state machine editor's "Selection" card: what the selected state or transition is and what can be done with it.
 * - A state: its fields, edited in place through the shared field group (name, kind, description, entry, exit and do lines; read-only
 *   text when the diagram cannot be edited), its tags (the shared `RecordTags`; a state sits in no component), its links, the
 *   issues that name it; Comment, Delete (confirmed, naming how many transitions and links go with it) and, for an ordinary
 *   or marker state, "Inside": the state it sits inside, the keyboard route to dragging it into a frame. A state that holds
 *   others cannot become a marker. Double-clicking a state on the canvas opens the same fields in a dialog.
 * - A transition: its two states, event, condition (guard), action and description, edited in place through the shared field group (read-only
 *   text when the diagram cannot be edited), the issues that name it, the attach points of its two ends (the keyboard route to
 *   dragging a line's end); Comment and Delete. Double-clicking a line on the canvas opens the same fields in a dialog.
 * - A note or one of its leader lines: the shared note and leader forms (`StateMachineNoteCards`).
 * - Nothing selected: a short prompt.
 *
 * Design decisions:
 * - The actions are icon buttons from the shared `SelectionActions`, the same set the block diagram's card uses.
 * - The card stores nothing: every action is a callback onto the page, which stores content at once and the drawing on Save.
 */
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { DetailCard } from "../../components/DetailCard";
import { FieldCaption } from "../../components/FieldHelp";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { returnFocusToCanvas } from "../../utils/canvasFocus";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, SIDE_POINTS, pointXY, type AttachPoint, type BoxGeometry } from "../../components/graphAttachPoints";
import type { LineEnds } from "../../components/graphLineAnchors";
import { suggestWaypoint, type LineShape } from "../../components/graphLinePath";
import { LabeledSelect } from "../../components/LabeledSelect";
import { LineVertexFields } from "./LineVertexFields";
import { RecordTags } from "../../components/RecordTags";
import { useStrings } from "../../context/TerminologyContext";
import { ARCHITECTURE_HELP } from "./help";
import { TermCaption } from "./TermCaption";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import { StateSelectionFields } from "./StateSelectionFields";
import type { TransitionFocusField } from "./TransitionFieldGroup";
import { TransitionSelectionFields } from "./TransitionSelectionFields";
import { noteKeyOf } from "./noteModel";
import { StateMachineNoteCards, type StateMachineNoteHandlers } from "./StateMachineNoteCards";
import { useStateLabel } from "./useStateLabel";
import { descendantIds, issuesFor, isMarkerKind, type StateMachineLayout } from "./stateMachineModel";
import { markerAttachPoints, markerFrame } from "./stateShapes";
import { MarkdownView } from "../../components/MarkdownView";
import {
  LABEL_POSITION_LABEL, STATE_KIND_LABEL, type ArchitectureState, type LineRouteChange, type LineWaypoint, type StateFieldValues, type StateMachineModel, type StateTransition, type TransitionFieldValues,
} from "./types";

/** The geometry of a state's box as the canvas draws it, with the points a marker offers (its label's side is not one). */
function geometry(layout: StateMachineLayout, state: ArchitectureState): BoxGeometry {
  const box = layout.boxes.find((b) => b.id === state.id) ?? state;
  if (!isMarkerKind(state.kind)) return { x: box.x, y: box.y, width: box.width, height: box.height };
  const frame = markerFrame(state.kind, box, state.label, state.label_position);
  return { ...frame, points: markerAttachPoints(state.label, state.label_position) };
}

/**
 * @param projectId The diagram's project.
 * @param model The model as read.
 * @param layout The drawing being edited.
 * @param selection What is selected on the canvas, or null.
 * @param editable False hides every action that changes the diagram.
 * @param onSaveState Stores the changed content fields of a state; resolves true when stored.
 * @param focusNameOf The id of a state just added, whose name takes the focus when its card appears; null for none.
 * @param onNameFocused Called once that focus has been given, so it is not repeated.
 * @param onSaveTransition Stores the changed fields of a transition; resolves true when stored.
 * @param focusTransition The id and field of a transition just added, whose field takes the focus when its card appears; null for none.
 * @param onTransitionFocused Called once that focus has been given, so it is not repeated.
 * @param onDeleteState Asks to delete the state (the page confirms, naming what goes with it).
 * @param onDeleteTransition Asks to delete the transition (the page confirms).
 * @param onConnect Starts a transition from a state to the state with the given id (the same state for a loop): the keyboard
 *   route to drawing a line between two states.
 * @param onParentChange Puts the state inside another (or at the top level with null); an unsaved drawing edit.
 * @param lineEnds The attach points a transition's ends use and would use if left automatic (`lineEndsOf`).
 * @param onPointsChange Sets the attach point of one or both ends of a transition (null is automatic); an unsaved drawing edit.
 * @param onComment Starts a comment on the selected state or transition.
 * @param onOpenValidation Opens the Validation list at a state code, from the one-line note of a selection that has issues.
 * @param notes What a change to a selected note or leader does.
 */
export function StateMachineSelectionPanel({
  projectId, model, layout, selection, editable, onSaveState, focusNameOf, onNameFocused, onSaveTransition, focusTransition, onTransitionFocused, onDeleteState, onDeleteTransition, onParentChange,
  lineEnds, onPointsChange, onComment, onOpenValidation, onConnect, notes, maxHeight,
}: {
  projectId: string;
  model: StateMachineModel;
  layout: StateMachineLayout;
  selection: GraphCanvasSelection | null;
  editable: boolean;
  onSaveState: (state: ArchitectureState, changed: Partial<StateFieldValues>) => Promise<boolean>;
  focusNameOf: string | null;
  onNameFocused: () => void;
  onSaveTransition: (transition: StateTransition, changed: Partial<TransitionFieldValues>) => Promise<boolean>;
  focusTransition: { id: string; field: TransitionFocusField } | null;
  onTransitionFocused: () => void;
  onDeleteState: (state: ArchitectureState) => void;
  onDeleteTransition: (transition: StateTransition) => void;
  onConnect: (state: ArchitectureState, targetId: string) => void;
  onParentChange: (state: ArchitectureState, parentId: string | null) => void;
  lineEnds: (transitionId: string) => LineEnds | null;
  onPointsChange: (transition: StateTransition, change: LineRouteChange) => void;
  onComment: (target: { kind: "node" | "edge"; id: string }) => void;
  onOpenValidation: (subject: string) => void;
  notes: StateMachineNoteHandlers;
  /** The tallest the card may be (the drawing's height); it scrolls inside beyond that. */
  maxHeight?: number;
}) {
  const commentText = useStrings().canvasComments;
  const stateName = useStateLabel().label;

  const noteKey = selection?.kind === "node" ? noteKeyOf(selection.id) : null;
  const note = noteKey === null ? null : layout.notes.find((n) => n.key === noteKey) ?? null;
  const leader = selection?.kind === "leader"
    ? layout.notes.flatMap((n) => n.leaders.map((l, i) => ({ note: n, leader: l, index: i + 1 }))).find((x) => x.leader.key === selection.id) ?? null
    : null;
  const state = selection?.kind === "node" && noteKey === null ? model.states.find((s) => s.id === selection.id) ?? null : null;
  const transition = selection?.kind === "edge" ? model.transitions.find((t) => t.id === selection.id) ?? null : null;

  let body;
  // The card's title is what is selected, so the heading line (with the Save button beside it) says what the card is about.
  let title: string | undefined;
  if (note || leader) {
    title = leader ? `Leader ${leader.index}` : "Note";
    body = <StateMachineNoteCards model={model} layout={layout} note={note} leader={leader} editable={editable} handlers={notes} />;
  } else if (state) {
    const holds = layout.boxes.some((b) => b.parent_state_id === state.id);
    const own = layout.boxes.find((b) => b.id === state.id);
    const blocked = new Set([state.id, ...descendantIds(layout, state.id)]);
    const parents = model.states.filter((s) => s.kind === "state" && !blocked.has(s.id));
    const issues = issuesFor(model.validation, state.unique_code);
    title = stateName(state);
    body = (
      <>
        {!editable && <p className="text-muted">{STATE_KIND_LABEL[state.kind]}</p>}
        {editable ? (
          <StateSelectionFields
            key={`fields:${state.id}`} state={state} holdsStates={holds} autoFocusName={focusNameOf === state.id} onFocused={onNameFocused}
            onSave={(changed) => onSaveState(state, changed)}
          />
        ) : (
          <>
            {state.description && (
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                <FieldCaption label="Description" help={ARCHITECTURE_HELP.elementDescription} />
                <MarkdownView text={state.description} />
              </div>
            )}
            {isMarkerKind(state.kind) && state.label && (
              <dl style={{ margin: 0 }}>
                <dt><TermCaption term="Symbol label" /></dt><dd style={{ margin: 0 }}>{state.label}</dd>
                <dt><TermCaption term="Label position" /></dt><dd style={{ margin: 0 }}>{LABEL_POSITION_LABEL[state.label_position]}</dd>
              </dl>
            )}
            {!isMarkerKind(state.kind) && (state.entry_action || state.exit_action || state.activity) && (
              <dl style={{ margin: 0 }}>
                {state.entry_action && <><dt><TermCaption term="Entry action" /></dt><dd style={{ margin: 0 }}>{state.entry_action}</dd></>}
                {state.exit_action && <><dt><TermCaption term="Exit action" /></dt><dd style={{ margin: 0 }}>{state.exit_action}</dd></>}
                {state.activity && <><dt><TermCaption term="Activity" /></dt><dd style={{ margin: 0 }}>{state.activity}</dd></>}
              </dl>
            )}
          </>
        )}
        <ValidationNote issues={issues} subject={state.unique_code} onOpen={onOpenValidation} />
        <SelectionActions
          actions={[
            selectionAction.comment(commentText.commentOnBox, () => onComment({ kind: "node", id: state.id })),
            editable && selectionAction.delete("Delete state…", () => onDeleteState(state)),
          ]}
        />
        {editable && (
          <LabeledSelect
            label="Inside" help={ARCHITECTURE_HELP.stateParent} value={own?.parent_state_id ?? ""} placeholder="Top level"
            options={parents.map((s) => ({ value: s.id, label: stateName(s) }))}
            onChange={(next) => onParentChange(state, next || null)}
          />
        )}
        {editable ? (
          <LabeledSelect
            label="Add transition to" help={ARCHITECTURE_HELP.transitionTo} value="" placeholder="Choose a state…"
            options={model.states.map((s) => ({ value: s.id, label: s.id === state.id ? `${stateName(s)} (itself)` : stateName(s) }))}
            onChange={(targetId) => { if (targetId) onConnect(state, targetId); }}
          />
        ) : null}
        {holds && <p className="text-muted">This is a composite state: it holds other states.</p>}
        <RecordTags key={`tags:${state.id}`} projectId={projectId} artefactType="architecture_state" artefactId={state.id} components={false} />
        <ArtefactLinksPanel key={`links:${state.id}`} projectId={projectId} artefactType="architecture_state" artefactId={state.id} compact />
      </>
    );
  } else if (transition) {
    const from = model.states.find((s) => s.id === transition.source_state_id);
    const to = model.states.find((s) => s.id === transition.target_state_id);
    const loop = transition.source_state_id === transition.target_state_id;
    const points = layout.points.find((p) => p.id === transition.id);
    // A transition's own issue is the ambiguity of two transitions leaving the same state, named by that state's code.
    const issues = issuesFor(model.validation, transition.source_state_code).filter((f) => f.code === "ambiguous");
    title = `${from ? stateName(from) : transition.source_state_code} → ${to ? stateName(to) : transition.target_state_code}`;
    body = (
      <>
        {loop && <p className="text-muted">Loop</p>}
        {editable ? (
          <TransitionSelectionFields
            key={`fields:${transition.id}`} transition={transition} states={model.states}
            autoFocus={focusTransition?.id === transition.id ? focusTransition.field : undefined} onFocused={onTransitionFocused}
            onSave={(changed) => onSaveTransition(transition, changed)}
          />
        ) : (
          <>
            <dl style={{ margin: 0 }}>
              {transition.event && <><dt><TermCaption term="Event" /></dt><dd style={{ margin: 0 }}>{transition.event}</dd></>}
              {transition.guard && <><dt><TermCaption term="Condition (guard)" /></dt><dd style={{ margin: 0 }}>{transition.guard}</dd></>}
              {transition.action && <><dt><TermCaption term="Action" /></dt><dd style={{ margin: 0 }}>{transition.action}</dd></>}
            </dl>
            {transition.description && <MarkdownView text={transition.description} />}
          </>
        )}
        <ValidationNote issues={issues} subject={transition.source_state_code} onOpen={onOpenValidation} />
        <SelectionActions
          actions={[
            selectionAction.comment(commentText.commentOnLine, () => onComment({ kind: "edge", id: transition.id })),
            editable && selectionAction.delete("Delete transition…", () => onDeleteTransition(transition)),
          ]}
        />
        {editable && from && to && !loop && (
          <EndPoints
            from={from} to={to} layout={layout} ends={lineEnds(transition.id)} sourcePoint={points?.source_point ?? null} targetPoint={points?.target_point ?? null}
            vertices={points?.points ?? []} lineShape={points?.line_shape ?? null} defaultShape={model.diagram.line_shape}
            onChange={(change) => onPointsChange(transition, change)}
          />
        )}
      </>
    );
  } else {
    body = <p className="text-muted">Select a state, a transition or a note to see its details.</p>;
  }

  return (
    <DetailCard heading="Selection" title={title} maxHeight={maxHeight} onKeyDown={(event) => returnFocusToCanvas(event, selection)}>
      {body}
    </DetailCard>
  );
}

/**
 * The validation issues that name the selection, as one line with a link that opens the toolbar's Validation list at that
 * state, so the person sees why a state is tinted without the full list repeated here.
 */
function ValidationNote({ issues, subject, onOpen }: { issues: { severity: "error" | "warning" }[]; subject: string; onOpen: (subject: string) => void }) {
  if (issues.length === 0) return null;
  const errors = issues.filter((i) => i.severity === "error").length;
  const count = `${issues.length} ${issues.length === 1 ? "issue" : "issues"}`;
  return (
    <p className="row" style={{ margin: 0, gap: "var(--space-2)", alignItems: "center" }}>
      <button type="button" className="btn btn-sm" aria-label={`Show ${count} in Validation`} onClick={() => onOpen(subject)}>{count}</button>
      <span className="text-muted">{errors > 0 ? `${errors} ${errors === 1 ? "error" : "errors"}` : "warnings only"}</span>
    </p>
  );
}

/** The two attach-point selects of a transition between different states, its shape and its vertices. */
function EndPoints({
  from, to, layout, ends, sourcePoint, targetPoint, vertices, lineShape, defaultShape, onChange,
}: {
  from: ArchitectureState;
  to: ArchitectureState;
  layout: StateMachineLayout;
  ends: LineEnds | null;
  sourcePoint: AttachPoint | null;
  targetPoint: AttachPoint | null;
  vertices: LineWaypoint[];
  lineShape: LineShape | null;
  defaultShape: LineShape;
  onChange: (change: LineRouteChange) => void;
}) {
  const a = geometry(layout, from);
  const b = geometry(layout, to);
  if (!ends) return null;
  const [sourceAutomatic, targetAutomatic] = ends.automatic;
  const [first, last] = ends.current;
  const newPoint = suggestWaypoint(pointXY(a, first), vertices, pointXY(b, last));
  const offered = (state: ArchitectureState) => (isMarkerKind(state.kind) ? SIDE_POINTS : ATTACH_POINTS);
  const options = (state: ArchitectureState, automatic: AttachPoint) => [
    { value: "", label: `Automatic (${ATTACH_POINT_LABEL[automatic]})` },
    ...offered(state).map((p) => ({ value: p, label: ATTACH_POINT_LABEL[p] })),
  ];
  const parse = (value: string): AttachPoint | null => (ATTACH_POINTS.find((p) => p === value) ?? null);
  return (
    <>
      <LabeledSelect
        label="Line starts at" help={ARCHITECTURE_HELP.diagramLineFrom} placeholder={null} value={sourcePoint ?? ""}
        options={options(from, sourceAutomatic)} onChange={(value) => onChange({ sourcePoint: parse(value) })}
      />
      <LabeledSelect
        label="Line ends at" help={ARCHITECTURE_HELP.diagramLineTo} placeholder={null} value={targetPoint ?? ""}
        options={options(to, targetAutomatic)} onChange={(value) => onChange({ targetPoint: parse(value) })}
      />
      <LineVertexFields points={vertices} lineShape={lineShape} defaultShape={defaultShape} editable newPoint={newPoint} onChange={onChange} />
    </>
  );
}
