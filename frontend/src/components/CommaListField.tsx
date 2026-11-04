/**
 * Module: components/CommaListField
 *
 * A single-line field for a short list of values typed separated by commas (link type names, the values of an
 * "is any of" test).
 *
 * Responsibilities: hand the parent the parsed list on every keystroke, and keep what is typed (a trailing comma,
 * a space) on screen. The box takes the parent's list only when it no longer means what the text says, so typing
 * "a, " is not swallowed and a list replaced from outside is shown.
 */
import { useState } from "react";

import { TextField } from "./FormFields";

/**
 * @param label The field's label.
 * @param value The current list.
 * @param onChange Called with the list the text now means.
 * @param parse Turns one trimmed, non-empty part into a value (default: the text itself).
 * @param hint A visible hint under the field.
 * @param disabled Read-only.
 *
 * The field is always `helpNotNeeded`: a caller explains it with `hint` (or the label does).
 */
export function CommaListField({
  label, value, onChange, parse = (part) => part, hint, disabled,
}: {
  label: string;
  value: unknown[];
  onChange: (next: unknown[]) => void;
  parse?: (part: string) => unknown;
  hint?: string;
  disabled?: boolean;
}) {
  const written = value.join(", ");
  const listOf = (text: string) => text.split(",").map((part) => part.trim()).filter(Boolean).map(parse);
  const [typed, setTyped] = useState(written);
  const same = JSON.stringify(listOf(typed)) === JSON.stringify(value);
  if (!same) setTyped(written);
  const shown = same ? typed : written;
  return (
    <TextField helpNotNeeded
      label={label} value={shown} disabled={disabled} hint={hint}
      onChange={(text) => { setTyped(text); onChange(listOf(text)); }}
    />
  );
}
