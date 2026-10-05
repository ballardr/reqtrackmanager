/**
 * Module: modules/stakeholders/RecordFormFields
 *
 * The labelled text controls the Persona and Stakeholder create/edit modals
 * both build their forms from: a single-line input and a multi-line textarea,
 * each with a visible label that is also the accessible name (style guide
 * principle 13) and an optional hint underneath.
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
