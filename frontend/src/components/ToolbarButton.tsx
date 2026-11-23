/**
 * Module: components/ToolbarButton
 *
 * One icon button of an editor toolbar (the policy editor, the Markdown editor): an icon with a tooltip and an
 * accessible name of the same text, optionally pressed (a format that is on) or unavailable.
 *
 * Design decision: a toolbar sits inside a field's body, so its buttons are the small size (28px, `btn-sm btn-icon`); a
 * button that opens a panel (`opens`) takes the panel's anchor through `buttonRef` and reports whether the panel is open.
 *
 * Dependencies: `Tooltip`, lucide icons.
 */
import type { LucideIcon } from "lucide-react";
import type { RefObject } from "react";

import { Tooltip } from "./Tooltip";

/**
 * @param icon The icon drawn.
 * @param label The tooltip and accessible name.
 * @param active Whether the format is on (shown pressed).
 * @param disabled Whether the action is unavailable.
 * @param onClick Called when the button is pressed.
 * @param buttonRef Receives the button element (the anchor of a panel the button opens).
 * @param opens Set for a button that opens a panel: whether the panel is open.
 */
export function ToolbarButton({ icon: Icon, label, active, disabled, onClick, buttonRef, opens }: {
  icon: LucideIcon; label: string; active?: boolean; disabled?: boolean; onClick: () => void;
  buttonRef?: RefObject<HTMLButtonElement | null>; opens?: boolean;
}) {
  return (
    <Tooltip label={label}>
      <button
        ref={buttonRef} type="button" className={`btn btn-sm btn-icon ${active ? "btn-primary" : ""}`} aria-label={label}
        aria-pressed={opens === undefined ? active : undefined} aria-haspopup={opens === undefined ? undefined : "dialog"}
        aria-expanded={opens} disabled={disabled} onClick={onClick}
      >
        <Icon size={16} />
      </button>
    </Tooltip>
  );
}
