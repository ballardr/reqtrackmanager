/**
 * Module: modules/architecture/StateMachineSelectionPanel
 *
 * The state machine editor's "Selection" card: what the selected state or transition is and what can be done with it.
 * - A state: its code, kind, description and entry, exit and do lines, its tags (the shared `RecordTags`; a state sits in no
 *   component), the findings that name it; Edit (the shared state form), Comment, Delete (confirmed, naming how many
 *   transitions and links go with it) and, for an ordinary or marker state, "Inside": the state it sits inside, the keyboard
 *   route to dragging it into a frame. A state that holds others cannot become a marker.
 * - A transition: its two states, event, guard, action and description, the findings that name it, the attach points of its two
 *   ends (the keyboard route to dragging a line's end); Edit, Comment and Delete.
 * - Nothing selected: a short prompt.
 *
 * Design decisions:
 * - The actions are icon buttons from the shared `SelectionActions`, the same set the block diagram's card uses.
 * - The card stores nothing: every action is a callback onto the page, which stores content at once and the drawing on Save.
 */
import { ActivityNote } from "../../components/ActivityNote";
import { DetailCard } from "../../components/DetailCard";
import { FieldCaption } from "../../components/FieldHelp";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, SIDE_POINTS, lineAttachPoints, type AttachPoint, type BoxGeometry } from "../../components/graphAttachPoints";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordTags } from "../../components/RecordTags";
import { useStrings } from "../../context/TerminologyContext";
import { ARCHITECTURE_HELP } from "./help";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import { useStateLabel } from "./useStateLabel";
import { descendantIds, findingsFor, isMarkerKind, type StateMachineLayout } from "./stateMachineModel";
import {
  FINDING_SEVERITY_LABEL, STATE_KIND_LABEL, type ArchitectureState, type StateMachineModel, type StateTransition,
} from "./types";

/** The geometry of a state's box as the canvas draws it, with the points a marker offers. */
function geometry(layout: StateMachineLayout, state: ArchitectureState): BoxGeometry {
  const box = layout.boxes.find((b) => b.id === state.id) ?? state;
  return { x: box.x, y: box.y, width: box.width, height: box.height, points: isMarkerKind(state.kind) ? SIDE_POINTS : undefined };
}

/**
 * @param projectId The diagram's project.
 * @param model The model as read.
 * @param layout The drawing being edited.
 * @param selection What is selected on the canvas, or null.
 * @param editable False hides every action that changes the diagram.
 * @param onEditState Opens the state form.
 * @param onEditTransition Opens the transition form.
 * @param onDeleteState Asks to delete the state (the page confirms, naming what goes with it).
 * @param onDeleteTransition Asks to delete the transition (the page confirms).
 * @param onConnect Starts a transition from a state to the state with the given id (the same state for a loop): the keyboard
 *   route to drawing a line between two states.
 * @param onParentChange Puts the state inside another (or at the top level with null); an unsaved drawing edit.
 * @param onPointsChange Sets the attach point of one or both ends of a transition (null is automatic); an unsaved drawing edit.
 * @param onComment Starts a comment on the selected state or transition.
 */
export function StateMachineSelectionPanel({
  projectId, model, layout, selection, editable, onEditState, onEditTransition, onDeleteState, onDeleteTransition, onParentChange,
  onPointsChange, onComment, onConnect,
}: {
  projectId: string;
  model: StateMachineModel;
  layout: StateMachineLayout;
  selection: GraphCanvasSelection | null;
  editable: boolean;
  onEditState: (state: ArchitectureState) => void;
  onEditTransition: (transition: StateTransition) => void;
  onDeleteState: (state: ArchitectureState) => void;
  onDeleteTransition: (transition: StateTransition) => void;
  onConnect: (state: ArchitectureState, targetId: string) => void;
  onParentChange: (state: ArchitectureState, parentId: string | null) => void;
  onPointsChange: (transition: StateTransition, change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null }) => void;
  onComment: (target: { kind: "node" | "edge"; id: string }) => void;
}) {
  const commentText = useStrings().canvasComments;
  const stateName = useStateLabel().label;

  const state = selection?.kind === "node" ? model.states.find((s) => s.id === selection.id) ?? null : null;
  const transition = selection?.kind === "edge" ? model.transitions.find((t) => t.id === selection.id) ?? null : null;

  let body;
  if (state) {
    const holds = layout.boxes.some((b) => b.parent_state_id === state.id);
    const own = layout.boxes.find((b) => b.id === state.id);
    const blocked = new Set([state.id, ...descendantIds(layout, state.id)]);
    const parents = model.states.filter((s) => s.kind === "state" && !blocked.has(s.id));
    const findings = findingsFor(model.findings, state.unique_code);
    body = (
      <>
        <p>
          <strong>{stateName(state)}</strong>
          <span className="text-muted"> · {STATE_KIND_LABEL[state.kind]}</span>
        </p>
        {state.description && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label="Description" help={ARCHITECTURE_HELP.elementDescription} />
            <ActivityNote text={state.description} />
          </div>
        )}
        {!isMarkerKind(state.kind) && (state.entry_action || state.exit_action || state.activity) && (
          <dl style={{ margin: 0 }}>
            {state.entry_action && <><dt className="text-muted">Entry action</dt><dd style={{ margin: 0 }}>{state.entry_action}</dd></>}
            {state.exit_action && <><dt className="text-muted">Exit action</dt><dd style={{ margin: 0 }}>{state.exit_action}</dd></>}
            {state.activity && <><dt className="text-muted">Activity</dt><dd style={{ margin: 0 }}>{state.activity}</dd></>}
          </dl>
        )}
        <FindingList findings={findings} />
        <SelectionActions
          actions={[
            editable && selectionAction.edit("Edit state", () => onEditState(state)),
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
            label="Add transition to" help={ARCHITECTURE_HELP.transitionEnds} value="" placeholder="Choose a state…"
            options={model.states.map((s) => ({ value: s.id, label: s.id === state.id ? `${stateName(s)} (itself)` : stateName(s) }))}
            onChange={(targetId) => { if (targetId) onConnect(state, targetId); }}
          />
        ) : null}
        {holds && <p className="text-muted">This is a composite state: it holds other states.</p>}
        <RecordTags key={state.id} projectId={projectId} artefactType="architecture_state" artefactId={state.id} components={false} />
      </>
    );
  } else if (transition) {
    const from = model.states.find((s) => s.id === transition.source_state_id);
    const to = model.states.find((s) => s.id === transition.target_state_id);
    const loop = transition.source_state_id === transition.target_state_id;
    const points = layout.points.find((p) => p.id === transition.id);
    // A transition's own finding is the ambiguity of two transitions leaving the same state, named by that state's code.
    const findings = findingsFor(model.findings, transition.source_state_code).filter((f) => f.code === "ambiguous");
    body = (
      <>
        <p>
          <strong>{from ? stateName(from) : transition.source_state_code}</strong>
          {" → "}
          <strong>{to ? stateName(to) : transition.target_state_code}</strong>
          {loop && <span className="text-muted"> · loop</span>}
        </p>
        <dl style={{ margin: 0 }}>
          {transition.event && <><dt className="text-muted">Event</dt><dd style={{ margin: 0 }}>{transition.event}</dd></>}
          {transition.guard && <><dt className="text-muted">Guard</dt><dd style={{ margin: 0 }}>{transition.guard}</dd></>}
          {transition.action && <><dt className="text-muted">Action</dt><dd style={{ margin: 0 }}>{transition.action}</dd></>}
        </dl>
        {transition.description && <ActivityNote text={transition.description} />}
        <FindingList findings={findings} />
        <SelectionActions
          actions={[
            editable && selectionAction.edit("Edit transition", () => onEditTransition(transition)),
            selectionAction.comment(commentText.commentOnLine, () => onComment({ kind: "edge", id: transition.id })),
            editable && selectionAction.delete("Delete transition…", () => onDeleteTransition(transition)),
          ]}
        />
        {editable && from && to && !loop && (
          <EndPoints
            from={from} to={to} layout={layout} sourcePoint={points?.source_point ?? null} targetPoint={points?.target_point ?? null}
            onChange={(change) => onPointsChange(transition, change)}
          />
        )}
      </>
    );
  } else {
    body = <p className="text-muted">Select a state or a transition to see its details.</p>;
  }

  return (
    <DetailCard heading="Selection">
      {body}
    </DetailCard>
  );
}

/** The findings that name the selection, shown inside the card so the person sees why a state is tinted. */
function FindingList({ findings }: { findings: { severity: "error" | "warning"; message: string }[] }) {
  if (findings.length === 0) return null;
  return (
    <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
      {findings.map((f) => <li key={`${f.severity}:${f.message}`}>{FINDING_SEVERITY_LABEL[f.severity]}: {f.message}</li>)}
    </ul>
  );
}

/** The two attach-point selects of a transition between different states. */
function EndPoints({
  from, to, layout, sourcePoint, targetPoint, onChange,
}: {
  from: ArchitectureState;
  to: ArchitectureState;
  layout: StateMachineLayout;
  sourcePoint: AttachPoint | null;
  targetPoint: AttachPoint | null;
  onChange: (change: { sourcePoint?: AttachPoint | null; targetPoint?: AttachPoint | null }) => void;
}) {
  const a = geometry(layout, from);
  const b = geometry(layout, to);
  const sourceAutomatic = lineAttachPoints(a, b, null, targetPoint)[0];
  const targetAutomatic = lineAttachPoints(a, b, sourcePoint, null)[1];
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
    </>
  );
}
