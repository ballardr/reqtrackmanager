/**
 * Module: components/LabeledSelect
 *
 * The `<label className="stack"><span>{label}</span><select className="input"
 * ...>` block that `RequirementMappingsModal.tsx`, the old inline "Add
 * compliance link" popover, and the new requirement-link picker's cascading
 * selects all needed byte-for-byte — extracted once a third and fourth
 * occurrence made it a genuine repeated pattern (`CLAUDE.md`'s reuse rule). Purely presentational: one labelled
 * `<select>` with a leading placeholder option and an optional disabled
 * state (plus `help`/`helpNotNeeded` for the field's `(?)` help, `ariaLabel` when the accessible name must differ from the visible label, `hint` and `inputProps`
 * for the odd `select` attribute). Callers own any cascading-reset behaviour (e.g. clearing a child
 * selection when its parent changes) — this component only renders.
 */
import { useId } from "react";
import type { ReactNode, SelectHTMLAttributes } from "react";

import { FieldShell } from "./FieldHelp";
import type { FieldHelpProps } from "./FieldHelp";

export function LabeledSelect({
  label,
  value,
  onChange,
  options,
  disabled,
  placeholder = "Select…",
  ariaLabel,
  hint,
  inputProps,
  help,
  required,
}: FieldHelpProps & {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
  /** Leading empty option's text; `null` omits it, for a select that
   * always has a value (e.g. a scoring-model switcher). */
  placeholder?: string | null;
  /** Overrides the label as the select's accessible name when they differ. */
  ariaLabel?: string;
  hint?: ReactNode;
  inputProps?: Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "className" | "aria-label" | "disabled">;
}) {
  const id = useId();
  const controlId = inputProps?.id ?? id;
  return (
    <FieldShell label={label} controlId={controlId} help={help} hint={hint} required={required}>
      <select
        {...inputProps}
        required={required}
        aria-required={required || undefined}
        id={controlId}
        className="input"
        aria-label={ariaLabel ?? label}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {placeholder !== null && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

/**
 * A select with no visible caption, for a control that sits in a row of other controls (an "add to this
 * group" picker beside its button, a column mapping inside a table cell) where the row or the cell heading
 * is the caption. The accessible name is required, so it cannot be left unnamed. A field in a form is a
 * `LabeledSelect`.
 *
 * @param ariaLabel The select's accessible name.
 * @param placeholder Leading empty option's text; `null` omits it.
 * @param maxWidth Optional width cap in pixels.
 */
export function InlineSelect({
  ariaLabel,
  value,
  onChange,
  options,
  disabled,
  placeholder = "Select…",
  maxWidth,
  inputProps,
}: {
  ariaLabel: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
  placeholder?: string | null;
  maxWidth?: number;
  inputProps?: Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "className" | "aria-label" | "disabled">;
}) {
  return (
    <select
      {...inputProps}
      className="input"
      style={maxWidth ? { maxWidth } : undefined}
      aria-label={ariaLabel}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {placeholder !== null && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
