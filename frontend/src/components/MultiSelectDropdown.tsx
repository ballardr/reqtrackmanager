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
 * implementation. Opened from the dropdown trigger the list lines up with it and is as wide as it, like a
 * native select list; the icon-only trigger opens the fixed-width panel to its right.
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

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
  /** Muted text after the label (which record types carry a search field, say). */
  hint?: string;
  onToggle: () => void;
}

export function MultiSelectDropdown({
  triggerLabel,
  options,
  emptyLabel = "None",
  filterable = false,
  summaryLimit,
  id,
  icon,
  addFromFilter,
  disabled = false,
}: {
  /** Accessible name for the closed trigger button and the opened list's title. */
  triggerLabel: string;
  options: MultiSelectOption[];
  /** Shown on the trigger when no option is checked. */
  emptyLabel?: string;
  /** Adds a filter box above a long list; it narrows the options by label and hint as the person types. */
  filterable?: boolean;
  /** Shows "N selected" on the trigger instead of every label once more than this many are checked. */
  summaryLimit?: number;
  /** `id` of the trigger, so a field caption can point at it (`FieldShell`'s `controlId`). */
  id?: string;
  /** Renders the trigger as an icon-only button (named and given a tooltip by `triggerLabel`) instead of a dropdown showing the summary. */
  icon?: ReactNode;
  /**
   * With `filterable`: when the typed text matches no option's label exactly, offers a button (and Enter,
   * while nothing else matches) that hands the text to `onAdd`, so a value that is not in the list can be
   * added from the same box. `label` is the button's text for the typed value; `note` is muted text under it
   * for a caution needed each time a value is added.
   */
  addFromFilter?: { label: (text: string) => string; onAdd: (text: string) => void; note?: string };
  /** Disables the icon-only trigger, e.g. while there is nothing to choose or add. */
  disabled?: boolean;
}) {
  const strings = useStrings();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const checked = options.filter((o) => o.checked);
  const summary =
    summaryLimit !== undefined && checked.length > summaryLimit
      ? strings.common.nSelected(checked.length)
      : checked.map((o) => o.label).join(", ") || emptyLabel;
  const needle = filter.trim().toLowerCase();
  const typed = filter.trim();
  const canAdd = !!addFromFilter && filterable && needle !== "" && !options.some((o) => o.label.trim().toLowerCase() === needle);
  const addTyped = () => {
    if (!addFromFilter || !canAdd) return;
    addFromFilter.onAdd(typed);
    setFilter("");
    // The button that was clicked disappears with the typed text; keep focus in the list so Escape still closes it.
    filterRef.current?.focus();
  };
  const visible = needle ? options.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(needle)) : options;

  const trigger = icon ? (
    <Tooltip label={triggerLabel}>
      <button
        id={id} ref={triggerRef} type="button" className="btn btn-icon" aria-label={triggerLabel} aria-haspopup="true" aria-expanded={open} disabled={disabled}
        onClick={() => { setFilter(""); setOpen((o) => !o); }}
      >
        {icon}
      </button>
    </Tooltip>
  ) : (
      <button
        id={id}
        ref={triggerRef}
        type="button"
        className="input row"
        style={{ justifyContent: "space-between", flexWrap: "nowrap", cursor: "pointer" }}
        title={summary}
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => {
          setFilter("");
          setOpen((o) => !o);
        }}
      >
        {/* `.row`'s own `flex-wrap: wrap` (theme.css) let a long summary
            (more roles checked) wrap onto a second line with just the
            chevron on it, where `justify-content: space-between` left it
            flush left instead of on the right — the chevron visibly
            "moved" depending on how many roles were checked. Forcing
            `nowrap` here and truncating the summary instead keeps the
            chevron pinned to the same spot on every row regardless of
            content length; the untruncated text is still available via
            the `title` above and the opened list itself. */}
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
          {summary}
        </span>
        <ChevronDown size={14} style={{ flexShrink: 0 }} />
      </button>
  );
  return (
    <>
      {trigger}
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} matchAnchor={!icon} placement={icon ? "side" : "below"} onClose={() => setOpen(false)}>
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            {filterable && (
              <input
                ref={filterRef}
                type="search"
                className="input"
                aria-label={strings.common.filterOptions(triggerLabel)}
                placeholder={strings.common.filterPlaceholder}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (visible.length === 0) addTyped();
                  }
                }}
              />
            )}
            <div
              role="group"
              aria-label={triggerLabel}
              className="stack"
              style={{ gap: "var(--space-2)", ...(filterable ? { maxHeight: "18rem", overflowY: "auto" } : {}) }}
            >
              {visible.map((opt) => (
                <label key={opt.value} className="row" style={{ gap: "var(--space-2)", fontSize: "0.85rem", flexWrap: "nowrap" }}>
                  <input
                    type="checkbox"
                    checked={opt.checked}
                    disabled={opt.disabled}
                    aria-label={opt.optionLabel}
                    title={opt.disabled ? opt.title : undefined}
                    onChange={opt.onToggle}
                  />
                  <span>
                    {opt.label}
                    {opt.hint && (
                      <span className="text-muted" style={{ fontSize: "0.75rem" }}>
                        {" "}
                        {opt.hint}
                      </span>
                    )}
                  </span>
                </label>
              ))}
              {canAdd && addFromFilter && (
                <button type="button" className="btn" style={{ justifyContent: "flex-start" }} onClick={addTyped}>
                  {addFromFilter.label(typed)}
                </button>
              )}
              {canAdd && addFromFilter?.note && (
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>{addFromFilter.note}</span>
              )}
              {filterable && visible.length === 0 && !canAdd && (
                <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                  {strings.common.noMatchingOptions}
                </span>
              )}
            </div>
          </div>
        </Popover>
      )}
    </>
  );
}
