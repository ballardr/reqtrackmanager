/**
 * Module: modules/architecture/LineVertexFields
 *
 * The Selection card's line shape and "Vertices" section for a selected line, shared by the block diagram (a connection's line),
 * the state machine diagram (a transition) and a note's leader: the line's own shape (Straight, Curved or Spline, or the
 * diagram's default), then its vertices as X and Y positions, an action to add one and one to remove them all.
 *
 * Responsibilities:
 * - Be the keyboard and non-pointer route to what dragging does on the canvas (add, move and remove a vertex).
 * - Apply a typed position once, when the field is left, so one edit is one undo step.
 *
 * Design decisions:
 * - Nothing here stores anything: every change is a callback and the editor page owns the layout, its history and the save.
 * - A new vertex is placed by the caller (`newPoint`, off the line's middle), because only the page knows where the line is.
 * - The shape is the line's own choice and may be set back to the diagram's default (`null`); it does not depend on vertices.
 * - The section is not shown at all when the line cannot keep a route (the caller omits it and says why).
 */
import { RotateCcw, Plus, X } from "lucide-react";

import { FieldCaption } from "../../components/FieldHelp";
import { InlineTextInput } from "../../components/FormFields";
import { IconAction } from "../../components/IconAction";
import { LineShapeSelect } from "../../components/LineShapeSelect";
import { MAX_WAYPOINTS, moveWaypoint, removeWaypoint, type LineShape } from "../../components/graphLinePath";
import { ARCHITECTURE_HELP } from "./help";
import type { LineWaypoint } from "./types";

/** A typed position as a number, or null when the text is not one (the field then keeps the old value). */
function parsePosition(text: string): number | null {
  const value = Number(text);
  return text.trim() !== "" && Number.isFinite(value) && Math.abs(value) <= 1_000_000 ? Math.round(value) : null;
}

/**
 * @param points The line's vertices in order from its source to its target.
 * @param lineShape The line's own shape, or null when it follows the diagram's default.
 * @param defaultShape The diagram's default shape (what a line with no shape of its own is drawn as).
 * @param editable Whether the drawing can be changed; a read-only card lists the points and offers no action.
 * @param newPoint Where an added vertex goes (the caller's choice, off the line).
 * @param onChange Called with the whole new list of vertices and/or the new shape (null: the diagram's default).
 */
export function LineVertexFields({
  points, lineShape, defaultShape, editable, newPoint, onChange,
}: {
  points: LineWaypoint[];
  lineShape: LineShape | null;
  defaultShape: LineShape;
  editable: boolean;
  newPoint: LineWaypoint;
  onChange: (change: { points?: LineWaypoint[]; lineShape?: LineShape | null }) => void;
}) {
  if (!editable && points.length === 0 && lineShape === null) return null;
  const setPosition = (index: number, axis: "x" | "y", text: string) => {
    const value = parsePosition(text);
    if (value !== null) onChange({ points: moveWaypoint(points, index, { ...points[index], [axis]: value }) });
  };
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <LineShapeSelect value={lineShape} fallback={defaultShape} disabled={!editable} onChange={(next) => onChange({ lineShape: next })} />
      <FieldCaption label="Vertices" help={ARCHITECTURE_HELP.lineVertices} />
      {points.length === 0 ? <p className="text-muted">No vertices.</p> : (
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} aria-label="Vertices">
          {points.map((at, i) => (
            <li key={i} className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap" }}>
              <span className="text-muted" style={{ minWidth: "1.25rem" }}>{i + 1}</span>
              <InlineTextInput
                type="number" ariaLabel={`Vertex ${i + 1} X`} value={String(at.x)} commitOnBlur disabled={!editable}
                onChange={(text) => setPosition(i, "x", text)}
              />
              <InlineTextInput
                type="number" ariaLabel={`Vertex ${i + 1} Y`} value={String(at.y)} commitOnBlur disabled={!editable}
                onChange={(text) => setPosition(i, "y", text)}
              />
              {editable && (
                <IconAction label={`Remove vertex ${i + 1}`} onClick={() => onChange({ points: removeWaypoint(points, i) })}><X /></IconAction>
              )}
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <div className="row" role="group" aria-label="Vertex actions" style={{ gap: "var(--space-2)" }}>
          <IconAction label="Add vertex" disabled={points.length >= MAX_WAYPOINTS} onClick={() => onChange({ points: [...points, newPoint] })}>
            <Plus />
          </IconAction>
          <IconAction label="Reset vertices" disabled={points.length === 0} onClick={() => onChange({ points: [] })}>
            <RotateCcw />
          </IconAction>
        </div>
      )}
    </div>
  );
}
