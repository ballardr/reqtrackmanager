/**
 * Module: components/LabeledSelect
 *
 * The `<label className="stack"><span>{label}</span><select className="input"
 * ...>` block that `RequirementMappingsModal.tsx`, the old inline "Add
 * compliance link" popover, and the new requirement-link picker's cascading
 * selects all needed byte-for-byte — extracted once a third and fourth
 * occurrence made it a genuine repeated pattern (`CLAUDE.md`'s reuse rule). Purely presentational: one labelled
 * `<select>` with a leading placeholder option and an optional disabled
 * state (plus `ariaLabel` when the accessible name must differ from the visible label, `hint` and `inputProps`
 * for the odd `select` attribute). Callers own any cascading-reset behaviour (e.g. clearing a child
 * selection when its parent changes) — this component only renders.
 */
import type { ReactNode, SelectHTMLAttributes } from "react";

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
}: {
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
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <select
        {...inputProps}
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
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}
