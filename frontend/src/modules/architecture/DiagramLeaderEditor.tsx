/**
 * Module: modules/architecture/DiagramLeaderEditor
 *
 * The Selection card's form for a selected leader line of a note: what it ends at, where it starts, how its two ends look and
 * its vertices.
 *
 * Responsibilities:
 * - Offer the keyboard route to what the canvas does with a leader: a "Points at" list (what the page offers: a drawn box or
 *   connection, a state or transition, or a spot with X and Y), the attach point it starts from, and the vertices and curve through the shared `LineVertexFields`.
 * - Say, rather than hide, that a leader points at something that is not drawn.
 * - Go back to the note the leader belongs to, or remove the leader (the note stays).
 *
 * Design decisions:
 * - Nothing here stores anything: every change is a callback, and the editor page owns the layout, its undo history and save.
 * - The list names only what is drawn, but keeps the current target selectable when it is not drawn, so the control always
 *   shows the truth. A spot's X and Y apply when the field is left, as one undo step.
 */
import { InlineTextInput } from "../../components/FormFields";
import { FieldCaption } from "../../components/FieldHelp";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, type AttachPoint } from "../../components/graphAttachPoints";
import type { LineShape } from "../../components/graphLinePath";
import { LabeledSelect } from "../../components/LabeledSelect";
import { labelOptions } from "../../utils/labelOptions";
import { LEADER_SPOT_OPTION, leaderOf, leaderOptionValue, leaderTargetOf, type EditorLeader, type NoteLeaderTarget } from "./noteModel";
import { ARCHITECTURE_HELP } from "./help";
import { LineVertexFields } from "./LineVertexFields";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import { LINE_END_LABEL, type LineEnd, type LineWaypoint } from "./types";

/** A typed position as a number, or null when the text is not one (the field then keeps the old value). */
function parsePosition(text: string): number | null {
  const value = Number(text);
  return text.trim() !== "" && Number.isFinite(value) && Math.abs(value) <= 1_000_000 ? Math.round(value) : null;
}

/** One thing a leader can end at, as the "Points at" list offers it: its option value (`leaderOptionValue`) and its words. */
export interface LeaderTargetOption {
  value: string;
  label: string;
}

/**
 * @param leader The selected leader.
 * @param index Its position among the note's leaders, from 1 (names the card).
 * @param editable Whether the layout can be changed.
 * @param targets What the diagram draws that a leader can end at (the page names them: boxes and connections, or states and transitions).
 * @param help The "Points at" field's help; by default the block diagram's wording (boxes and connections).
 * @param drawn Whether the leader's target is drawn (a leader to something switched off or removed is not).
 * @param newPoint Where an added vertex goes (off the line, chosen by the page, which knows where the line runs).
 * @param onTarget Called with a box, connection or spot to end at.
 * @param onChange Called with the part of the leader that changed (start point, vertices, curve, ends).
 * @param onOpenNote Called to select the note the leader belongs to.
 * @param onRemove Called to remove the leader.
 */
export function DiagramLeaderEditor({
  leader, index, editable, targets, help = ARCHITECTURE_HELP.leaderPointsAt, drawn, newPoint, defaultShape, onTarget, onChange, onOpenNote, onRemove,
}: {
  leader: EditorLeader;
  index: number;
  editable: boolean;
  targets: LeaderTargetOption[];
  help?: string;
  drawn: boolean;
  newPoint: LineWaypoint;
  /** The diagram's default line shape (what a leader with no shape of its own is drawn as). */
  defaultShape: LineShape;
  onTarget: (target: NoteLeaderTarget) => void;
  onChange: (change: Partial<Pick<EditorLeader, "start_point" | "points" | "line_shape" | "start_style" | "end_style">>) => void;
  onOpenNote: () => void;
  onRemove: () => void;
}) {
  const target = leaderOf(leader);
  const current = leaderOptionValue(target);
  const options = [...targets];
  const spot = { value: LEADER_SPOT_OPTION, label: "A spot on the canvas" };
  if (target?.kind === "point" || current === "") options.push(spot);
  else if (!options.some((o) => o.value === current)) options.push({ value: current, label: "An item not on this diagram" });
  // A box or connection leader may be moved to a spot with the same list; the spot starts where the line ends now when known.
  const choose = (value: string) => {
    if (value === LEADER_SPOT_OPTION) onTarget({ kind: "point", x: Math.round(newPoint.x), y: Math.round(newPoint.y) });
    else {
      const chosen = leaderTargetOf(value);
      if (chosen) onTarget(chosen);
    }
  };
  const setSpot = (axis: "x" | "y", text: string) => {
    const value = parsePosition(text);
    if (value !== null && target?.kind === "point") onTarget({ ...target, [axis]: value });
  };
  const endOptions = labelOptions(LINE_END_LABEL);
  const startOptions = [
    { value: "", label: "Automatic" },
    ...ATTACH_POINTS.map((p) => ({ value: p, label: ATTACH_POINT_LABEL[p] })),
  ];
  return (
    <div className="stack">
      <p><strong>Leader {index}</strong></p>
      <LabeledSelect
        label="Points at" help={help} placeholder={null} disabled={!editable} value={current}
        options={[...options, ...(options.some((o) => o.value === LEADER_SPOT_OPTION) ? [] : [spot])]} onChange={choose}
      />
      {target?.kind === "point" && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <FieldCaption label="Spot" help={help} />
          <div className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap" }}>
            <InlineTextInput
              type="number" ariaLabel="Spot X" value={String(target.x)} commitOnBlur disabled={!editable} onChange={(text) => setSpot("x", text)}
            />
            <InlineTextInput
              type="number" ariaLabel="Spot Y" value={String(target.y)} commitOnBlur disabled={!editable} onChange={(text) => setSpot("y", text)}
            />
          </div>
        </div>
      )}
      <LabeledSelect
        label="Starts at" help={ARCHITECTURE_HELP.leaderStartsAt} placeholder={null} disabled={!editable} value={leader.start_point ?? ""}
        options={startOptions} onChange={(value) => onChange({ start_point: ATTACH_POINTS.find((p): p is AttachPoint => p === value) ?? null })}
      />
      <LabeledSelect
        label="Start style" help={ARCHITECTURE_HELP.leaderStartStyle} placeholder={null} disabled={!editable} value={leader.start_style}
        options={endOptions} onChange={(value) => onChange({ start_style: value as LineEnd })}
      />
      <LabeledSelect
        label="End style" help={ARCHITECTURE_HELP.leaderEndStyle} placeholder={null} disabled={!editable} value={leader.end_style}
        options={endOptions} onChange={(value) => onChange({ end_style: value as LineEnd })}
      />
      <LineVertexFields
        points={leader.points} lineShape={leader.line_shape} defaultShape={defaultShape} editable={editable} newPoint={newPoint}
        onChange={({ points, lineShape }) => onChange({ ...(points !== undefined && { points }), ...(lineShape !== undefined && { line_shape: lineShape }) })}
      />
      {!drawn && (
        <p className="text-muted" role="status">The line points at something that is not drawn on this diagram, so it is hidden. It returns with that item.</p>
      )}
      <SelectionActions actions={[selectionAction.owner("Select note", onOpenNote), editable && selectionAction.clear("Remove leader", onRemove)]} />
    </div>
  );
}
