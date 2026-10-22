/**
 * Module: components/FormFields
 *
 * The labelled controls every create/edit form is built from (docs/ux-style-guide.md, "Pattern:
 * compact forms and add-on-demand"): a single-line input, a multi-line textarea, a date input and a
 * checkbox, each with a visible label that is also the accessible name (principle 13) and an optional
 * hint underneath (`InlineTextInput` is the caption-less form for an inline row). Lay them out in a `FormGrid`; pick from a list with `LabeledSelect` and people with
 * `PrincipalFormField`. Every field takes `help` (a `(?)` button revealing what the field means,
 * `FieldHelp`) or, for a self-explanatory field, `helpNotNeeded`.
 */
import { useId, useState } from "react";
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

import { useStrings } from "../context/TerminologyContext";
import { normaliseHexColour } from "../utils/color";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { FieldCaption, FieldHelp, FieldShell, RequiredMark } from "./FieldHelp";
import type { FieldHelpProps } from "./FieldHelp";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { ToggleSwitch } from "./ToggleSwitch";

/** Attributes a field passes straight to its control (type, min, max, maxLength, autoFocus, style…); the field owns the rest. */
type InputExtras = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "className" | "aria-label" | "placeholder" | "disabled">;
type TextAreaExtras = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "className" | "aria-label" | "rows" | "disabled">;

/** A labelled single-line input; `ariaLabel` overrides the label as the accessible name when they differ. */
export function TextField({
  label, value, onChange, ariaLabel, hint, placeholder, disabled, inputProps, labelExtra, help, required,
}: FieldHelpProps & {
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
  const controlId = inputProps?.id ?? id;
  return (
    <FieldShell label={label} controlId={controlId} help={help} extra={labelExtra} hint={hint} required={required}>
      <input
        {...inputProps} required={required ?? inputProps?.required} aria-required={required || undefined} id={controlId} className="input" value={value}
        onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel ?? label} placeholder={placeholder} disabled={disabled}
      />
    </FieldShell>
  );
}

/**
 * A single-line input with no visible caption, for an inline add or rename row where the row is the
 * caption (a stage's name beside its status badge). The accessible name is required, so it cannot be left
 * unnamed. A field in a form is a `TextField`.
 *
 * @param ariaLabel The input's accessible name.
 * @param type The HTML input type (`text`, `number`, `datetime-local`).
 * @param maxWidth Optional width cap in pixels.
 */
export function InlineTextInput({
  ariaLabel, value, onChange, type = "text", maxWidth, placeholder, disabled,
}: {
  ariaLabel: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number" | "datetime-local";
  maxWidth?: number;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <input
      className="input" type={type} style={maxWidth ? { maxWidth } : undefined} value={value} aria-label={ariaLabel}
      placeholder={placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value)}
    />
  );
}

/**
 * A labelled multi-line input; `ariaLabel` overrides the label as the accessible name when they differ.
 * `autoGrow` swaps the fixed `rows` for a box that grows with its content (see `AutoGrowTextarea`); `rows`
 * is then ignored.
 */
export function TextAreaField({
  label, value, onChange, rows = 2, hint, ariaLabel, disabled, inputProps, autoGrow, labelExtra, help, required,
}: FieldHelpProps & {
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
  const controlId = inputProps?.id ?? id;
  return (
    <FieldShell label={label} controlId={controlId} help={help} extra={labelExtra} hint={hint} required={required}>
      {autoGrow ? (
        <AutoGrowTextarea {...inputProps} required={required ?? inputProps?.required} aria-required={required || undefined} id={controlId} value={value} onChange={onChange} aria-label={ariaLabel ?? label} disabled={disabled} />
      ) : (
        <textarea
          {...inputProps} required={required ?? inputProps?.required} aria-required={required || undefined} id={controlId} className="input" rows={rows} value={value} onChange={(e) => onChange(e.target.value)}
          aria-label={ariaLabel ?? label} disabled={disabled}
        />
      )}
    </FieldShell>
  );
}

/** A labelled date input (`value` is YYYY-MM-DD, or "" for none); `ariaLabel` overrides the label as the accessible name. */
export function DateField({
  label, value, onChange, hint, ariaLabel, disabled, inputProps, help, required,
}: FieldHelpProps & {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  inputProps?: Omit<InputExtras, "type">;
}) {
  const id = useId();
  const controlId = inputProps?.id ?? id;
  return (
    <FieldShell label={label} controlId={controlId} help={help} hint={hint} required={required}>
      <input
        {...inputProps} required={required ?? inputProps?.required} aria-required={required || undefined} id={controlId} className="input" type="date" value={value} onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel ?? label} disabled={disabled}
      />
    </FieldShell>
  );
}

/**
 * A labelled checkbox with an optional hint underneath. With `heading` it is laid out like the other
 * fields (a heading line, then the control), so it lines up with an input beside it in a `FormGrid`;
 * `label` is then the checkbox's own text and `ariaLabel` its accessible name.
 */
export function CheckboxField({
  label, checked, onChange, hint, heading, ariaLabel, disabled, title, help, required,
}: FieldHelpProps & {
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
      {heading && <FieldCaption label={heading} help={help} required={required} />}
      <span className="row" style={{ gap: "0.4rem", alignItems: "flex-start", flexWrap: "nowrap", minHeight: heading ? "2.25rem" : undefined }}>
        <label className="checkbox-label">
          <input
            type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={ariaLabel} required={required}
            disabled={disabled} title={title}
          />
          {label}{!heading && required && <RequiredMark />}
        </label>
        {!heading && help && <FieldHelp label={label} help={help} />}
      </span>
      {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
    </div>
  );
}

/**
 * A labelled colour field: the browser's colour picker (the wheel) and a hex box kept in sync, with
 * an optional row of named preset swatches and an optional "no colour" choice. The hex box accepts
 * `#rgb` or `#rrggbb` (with or without the `#`) and reports lower-case `#rrggbb`; text that is not a
 * colour is flagged and never reported, so a caller only ever sees plain hex (or `""` for none).
 *
 * @param value A `#rrggbb` string, or `""` for no colour when `emptyLabel` is given.
 * @param presets Named swatches shown as a row of buttons (each reports its own hex).
 * @param emptyLabel Adds a "no colour" button with this text; choosing it reports `""`.
 */
export function ColorField({
  label, value, onChange, hint, ariaLabel, help, presets, emptyLabel, required,
}: FieldHelpProps & {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  ariaLabel?: string;
  presets?: ReadonlyArray<{ name: string; hex: string }>;
  emptyLabel?: string;
}) {
  const id = useId();
  const strings = useStrings();
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? value;
  const invalid = draft !== null && draft.trim() !== "" && normaliseHexColour(draft) === null;
  const name = ariaLabel ?? label;
  return (
    <FieldShell label={label} controlId={id} help={help} hint={hint} required={required}>
      <span className="row" style={{ gap: "0.4rem", alignItems: "center" }}>
        <input
          id={id} type="color" value={normaliseHexColour(value) ?? "#000000"} aria-label={name}
          onChange={(e) => { setDraft(null); onChange(e.target.value); }}
          style={{ width: 60, height: 36, padding: 2 }}
        />
        <input
          className="input" style={{ width: "7rem" }} value={shown} maxLength={7} spellCheck={false}
          aria-label={strings.common.hexCode(name)} aria-invalid={invalid || undefined} placeholder="#rrggbb"
          onChange={(e) => {
            setDraft(e.target.value);
            const hex = normaliseHexColour(e.target.value);
            if (hex) onChange(hex);
          }}
          onBlur={() => setDraft(null)}
        />
        {presets?.map((preset) => (
          <button
            key={preset.hex} type="button" className="colour-swatch" aria-label={preset.name} title={preset.name}
            aria-pressed={normaliseHexColour(value) === preset.hex}
            style={{ background: preset.hex }}
            onClick={() => { setDraft(null); onChange(preset.hex); }}
          />
        ))}
        {emptyLabel && (
          <button type="button" className="btn btn-sm" aria-pressed={value === ""} onClick={() => { setDraft(null); onChange(""); }}>
            {emptyLabel}
          </button>
        )}
      </span>
      {invalid && <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>{strings.common.hexCodeInvalid}</span>}
    </FieldShell>
  );
}

/**
 * A labelled on/off switch for a setting, with the label and an optional hint beside it. Use this
 * for a state that applies as it is saved with its form; use `CheckboxField` for a choice made while
 * filling the form in.
 */
export function ToggleField({
  label, checked, onChange, hint, disabled, help,
}: FieldHelpProps & {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <span className="row" style={{ gap: "0.6rem", alignItems: "center" }}>
      <label className="checkbox-label" style={{ gap: "0.6rem" }}>
        <ToggleSwitch checked={checked} onChange={onChange} label={label} disabled={disabled} />
        <span className="stack" style={{ gap: 0 }}>
          {label}
          {hint && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{hint}</span>}
        </span>
      </label>
      {help && <FieldHelp label={label} help={help} />}
    </span>
  );
}

/**
 * A labelled file picker for a form field that is submitted with the form (a bundle to import): the
 * selection does not act on its own. A file whose selection acts immediately (an attachment, a logo)
 * uses `FileUploadTrigger` instead.
 */
export function FileField({
  label, onChange, accept, hint, ariaLabel, help, required,
}: FieldHelpProps & {
  label: string;
  onChange: (file: File | null) => void;
  accept?: string;
  hint?: ReactNode;
  ariaLabel?: string;
}) {
  const id = useId();
  return (
    <FieldShell label={label} controlId={id} help={help} hint={hint} required={required}>
      <input
        id={id} className="input" type="file" required={required} aria-required={required || undefined} accept={accept} aria-label={ariaLabel ?? label}
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
    </FieldShell>
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
  id, label, labelExtra, accept, disabled, onSelect, children, help, required,
}: FieldHelpProps & {
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
      <FieldCaption htmlFor={id} label={label} extra={labelExtra} help={help} required={required} />
      <FileUploadTrigger id={id} accept={accept} disabled={disabled} onSelect={onSelect}>
        {children}
      </FileUploadTrigger>
    </div>
  );
}
