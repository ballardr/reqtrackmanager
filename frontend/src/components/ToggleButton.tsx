/**
 * Module: components/ToggleButton
 *
 * A button that is pressed or not (`aria-pressed`), or a plain action button in the same toolbar look: the one
 * button the table editor's toolbar and a block form's on/off setting share.
 *
 * Design decisions: a pressed button carries the accent edge (`btn-marked`), and its state is `aria-pressed`, never
 * colour alone. An icon-only button is named by `label` and shown with a tooltip; one with text (`iconOnly={false}`)
 * is named by that text, so a label lookup finds it either way. `pressed` left out makes it an action button.
 * Help for the button is its tooltip (`help`), never a `(?)` beside it (docs/ux-style-guide.md, "Pattern: help on
 * interactive elements"): an icon-only button's tooltip is its name, then the help on the lines after it.
 */
import { useId, type ReactNode } from "react";

import { Tooltip } from "./Tooltip";

/**
 * @param label The accessible name (and the tooltip of an icon-only button).
 * @param pressed Whether it is on; absent for an action button.
 * @param onClick Called on a press.
 * @param disabled Disables it.
 * @param help What the button does, one line per state for a toggle; shown as the button's tooltip and its description.
 * @param iconOnly Draws a square icon button with a tooltip (default); false draws `children` as the button's text.
 * @param children The icon, or the text.
 */
export function ToggleButton({
  label, pressed, onClick, disabled, help, iconOnly = true, children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  disabled?: boolean;
  help?: string;
  iconOnly?: boolean;
  children: ReactNode;
}) {
  const bubbleId = useId();
  const button = (
    <button
      type="button" className={`btn btn-sm${iconOnly ? " btn-icon" : ""}${pressed ? " btn-marked" : ""}`} aria-label={label}
      aria-describedby={help ? bubbleId : undefined} aria-pressed={pressed} disabled={disabled} onClick={onClick}
    >
      {children}
    </button>
  );
  if (help) {
    return <Tooltip label={iconOnly ? `${label}\n${help}` : help} wrap bubbleId={bubbleId}>{button}</Tooltip>;
  }
  return iconOnly ? <Tooltip label={label}>{button}</Tooltip> : button;
}
