/**
 * Module: components/SettingsPopoverButton
 *
 * A small gear button that opens a `Popover` holding a few settings of one control (a column, a view) instead of a row
 * of selects always shown. It is the settings counterpart of `AddPopoverButton`: same anchored `Popover`, same Escape
 * and outside-click closing.
 *
 * Design decisions: the settings are hidden until opened, so the current choice must still show: `label` (accessible
 * name and tooltip) states it and `marked` draws an accent border when it is not the default. Changes apply as made, so
 * there is no Save. `defaultOpen` opens it on first render (a row just added, whose settings must be filled in).
 */
import { Settings } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

/**
 * @param label Accessible name and tooltip; should state the current settings, e.g. "Score settings: Impact x Likelihood".
 * @param title Title of the popover.
 * @param marked True when a setting differs from its default.
 * @param defaultOpen Open on first render.
 * @param children The settings controls.
 */
export function SettingsPopoverButton({
  label, title, marked = false, defaultOpen = false, children,
}: { label: string; title: string; marked?: boolean; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <Tooltip label={label}>
        <button
          ref={triggerRef}
          type="button"
          className={`btn btn-sm btn-icon${marked ? " btn-marked" : ""}`}
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <Settings size={14} aria-hidden="true" />
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} title={title} onClose={() => setOpen(false)} fit>
          {children}
        </Popover>
      )}
    </>
  );
}
