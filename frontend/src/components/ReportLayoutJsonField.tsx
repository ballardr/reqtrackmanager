/**
 * Module: components/ReportLayoutJsonField
 *
 * A text area for one value of a layout block that the outline has no purpose-built control for (a block
 * type or field kind it does not know). The text is kept as typed; the parent gets the parsed value only while
 * the text is valid JSON, and the server's own check shows what else is wrong.
 *
 * Responsibilities: parse on change, keep half-typed text, re-read the value when it is replaced from outside.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { stableJson } from "../utils/reportLayoutTree";
import { TextAreaField } from "./FormFields";

/** Whether the text parses to the same JSON as `value`. */
function sameValue(text: string, value: unknown): boolean {
  try {
    return stableJson(JSON.parse(text)) === stableJson(value);
  } catch {
    return false;
  }
}

/**
 * @param label The field's label.
 * @param value The current value (`undefined` for none).
 * @param onChange Called with the parsed value (`undefined` when the text is emptied) whenever the text is valid JSON.
 * @param help The field's help text, if any.
 * @param disabled Read-only.
 * @param required Marks the field as one the layout needs.
 */
export function ReportLayoutJsonField({
  label, value, onChange, help, disabled, required,
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  help?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  const text = useStrings().reportOutline;
  const written = value === undefined ? "" : JSON.stringify(value, null, 2);
  const [typed, setTyped] = useState(written);
  const [broken, setBroken] = useState(false);
  const [lastWritten, setLastWritten] = useState(written);
  // A value replaced from outside (another view, a restored version) is shown; the author's own typing, which
  // comes back as the same value, is left exactly as typed.
  if (written !== lastWritten) {
    setLastWritten(written);
    if (!sameValue(typed, value)) {
      setTyped(written);
      setBroken(false);
    }
  }

  function edit(next: string) {
    setTyped(next);
    if (next.trim() === "") {
      setBroken(false);
      onChange(undefined);
      return;
    }
    try {
      onChange(JSON.parse(next));
      setBroken(false);
    } catch {
      setBroken(true);
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <TextAreaField
        label={text.jsonFieldLabel(label)} value={typed} onChange={edit} rows={4} disabled={disabled} help={help} required={required}
        inputProps={{ spellCheck: false }}
      />
      {broken && <span role="alert" style={{ color: "var(--color-danger)" }}>{text.jsonInvalid}</span>}
    </div>
  );
}
