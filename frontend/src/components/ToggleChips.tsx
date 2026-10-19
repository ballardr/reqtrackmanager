/**
 * Module: components/ToggleChips
 *
 * A row of on/off chips that narrow one list to a few kinds of record ("Personas", "Stakeholders", ...).
 * Each chip is a `FilterBadge` (so it looks like the other filter shortcuts) exposed as a toggle button
 * (`aria-pressed`). Use it for a small, fixed set of kinds that sit above a list; a field with many values
 * or a free-text one belongs in the `FilterPanel`.
 */
import { FilterBadge } from "./FilterBadge";

export interface ToggleChipOption<K extends string> {
  key: K;
  label: string;
  /** Shown after the label, muted, when given (how many records of this kind there are). */
  count?: number;
}

/**
 * @param ariaLabel Names the group (e.g. "Kinds of record").
 * @param options The chips, in display order.
 * @param selected The keys currently on.
 * @param onToggle Called with the key of the chip that was clicked.
 */
export function ToggleChips<K extends string>({
  ariaLabel,
  options,
  selected,
  onToggle,
}: {
  ariaLabel: string;
  options: ToggleChipOption<K>[];
  selected: K[];
  onToggle: (key: K) => void;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className="row" style={{ gap: "0.4rem" }}>
      {options.map((option) => {
        const on = selected.includes(option.key);
        return (
          <FilterBadge key={option.key} active={on} pressed={on} onClick={() => onToggle(option.key)}>
            {option.label}
            {option.count !== undefined && (
              <>
                {" "}
                <span className="text-muted">{option.count}</span>
              </>
            )}
          </FilterBadge>
        );
      })}
    </div>
  );
}
