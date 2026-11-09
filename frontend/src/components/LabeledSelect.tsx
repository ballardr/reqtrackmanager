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
 * for the odd `select` attribute, and `autoWidth` for a select with a few short options that need not fill the row). Callers own any cascading-reset behaviour (e.g. clearing a child
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
  autoWidth,
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
  /** Sizes the select to its longest option instead of filling the row. */
  autoWidth?: boolean;
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
        style={autoWidth ? { width: "auto", alignSelf: "flex-start" } : undefined}
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

export interface InlineSelectOption<V extends string = string> {
  value: V;
  label: string;
  /** Shown but not choosable (a candidate that is unavailable, with the reason in its label). */
  disabled?: boolean;
  /** Options with the same consecutive `group` render under one `<optgroup>` of that name. */
  group?: string;
}

/**
 * A select with no visible caption, for a control that sits in a row of other controls (an "add to this
 * group" picker beside its button, a column mapping inside a table cell) where the row or the cell heading
 * is the caption. The accessible name is required, so it cannot be left unnamed. A field in a form is a
 * `LabeledSelect`; a narrowing filter is a `FilterSelect`.
 *
 * @param ariaLabel The select's accessible name.
 * @param value The chosen value; `""` shows the placeholder entry.
 * @param onChange Called with the chosen value.
 * @param options The choices; typed to the enum when the options are.
 * @param disabled Whether the select is unavailable.
 * @param placeholder Leading empty option's text; `null` omits it.
 * @param maxWidth Optional width cap in pixels.
 * @param autoWidth Sizes the select to its content instead of filling the row.
 * @param className Extra classes after `input`, for a select a stylesheet positions (a grid cell, a toolbar).
 * @param inputProps Rare extra `select` attributes (`id`, `aria-describedby`, `data-*`).
 */
export function InlineSelect<V extends string = string>({
  ariaLabel,
  value,
  onChange,
  options,
  disabled,
  placeholder = "Select…",
  maxWidth,
  autoWidth,
  className,
  inputProps,
}: {
  ariaLabel: string;
  value: V | "";
  onChange: (value: V) => void;
  options: InlineSelectOption<V>[];
  disabled?: boolean;
  placeholder?: string | null;
  maxWidth?: number;
  autoWidth?: boolean;
  className?: string;
  inputProps?: Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "className" | "aria-label" | "disabled">;
}) {
  const rendered: ReactNode[] = [];
  let groupOptions: ReactNode[] = [];
  let currentGroup: string | undefined;
  const flush = () => {
    if (currentGroup !== undefined) {
      rendered.push(
        <optgroup key={`group:${currentGroup}`} label={currentGroup}>
          {groupOptions}
        </optgroup>,
      );
    }
    groupOptions = [];
  };
  for (const o of options) {
    if (o.group !== currentGroup) {
      flush();
      currentGroup = o.group;
    }
    const node = (
      <option key={o.value} value={o.value} disabled={o.disabled}>
        {o.label}
      </option>
    );
    if (currentGroup === undefined) rendered.push(node);
    else groupOptions.push(node);
  }
  flush();
  return (
    <select
      {...inputProps}
      className={className ? `input ${className}` : "input"}
      style={maxWidth || autoWidth ? { maxWidth, width: autoWidth ? "auto" : undefined } : undefined}
      aria-label={ariaLabel}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value as V)}
    >
      {placeholder !== null && <option value="">{placeholder}</option>}
      {rendered}
    </select>
  );
}
