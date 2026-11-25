/**
 * Module: components/ClearButton
 *
 * The one control that empties a value or removes one item: a compact icon "X" directly after the value it acts on
 * (an owner badge, a chip, a colour, a filter). It takes no text, border or `btn` height; the glyph is 14px and the
 * clickable area extends past the visible box (`.clear-button`) as a touch target.
 *
 * Its accessible name and tooltip are the same text and name the field or item ("Clear: Owner"). A caller renders
 * it only while there is something to clear. Clearing many things is a button or menu row, not this
 * (docs/ux-style-guide.md, "Pattern: clear control").
 *
 * Dependencies: `Tooltip` (a native `title` is not used).
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
