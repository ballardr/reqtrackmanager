/**
 * Module: components/TextListField
 *
 * A list of short texts edited as one entry per line (file-name patterns, file types).
 *
 * Responsibilities:
 * - Show a list as lines in a growing text area and report the list back as the person types: blank lines and
 *   surrounding spaces are dropped from the reported list.
 * - Keep what is typed (including a blank line the person has just started) until the list is changed from outside.
 *
 * Design decisions: it wraps `TextAreaField`, so help, required marking and growth are the shared ones. The draft is
 * local because splitting on every keystroke would remove the newline just typed.
 */
import { useState } from "react";

import { TextAreaField } from "./FormFields";
import type { FieldHelpProps } from "./FieldHelp";

/** The entries of `text`: one per line, trimmed, blanks removed. */
function linesToList(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter((line) => line !== "");
}

/**
 * @param label The field's caption.
 * @param value The current list.
 * @param onChange Called with the new list (empty when nothing is left).
 * @param hint Text under the box, for example "One per line".
 * @param disabled Read-only.
 */
export function TextListField({
  label, value, onChange, hint, disabled, help, required,
}: Pick<FieldHelpProps, "help" | "required"> & {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  hint?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value.join("\n"));
  const [seen, setSeen] = useState(value);
  // A list changed from outside (undo, another view) replaces the draft; our own edits keep it.
  if (JSON.stringify(seen) !== JSON.stringify(value)) {
    setSeen(value);
    if (JSON.stringify(linesToList(draft)) !== JSON.stringify(value)) setDraft(value.join("\n"));
  }
  return (
    <TextAreaField
      label={label} value={draft} disabled={disabled} hint={hint} help={help} required={required} rows={2}
      inputProps={{ spellCheck: false }}
      onChange={(text) => {
        setDraft(text);
        const next = linesToList(text);
        setSeen(next);
        onChange(next);
      }}
    />
  );
}
