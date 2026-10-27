/**
 * Module: components/ReportVariablesForm
 *
 * The run form of a custom report layout's variables: one labelled control per variable the layout declares,
 * built from what the server returns (`ReportVariable`: type, default and the current options), so a new layout
 * needs no UI code. Used by the Reports page (`ReportRunner`) and by the designer's preview.
 *
 * Responsibilities:
 * - Pick the control from the variable: a switch for yes/no, a checkbox list in a dropdown for a list of options,
 *   a select for one of several options, a date, a number, or text (a list typed as comma-separated text).
 * - Mark a variable the person must fill in (no default) with `*`, through the shared field components.
 * - Stay controlled and stateless but for the text being typed in a free list field, which is kept so a trailing
 *   comma is not swallowed before the next value is typed.
 *
 * Design decisions:
 * - A value the form cannot offer (the options changed since it was chosen) is still shown selected, so the
 *   person sees what will run; the server warns when it is no longer one of the options.
 * - Variables narrow what a report shows, they do not widen what the person may read; the form says nothing
 *   about access.
 *
 * Dependencies: the shared field components (`LabeledSelect`, `TextField`, `DateField`, `ToggleField`,
 * `MultiSelectDropdown`).
 */
import { useState } from "react";

import type { ReportVariable, VariableValue, VariableValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { DateField, TextField, ToggleField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { RequiredMark } from "./FieldHelp";

/**
 * @param variables The layout's variables with defaults and options.
 * @param values Current values by name (`null` or absent: not chosen).
 * @param onChange Called with a variable name and its new value (`null` clears it).
 */
export function ReportVariablesForm({
  variables, values, onChange,
}: {
  variables: ReportVariable[];
  values: VariableValues;
  onChange: (name: string, value: VariableValue | null) => void;
}) {
  const text = useStrings().reportVariables;
  if (variables.length === 0) return null;
  return (
    <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }} role="group" aria-label={text.groupLabel}>
      {variables.map((variable) => (
        <VariableControl key={variable.name} variable={variable} value={values[variable.name] ?? null} onChange={(v) => onChange(variable.name, v)} />
      ))}
    </div>
  );
}

function VariableControl({
  variable, value, onChange,
}: {
  variable: ReportVariable;
  value: VariableValue | null;
  onChange: (value: VariableValue | null) => void;
}) {
  const text = useStrings().reportVariables;
  const required = variable.default === null;
  const label = variable.label;
  if (variable.type === "bool") {
    return <ToggleField helpNotNeeded label={label} checked={value === true} onChange={onChange} />;
  }
  if (variable.options !== null && variable.multiple) {
    const chosen = new Set(Array.isArray(value) ? value.map(String) : []);
    // A chosen value that is no longer on offer stays listed (checked) so it can be unchecked.
    const offered = [...variable.options, ...[...chosen].filter((c) => !variable.options?.includes(c))];
    return (
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <span>{label}{required && <RequiredMark />}</span>
        <MultiSelectDropdown
          triggerLabel={label}
          emptyLabel={text.chooseSeveral}
          filterable={offered.length > 8}
          summaryLimit={2}
          options={offered.map((option) => ({
            value: option,
            label: option,
            checked: chosen.has(option),
            optionLabel: option,
            onToggle: () => {
              const next = new Set(chosen);
              if (next.has(option)) next.delete(option);
              else next.add(option);
              // Keep the options' own order so the request does not depend on click order.
              const ordered = offered.filter((o) => next.has(o));
              onChange(ordered.length === 0 ? null : ordered);
            },
          }))}
        />
      </div>
    );
  }
  if (variable.options !== null) {
    const current = value === null ? "" : String(value);
    const offered = current && !variable.options.includes(current) ? [...variable.options, current] : variable.options;
    return (
      <LabeledSelect
        helpNotNeeded
        label={label}
        required={required}
        value={current}
        onChange={(next) => onChange(next === "" ? null : next)}
        options={offered.map((o) => ({ value: o, label: o }))}
        placeholder={text.choose}
      />
    );
  }
  if (variable.type === "date") {
    return <DateField helpNotNeeded label={label} required={required} value={typeof value === "string" ? value : ""} onChange={(next) => onChange(next === "" ? null : next)} />;
  }
  if (variable.multiple) {
    return <ListTextField variable={variable} value={value} required={required} onChange={onChange} />;
  }
  if (variable.type === "number") {
    return (
      <TextField
        helpNotNeeded
        label={label}
        required={required}
        value={value === null ? "" : String(value)}
        inputProps={{ type: "number" }}
        onChange={(next) => onChange(next === "" ? null : Number(next))}
      />
    );
  }
  return <TextField helpNotNeeded label={label} required={required} value={value === null ? "" : String(value)} onChange={(next) => onChange(next === "" ? null : next)} />;
}

/** A list of free values typed as comma-separated text; the text is kept while typing so a trailing comma survives. */
function ListTextField({
  variable, value, required, onChange,
}: {
  variable: ReportVariable;
  value: VariableValue | null;
  required: boolean;
  onChange: (value: VariableValue | null) => void;
}) {
  const text = useStrings().reportVariables;
  const [typed, setTyped] = useState(() => (Array.isArray(value) ? value.join(", ") : ""));
  return (
    <TextField
      helpNotNeeded
      label={variable.label}
      required={required}
      hint={text.commaHint}
      value={typed}
      onChange={(next) => {
        setTyped(next);
        const parts = next.split(",").map((p) => p.trim()).filter(Boolean);
        onChange(parts.length === 0 ? null : variable.type === "number" ? parts.map(Number) : parts);
      }}
    />
  );
}
