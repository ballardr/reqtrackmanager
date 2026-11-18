/**
 * Module: components/IconAction
 *
 * A small icon-only button (or link) named by its label, which is also its tooltip: the one shape for an action in a
 * crowded place (a comment row, a Selection card, a table row) where a text button would compete with the content
 * (docs/ux-style-guide.md, "Pattern: help on interactive elements" and "Pattern: button sizes").
 *
 * Design decisions:
 * - The label is both the accessible name and the tooltip, so a pointer, keyboard and screen reader user get the same
 *   words; the caller never writes a separate `aria-label`.
 * - A destination is a real link (`to`), not a button that navigates, so it opens in a new tab and is announced as a link.
 */
import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Tooltip } from "./Tooltip";

/**
 * @param label The action's name: the control's accessible name and its tooltip.
 * @param onClick Called when the button is pressed (a button, when `to` is absent).
 * @param to A route to open; renders a link instead of a button.
 * @param disabled Whether the button is unavailable (a button only).
 * @param danger Draws the destructive outline.
 * @param help What the action does when its name alone does not say; shown under the name in the tooltip and read as the
 *   control's description.
 * @param children The icon.
 */
export function IconAction({
  label, onClick, to, disabled, danger, help, children,
}: {
  label: string;
  onClick?: () => void;
  to?: string;
  disabled?: boolean;
  danger?: boolean;
  help?: string;
  children: ReactNode;
}) {
  const bubbleId = useId();
  const className = `btn btn-sm btn-icon${danger ? " btn-danger" : ""}`;
  const describedBy = help ? bubbleId : undefined;
  return (
    <Tooltip label={help ? `${label}\n${help}` : label} wrap={Boolean(help)} bubbleId={bubbleId}>
      {to !== undefined ? (
        <Link className={className} to={to} aria-label={label} aria-describedby={describedBy}>{children}</Link>
      ) : (
        <button type="button" className={className} aria-label={label} aria-describedby={describedBy} disabled={disabled} onClick={onClick}>{children}</button>
      )}
    </Tooltip>
  );
}
