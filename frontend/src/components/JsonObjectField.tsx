/**
 * Module: components/JsonObjectField
 *
 * A labelled text area for a small JSON object (a report pack entry's fixed variable values or a module report's
 * options). It keeps the text as typed, hands the parent the parsed object only while the text is valid (empty means
 * "none"), and shows what is wrong inline, so a half-typed value never reaches the pack being edited.
 *
 * Responsibilities: parse on change, report validity (`onValidity`) so the host can hold Save back, and re-sync the
 * text when the host replaces the value from outside (a different entry in the same slot).
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { TextAreaField } from "./FormFields";

type JsonObject = Record<string, unknown>;

/** The parsed object, `undefined` for empty text, or `null` when the text is not a JSON object. */
function parse(text: string): JsonObject | undefined | null {
  if (text.trim() === "") return undefined;
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as JsonObject) : null;
  } catch {
    return null;
  }
}

/**
 * @param label The field's label.
 * @param value The current object, or `undefined` for none.
 * @param onChange Called with the new object (`undefined` when the text is emptied) whenever the text is valid.
 * @param onValidity Called with whether the text is currently acceptable.
 * @param help / hint The field's help text and visible hint.
 */
export function JsonObjectField({
  label, value, onChange, onValidity, help, hint,
}: {
  label: string;
  value: JsonObject | undefined;
  onChange: (value: JsonObject | undefined) => void;
  onValidity?: (valid: boolean) => void;
  help: string;
  hint?: string;
}) {
  const text = useStrings().reportPacks;
  const [draft, setDraft] = useState(value === undefined ? "" : JSON.stringify(value));
  // The host's value no longer means what the text says: it was replaced from outside, so show it.
  if (JSON.stringify(parse(draft)) !== JSON.stringify(value) && parse(draft) !== null) {
    setDraft(value === undefined ? "" : JSON.stringify(value));
  }

  const parsed = parse(draft);
  const problem = parsed === null ? (draft.trim().startsWith("{") ? text.jsonInvalid : text.jsonNotObject) : null;

  function change(next: string) {
    setDraft(next);
    const result = parse(next);
    onValidity?.(result !== null);
    if (result !== null) onChange(result);
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <TextAreaField
        label={label} value={draft} onChange={change} hint={hint} help={help}
        inputProps={{ spellCheck: false, style: { fontFamily: "var(--font-mono, monospace)" } }}
      />
      {problem && <span role="alert" style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{problem}</span>}
    </div>
  );
}
