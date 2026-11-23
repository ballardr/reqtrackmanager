/**
 * Module: components/ChoiceButtons
 *
 * An exclusive choice of a few short values drawn as a row of buttons: a radio group with one tab stop, arrow keys
 * moving the choice, and the chosen button marked by `aria-checked` and an accent edge (never colour alone). A
 * caption with optional field help sits above; each option is a `role="radio"` button; the group wraps.
 *
 * It stores nothing: `onChange` gets the clicked value. A value matching no option leaves every button unchecked
 * and the first reachable, so a stored value the buttons do not know is unchanged until a button is pressed.
 */
import { useRef } from "react";

import { FieldCaption, type FieldHelpProps } from "./FieldHelp";

/**
 * @param label The group's caption and accessible name.
 * @param value The chosen option's value (`""` or an unknown value: none checked).
 * @param options The values and what each button says, in order.
 * @param onChange Called with the pressed option's value.
 * @param disabled Disables every button.
 */
export function ChoiceButtons<V extends string | number>({
  label, value, options, onChange, disabled, help, required,
}: FieldHelpProps & {
  label: string;
  value: V | "" | undefined;
  options: { value: V; label: string }[];
  onChange: (value: V) => void;
  disabled?: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const checked = options.findIndex((o) => o.value === value);
  const tabStop = checked >= 0 ? checked : 0;
  const move = (from: number, step: number) => {
    const next = (from + step + options.length) % options.length;
    refs.current[next]?.focus();
    onChange(options[next].value);
  };
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption label={label} help={help} required={required} />
      <div role="radiogroup" aria-label={label} className="choice-buttons">
        {options.map((option, index) => (
          <button
            key={String(option.value)} ref={(el) => { refs.current[index] = el; }} type="button" role="radio"
            className={`btn btn-sm${index === checked ? " btn-marked" : ""}`} aria-checked={index === checked} disabled={disabled}
            tabIndex={index === tabStop ? 0 : -1} onClick={() => onChange(option.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); move(index, 1); }
              else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); move(index, -1); }
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
