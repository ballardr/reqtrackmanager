/**
 * Module: components/FormFields
 *
 * The labelled controls every create/edit form is built from (docs/ux-style-guide.md, "Pattern:
 * compact forms and add-on-demand"): a single-line input, a multi-line textarea, a date input and a
 * checkbox, each with a visible label that is also the accessible name (principle 13) and an optional
 * hint underneath. Lay them out in a `FormGrid`; pick from a list with `LabeledSelect` and people with
 * `PrincipalFormField`.
 */
import { useId } from "react";
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { ToggleSwitch } from "./ToggleSwitch";

/** Attributes a field passes straight to its control (type, min, max, maxLength, autoFocus, style…); the field owns the rest. */
type InputExtras = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "className" | "aria-label" | "placeholder" | "disabled">;
type TextAreaExtras = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "className" | "aria-label" | "rows" | "disabled">;

/** The caption line of a field whose label carries a control beside it (an `OverridePill`): the label is tied to its input by `htmlFor`. */
function LabelRow({ htmlFor, label, extra }: { htmlFor: string; label: string; extra: ReactNode }) {
  return (
    <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
      <label htmlFor={htmlFor}>{label}</label>
      {extra}
    </span>
  );
}

/** A labelled single-line input; `ariaLabel` overrides the label as the accessible name when they differ. */
export function TextField({
  label, value, onChange, ariaLabel, hint, placeholder, disabled, inputProps, labelExtra,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
  hint?: ReactNode;
  placeholder?: string;
  disabled?: boolean;
  inputProps?: InputExtras;
  /** A control beside the label (an `OverridePill`); the label is then a sibling of the input, not its wrapper. */
  labelExtra?: ReactNode;
}) {
  const id = useId();
  const input = (
    <input
      {...inputProps} id={labelExtra ? (inputProps?.id ?? id) : inputProps?.id} className="input" value={value}
      onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel ?? label} placeholder={placeholder} disabled={disabled}
    />
  );
  const hintNode = hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>;
  if (labelExtra) {
    return (
      <div className="stack" style={{ gap: "0.25rem" }}>
        <LabelRow htmlFor={inputProps?.id ?? id} label={label} extra={labelExtra} />
        {input}
        {hintNode}
      </div>
    );
  }
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      {input}
      {hintNode}
    </label>
  );
}

/**
 * A labelled multi-line input; `ariaLabel` overrides the label as the accessible name when they differ.
 * `autoGrow` swaps the fixed `rows` for a box that grows with its content (see `AutoGrowTextarea`); `rows`
 * is then ignored.
 */
export function TextAreaField({
  label, value, onChange, rows = 2, hint, ariaLabel, disabled, inputProps, autoGrow, labelExtra,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  hint?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  inputProps?: TextAreaExtras;
  autoGrow?: boolean;
  /** A control beside the label (an `OverridePill`); the label is then a sibling of the control, not its wrapper. */
  labelExtra?: ReactNode;
}) {
  const id = useId();
  const controlId = labelExtra ? (inputProps?.id ?? id) : inputProps?.id;
  const control = autoGrow ? (
    <AutoGrowTextarea {...inputProps} id={controlId} value={value} onChange={onChange} aria-label={ariaLabel ?? label} disabled={disabled} />
  ) : (
    <textarea
      {...inputProps} id={controlId} className="input" rows={rows} value={value} onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel ?? label} disabled={disabled}
    />
  );
  const hintNode = hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>;
  if (labelExtra) {
    return (
      <div className="stack" style={{ gap: "0.25rem" }}>
        <LabelRow htmlFor={controlId ?? id} label={label} extra={labelExtra} />
        {control}
        {hintNode}
      </div>
    );
  }
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      {control}
      {hintNode}
    </label>
  );
}

/** A labelled date input (`value` is YYYY-MM-DD, or "" for none); `ariaLabel` overrides the label as the accessible name. */
export function DateField({
  label, value, onChange, hint, ariaLabel, disabled, inputProps,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  inputProps?: Omit<InputExtras, "type">;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <input
        {...inputProps} className="input" type="date" value={value} onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel ?? label} disabled={disabled}
      />
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
  label, checked, onChange, hint, heading, ariaLabel, disabled, title,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  heading?: string;
  ariaLabel?: string;
  disabled?: boolean;
  /** Tooltip, e.g. why a forced-on box cannot be changed. */
  title?: string;
}) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      {heading && <span>{heading}</span>}
      <label className="row" style={{ gap: "0.4rem", minHeight: heading ? "2.25rem" : undefined }}>
        <input
          type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={ariaLabel}
          disabled={disabled} title={title}
        />
        {label}
      </label>
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </div>
  );
}

/** A labelled colour picker (`value` is a `#rrggbb` string). */
export function ColorField({
  label, value, onChange, hint, ariaLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  ariaLabel?: string;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <input
        type="color" value={value} onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel ?? label}
        style={{ width: 60, height: 36, padding: 2 }}
      />
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}

/**
 * A labelled on/off switch for a setting, with the label and an optional hint beside it. Use this
 * for a state that applies as it is saved with its form; use `CheckboxField` for a choice made while
 * filling the form in.
 */
export function ToggleField({
  label, checked, onChange, hint, disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="row" style={{ gap: "0.6rem" }}>
      <ToggleSwitch checked={checked} onChange={onChange} label={label} disabled={disabled} />
      <span className="stack" style={{ gap: 0 }}>
        {label}
        {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
      </span>
    </label>
  );
}

/**
 * A labelled file picker for a form field that is submitted with the form (a bundle to import): the
 * selection does not act on its own. A file whose selection acts immediately (an attachment, a logo)
 * uses `FileUploadTrigger` instead.
 */
export function FileField({
  label, onChange, accept, hint, ariaLabel,
}: {
  label: string;
  onChange: (file: File | null) => void;
  accept?: string;
  hint?: ReactNode;
  ariaLabel?: string;
}) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <input
        className="input" type="file" accept={accept} aria-label={ariaLabel ?? label}
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </label>
  );
}

/**
 * A labelled file upload whose selection acts at once (a logo, a background image): the label, an optional
 * `OverridePill` beside it, then the trigger button. A file that is submitted with a form uses `FileField`.
 *
 * @param id The input's id (the label points at it).
 * @param labelExtra A control beside the label (an `OverridePill`).
 * @param children The trigger button's content.
 */
export function UploadField({
  id, label, labelExtra, accept, disabled, onSelect, children,
}: {
  id: string;
  label: string;
  labelExtra?: ReactNode;
  accept?: string;
  disabled?: boolean;
  onSelect: (file: File) => void;
  children: ReactNode;
}) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <LabelRow htmlFor={id} label={label} extra={labelExtra} />
      <FileUploadTrigger id={id} accept={accept} disabled={disabled} onSelect={onSelect}>
        {children}
      </FileUploadTrigger>
    </div>
  );
}
