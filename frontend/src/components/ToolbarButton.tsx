/**
 * Module: components/ToolbarButton
 *
 * One icon button of an editor toolbar (the policy editor, the Markdown editor): an icon with a tooltip and an
 * accessible name of the same text, optionally pressed (a format that is on) or unavailable.
 *
 * Dependencies: `Tooltip`, lucide icons.
 */
import type { LucideIcon } from "lucide-react";

import { Tooltip } from "./Tooltip";

/**
 * @param icon The icon drawn.
 * @param label The tooltip and accessible name.
 * @param active Whether the format is on (shown pressed).
 * @param disabled Whether the action is unavailable.
 * @param onClick Called when the button is pressed.
 */
export function ToolbarButton({ icon: Icon, label, active, disabled, onClick }: {
  icon: LucideIcon; label: string; active?: boolean; disabled?: boolean; onClick: () => void;
}) {
  return (
    <Tooltip label={label}>
      <button
        type="button" className={`btn ${active ? "btn-primary" : ""}`} aria-label={label} aria-pressed={active}
        disabled={disabled} onClick={onClick}
      >
        <Icon size={16} />
      </button>
    </Tooltip>
  );
}
