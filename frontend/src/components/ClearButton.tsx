/**
 * Module: components/ClearButton
 *
 * The one control that empties a value or removes one item: a compact icon "X" drawn directly
 * after the value it acts on (an owner badge, a chip, a colour, a picture, a filter). It is part
 * of the thing it controls, not a toolbar button, so it takes no text, no border and no `btn`
 * height; the glyph is 14px and the clickable area is extended past the visible box (see
 * `.clear-button`) so it stays a usable touch target.
 *
 * Its accessible name and tooltip are the same text and must name the field or item
 * ("Clear: Owner", "Remove sort key 2"). A caller renders it only while there is something to
 * clear, never disabled-empty. Clearing many things at once is a button or a menu row, not this
 * (docs/ux-style-guide.md, "Pattern: clear control").
 *
 * Dependencies: `Tooltip` for the hover and focus text (a native `title` is not used).
 */
import { X } from "lucide-react";

import { Tooltip } from "./Tooltip";

/**
 * @param label Accessible name and tooltip text; name the field or item it empties.
 * @param onClick Called when pressed; the caller opens its own confirmation where the tier requires one.
 * @param disabled Disables the control (for example while the form is saving).
 */
export function ClearButton({
  label, onClick, disabled = false,
}: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <Tooltip label={label} className="clear-button-wrap">
      <button type="button" className="clear-button" aria-label={label} onClick={onClick} disabled={disabled}>
        <X size={14} aria-hidden="true" />
      </button>
    </Tooltip>
  );
}
