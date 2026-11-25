/**
 * Module: components/StatFigureLabel
 *
 * The label of a stat figure, interactive when the figure has somewhere to go (shared by `StatBar` and `StatGroups`):
 * `to` is a router link to the page the figure counts (typically an already filtered list); `onActivate` is a button
 * for a figure that opens something in place; with neither it is plain text.
 *
 * The control is stretched over the whole cell or row by `.stat-link::after` (theme.css), so the number is clickable
 * too, while its accessible name is "<label>: <value>". The surrounding cell carries `.stat-linked` for the hover tint.
 */
import { Link } from "react-router-dom";

import type { StatFigureAction } from "../utils/statFigureAction";
import { Tooltip } from "./Tooltip";

/**
 * @param label The figure's label.
 * @param value The figure's value (part of the accessible name only).
 * @param to Optional router destination.
 * @param onActivate Optional in-place action (used when there is no `to`).
 * @param hint Optional tooltip text saying where the figure leads (hover and focus).
 */
export function StatFigureLabel({ label, value, to, onActivate, hint }: { label: string; value: string | number } & StatFigureAction) {
  const name = `${label}: ${value}`;
  let control = <>{label}</>;
  if (to) {
    control = (
      <Link to={to} className="stat-link" aria-label={name}>
        {label}
      </Link>
    );
  } else if (onActivate) {
    control = (
      <button type="button" className="stat-link stat-link--button" aria-label={name} onClick={onActivate}>
        {label}
      </button>
    );
  } else {
    return control;
  }
  // The tooltip explains the destination on hover (following the pointer, since the whole cell is the target) and keyboard focus; the control's own name stays "<label>: <value>".
  return hint ? <Tooltip label={hint} followPointer>{control}</Tooltip> : control;
}
