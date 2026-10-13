/**
 * Module: modules/stakeholders/RecordFormFields
 *
 * The labelled controls the Persona, Stakeholder, Need and Engagement
 * create/edit modals build their forms from: a single-line input, a multi-line
 * textarea, a date input and a checkbox, each with a visible label that is
 * also the accessible name (style guide principle 13) and an optional hint
 * underneath.
 */
import type { ReactNode } from "react";

/** A labelled single-line input; `ariaLabel` overrides the label as the accessible name when they differ. */
export function TextField({
  label, value, onChange, ariaLabel, hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
  hint?: ReactNode;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel ?? label} />
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}

/** A labelled multi-line input. */
export function TextAreaField({
  label, value, onChange, rows = 2, hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  hint?: ReactNode;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <textarea className="input" rows={rows} value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} />
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}

/** A labelled date input (`value` is YYYY-MM-DD, or "" for none). */
export function DateField({
  label, value, onChange, hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <input className="input" type="date" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} />
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}

/** A labelled checkbox with an optional hint underneath. */
export function CheckboxField({
  label, checked, onChange, hint,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
}) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <label className="row" style={{ gap: "0.4rem" }}>
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </div>
  );
}
