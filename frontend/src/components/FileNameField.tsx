/**
 * Module: components/FileNameField
 *
 * A "File name" field for a downloaded report: a layout's, a pack's, a pack entry's or the organisation's default.
 * It is a text template with `{{placeholders}}`, an Insert list of the placeholders valid in that place and a live
 * example of the name the template gives.
 *
 * Responsibilities:
 * - Edit the template (an emptied field is `""`; the caller removes the key).
 * - Ask the server what the template would name a file (`api/reportFileNames`) shortly after typing stops, and show
 *   the example, or the server's problems, beneath the field.
 * - Offer the placeholders the server says are valid here, appended to the end of the text.
 *
 * Design decisions: the example comes from the server so it can never disagree with a real download (same fill, same
 * cleaning); the call is injected (`fetchExample`) so stories stay off the network; a failed call shows a quiet
 * "could not be shown" line and never blocks editing, since the save-time check is the judge.
 */
import { useEffect, useState } from "react";

import { fetchFileNameExample, type FileNameExample, type FileNameExtension, type FileNameKind, type FileNameExampleRequest } from "../api/reportFileNames";
import { useStrings } from "../context/TerminologyContext";
import { LabeledSelect } from "./LabeledSelect";
import { TextField } from "./FormFields";

/** How long typing must pause before the example is asked for. */
const DEBOUNCE_MS = 300;

/**
 * @param label The field's caption.
 * @param value The template.
 * @param onChange Called with the new template (`""` when emptied).
 * @param kind Where the template is set; decides which placeholders are valid.
 * @param variables Names of the run-time variables the place declares.
 * @param extension The extension the example shows.
 * @param help The field's help text.
 * @param error A server message about this field (from a save), shown beneath it.
 * @param fetchExample Asks the server for the example (a story passes a fake).
 */
export function FileNameField({
  label, value, onChange, kind, variables = [], extension = "pdf", disabled, help, error, fetchExample = fetchFileNameExample,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  kind: FileNameKind;
  variables?: string[];
  extension?: FileNameExtension;
  disabled?: boolean;
  help: string;
  error?: string;
  fetchExample?: (request: FileNameExampleRequest) => Promise<FileNameExample>;
}) {
  const text = useStrings().reportFileName;
  const [shown, setShown] = useState<FileNameExample | null>(null);
  const [failed, setFailed] = useState(false);
  const variableKey = variables.join("\u0000");

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      fetchExample({ template: value, kind, variables: variableKey ? variableKey.split("\u0000") : [], extension })
        .then((answer) => {
          if (!current) return;
          if (answer && Array.isArray(answer.problems)) { setShown(answer); setFailed(false); } else setFailed(true);
        })
        .catch(() => { if (current) setFailed(true); });
    }, DEBOUNCE_MS);
    return () => { current = false; clearTimeout(timer); };
  }, [value, kind, variableKey, extension, fetchExample]);

  const problems = [...(error ? [error] : []), ...(value !== "" ? shown?.problems ?? [] : [])];
  const options = (shown?.placeholders ?? []).map((p) => ({ value: p, label: p }));
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <TextField
        label={label} value={value} onChange={onChange} disabled={disabled} help={help} hint={text.hint}
        inputProps={{ maxLength: 200, spellCheck: false }}
      />
      {!disabled && options.length > 0 && (
        <LabeledSelect
          helpNotNeeded label={text.insert} value="" placeholder={text.insertChoose} options={options}
          onChange={(placeholder) => { if (placeholder) onChange(`${value}${placeholder}`); }}
        />
      )}
      {problems.length > 0 ? (
        <div role="alert" style={{ color: "var(--color-danger)" }}>{problems.map((p) => <div key={p}>{p}</div>)}</div>
      ) : (
        <div className="text-muted" aria-live="polite">
          {failed ? text.unavailable : shown === null ? text.checking : shown.example ? text.example(shown.example) : text.exampleNone}
        </div>
      )}
    </div>
  );
}
