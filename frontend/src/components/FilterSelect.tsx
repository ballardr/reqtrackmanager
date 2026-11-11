/**
 * Module: components/FilterSelect
 *
 * The labelled single-choice select of a filter panel: a `FilterField` caption (with optional `(?)` help) around a
 * `select.input` whose first entry clears the filter ("All statuses"). Every filter panel uses this one component, so
 * the caption, the "All" entry, the accessible name and the chevron are the same on every list (docs/ux-style-guide.md,
 * "Pattern: filter panel"). Presentational only: the caller owns the value, and an empty string means "no filter".
 * A select in a form is a `LabeledSelect`; one in a row of controls with no caption is an `InlineSelect`.
 */
import type { SelectHTMLAttributes } from "react";

import { FilterField } from "./FilterPanel";

export interface FilterSelectOption<V extends string = string> {
  value: V;
  label: string;
}

type FilterSelectProps<V extends string> = {
  label: string;
  help?: string;
  options: FilterSelectOption<V>[];
  disabled?: boolean;
  ariaLabel?: string;
  inputProps?: Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "className" | "aria-label" | "disabled">;
} & (
  | { allLabel: string; value: V | ""; onChange: (value: V | "") => void }
  | { allLabel?: undefined; value: V; onChange: (value: V) => void }
);

/**
 * One labelled filter select.
 *
 * @param label The caption, also the select's accessible name unless `ariaLabel` is given.
 * @param help What each option means, as the caption's `(?)` tooltip, one line per option.
 * @param value The chosen value; with `allLabel`, `""` is the "All" entry.
 * @param onChange Called with the chosen value (`""` for the "All" entry when `allLabel` is given).
 * @param options The choices, in display order.
 * @param allLabel Text of the leading entry that clears the filter; omit for a select that always holds a value.
 * @param disabled Whether the select is unavailable (for example until a parent filter is chosen).
 * @param ariaLabel Overrides the caption as the accessible name when they differ.
 * @param inputProps Rare extra `select` attributes (`id`, `data-*`).
 */
export function FilterSelect<V extends string = string>({
  label,
  help,
  value,
  onChange,
  options,
  allLabel,
  disabled,
  ariaLabel,
  inputProps,
}: FilterSelectProps<V>) {
  return (
    <FilterField label={label} help={help}>
      <select
        {...inputProps}
        className="input"
        aria-label={ariaLabel ?? label}
        disabled={disabled}
        value={value}
        onChange={(e) => (onChange as (value: string) => void)(e.target.value)}
      >
        {allLabel !== undefined && <option value="">{allLabel}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FilterField>
  );
}
