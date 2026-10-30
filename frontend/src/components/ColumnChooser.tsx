/**
 * Module: components/ColumnChooser
 *
 * The one control for choosing which optional columns a list shows: an icon button that opens a popover with a
 * checkbox per column, the always-on Name column shown ticked and locked, and a reset to the list's defaults.
 *
 * Responsibilities:
 * - Name the columns and report each tick; the list owns the choice (`useColumnChoice` remembers it per person).
 * - Say when the choice is not the default (accent border on the button, like `SettingsPopoverButton`).
 *
 * Design decisions: changes apply as they are ticked, so there is no Save. The always-on column is listed so a
 * person sees why it cannot be unticked, instead of wondering where it went.
 *
 * Dependencies: `Popover`, `Tooltip`, `CheckboxField`, `lucide-react`.
 */
import { Columns3 } from "lucide-react";
import { useRef, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { CheckboxField } from "./FormFields";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

/** A column the person can show or hide. */
export interface ChooserColumn {
  id: string;
  label: string;
}

/**
 * @param columns The optional columns, in the order the list draws them.
 * @param visible The ids of the columns now shown.
 * @param onToggle Called with a column id and whether it should now be shown.
 * @param onReset Called to return to the list's default columns.
 * @param isDefault True when the shown columns are the defaults (the reset is then disabled).
 * @param alwaysOn The label of the column that cannot be hidden (usually Name), shown ticked and locked.
 */
export function ColumnChooser({
  columns, visible, onToggle, onReset, isDefault, alwaysOn,
}: {
  columns: ChooserColumn[];
  visible: readonly string[];
  onToggle: (id: string, shown: boolean) => void;
  onReset: () => void;
  isDefault: boolean;
  alwaysOn: string;
}) {
  const text = useStrings().columnChooser;
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <Tooltip label={text.label}>
        <button
          ref={triggerRef} type="button" className={`btn btn-icon${isDefault ? "" : " btn-marked"}`}
          aria-label={text.label} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        >
          <Columns3 size={16} aria-hidden="true" />
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} title={text.title} onClose={() => setOpen(false)} fit>
          <div className="stack" style={{ gap: "var(--space-2)" }}>
            <CheckboxField label={alwaysOn} checked onChange={() => {}} disabled title={text.alwaysOn} helpNotNeeded />
            {columns.map((c) => (
              <CheckboxField key={c.id} label={c.label} checked={visible.includes(c.id)} onChange={(shown) => onToggle(c.id, shown)} helpNotNeeded />
            ))}
            <button type="button" className="btn btn-sm" disabled={isDefault} onClick={onReset}>{text.reset}</button>
          </div>
        </Popover>
      )}
    </>
  );
}
