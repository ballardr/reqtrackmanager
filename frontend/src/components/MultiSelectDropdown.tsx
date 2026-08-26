/**
 * Module: components/MultiSelectDropdown
 *
 * A compact, closed-by-default control for picking any subset of a small,
 * fixed option list — visually a single dropdown (matches every other
 * `<select className="input">` in the app when closed, showing the
 * currently-checked options' own labels as its summary text) but opens into
 * a checkbox list rather than forcing single-choice, for a field whose
 * underlying data genuinely allows holding more than one value at once. See
 * `docs/ux-style-guide.md`'s "Pattern: multi-select dropdown" — first call
 * site is `OrgAdminPage.tsx`'s Users table Roles column, replacing an
 * always-visible checkbox stack that read as a broken single-select and
 * crowded the row.
 *
 * Reuses `Popover` for the revealed checkbox list, the same way `ActionMenu`
 * and `SplitButtonTrigger` already do — positioning, focus trap, and
 * outside-click/Escape close all come from there rather than a second
 * implementation.
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState } from "react";

import { Popover } from "./Popover";

export interface MultiSelectOption {
  value: string;
  /** Visible label, used both in the closed trigger's summary and the open list. */
  label: string;
  checked: boolean;
  disabled?: boolean;
  /** Tooltip shown while `disabled`, explaining why this option can't be toggled. */
  title?: string;
  /** Full accessible name for this option's checkbox, e.g. "Grant Org admin to Alex Morgan". */
  optionLabel: string;
  onToggle: () => void;
}

export function MultiSelectDropdown({
  triggerLabel,
  options,
  emptyLabel = "None",
}: {
  /** Accessible name for the closed trigger button and the opened list's title. */
  triggerLabel: string;
  options: MultiSelectOption[];
  /** Shown on the trigger when no option is checked. */
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const summary =
    options
      .filter((o) => o.checked)
      .map((o) => o.label)
      .join(", ") || emptyLabel;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="input row"
        style={{ justifyContent: "space-between", cursor: "pointer" }}
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span>{summary}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} onClose={() => setOpen(false)}>
          <div role="group" aria-label={triggerLabel} className="stack" style={{ gap: "0.35rem" }}>
            {options.map((opt) => (
              <label key={opt.value} className="row" style={{ gap: "0.35rem", fontSize: "0.85rem" }}>
                <input
                  type="checkbox"
                  checked={opt.checked}
                  disabled={opt.disabled}
                  aria-label={opt.optionLabel}
                  title={opt.disabled ? opt.title : undefined}
                  onChange={opt.onToggle}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </Popover>
      )}
    </>
  );
}
