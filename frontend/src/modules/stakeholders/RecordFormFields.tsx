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

/**
 * A labelled checkbox with an optional hint underneath. With `heading` it is laid out like the other
 * fields (a heading line, then the control), so it lines up with an input beside it in a `FormGrid`;
 * `label` is then the checkbox's own text and `ariaLabel` its accessible name.
 */
export function CheckboxField({
  label, checked, onChange, hint, heading, ariaLabel,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  heading?: string;
  ariaLabel?: string;
}) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      {heading && <span>{heading}</span>}
      <label className="row" style={{ gap: "0.4rem", minHeight: heading ? "2.25rem" : undefined }}>
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={ariaLabel} />
        {label}
      </label>
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </div>
  );
}
