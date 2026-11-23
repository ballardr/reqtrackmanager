/**
 * Module: components/ViewSwitch
 *
 * A compact switch between the views of one field (the Markdown editor's Visual, Write and Preview): a small group of
 * toolbar-size icon buttons (`ToolbarButton`, so it reads as part of the field), the chosen one pressed, each with a
 * tooltip and an accessible name of the same text.
 *
 * Responsibilities: report the chosen view. The pressed button keeps the focus (it is not a toolbar action on the
 * editor), so a view that replaces the focused editor does not end the use of the field (`ActiveFieldFrame` follows focus).
 *
 * Design decision: buttons with `aria-pressed`, not tabs: the views are alternative renderings of one value inside a
 * form field, not panels of a page, and a tab strip is larger than the caption it sits beside.
 *
 * Dependencies: `ToolbarButton`, lucide icons.
 */
import type { LucideIcon } from "lucide-react";

import { ToolbarButton } from "./ToolbarButton";

/** One view of the field. */
export interface ViewSwitchOption<K extends string> {
  key: K;
  /** The tooltip and accessible name. */
  label: string;
  icon: LucideIcon;
}

/**
 * @param label The group's accessible name ("Editor view").
 * @param options The views, in order.
 * @param active The chosen view's key.
 * @param onChange Called with the key of the view pressed.
 * @param disabled Whether the views are unavailable.
 */
export function ViewSwitch<K extends string>({ label, options, active, onChange, disabled }: {
  label: string;
  options: ViewSwitchOption<K>[];
  active: K;
  onChange: (key: K) => void;
  disabled?: boolean;
}) {
  return (
    // A view replaces the editor that has the focus, so the pressed button takes the focus itself (an enclosing toolbar
    // slot keeps focus in the editor for its formatting buttons, which would leave the field when the editor goes).
    <div
      className="row view-switch" role="group" aria-label={label} style={{ gap: "var(--space-1)", flexWrap: "nowrap" }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {options.map((option) => (
        <ToolbarButton
          key={option.key} icon={option.icon} label={option.label} active={active === option.key} disabled={disabled}
          onClick={() => onChange(option.key)}
        />
      ))}
    </div>
  );
}
