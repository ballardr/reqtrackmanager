/**
 * Module: components/ToggleButton
 *
 * A button that is pressed or not (`aria-pressed`), or a plain action button in the same toolbar look: the one
 * button the table editor's toolbar and a block form's on/off setting share.
 *
 * Design decisions: a pressed button carries the accent edge (`btn-marked`), and its state is `aria-pressed`, never
 * colour alone. An icon-only button is named by `label` and shown with a tooltip; one with text (`iconOnly={false}`)
 * is named by that text, so a label lookup finds it either way. `pressed` left out makes it an action button.
 */
import type { ReactNode } from "react";

import { Tooltip } from "./Tooltip";

/**
 * @param label The accessible name (and the tooltip of an icon-only button).
 * @param pressed Whether it is on; absent for an action button.
 * @param onClick Called on a press.
 * @param disabled Disables it.
 * @param iconOnly Draws a square icon button with a tooltip (default); false draws `children` as the button's text.
 * @param children The icon, or the text.
 */
export function ToggleButton({
  label, pressed, onClick, disabled, iconOnly = true, children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  disabled?: boolean;
  iconOnly?: boolean;
  children: ReactNode;
}) {
  const button = (
    <button
      type="button" className={`btn btn-sm${iconOnly ? " btn-icon" : ""}${pressed ? " btn-marked" : ""}`} aria-label={label}
      aria-pressed={pressed} disabled={disabled} onClick={onClick}
    >
      {children}
    </button>
  );
  return iconOnly ? <Tooltip label={label}>{button}</Tooltip> : button;
}
