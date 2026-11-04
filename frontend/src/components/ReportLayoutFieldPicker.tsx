/**
 * Module: components/ReportLayoutFieldPicker
 *
 * The designer's field picker: one searchable list of everything a `{{...}}` placeholder can name at the caret,
 * and a click inserts it.
 *
 * Responsibilities:
 * - Combine, in one list, the report and project placeholders (`{{project_name}}`, `{{project_description}}`,
 *   `{{report_title}}` ...) and the fields of every name in scope (`as req` in an enclosing For each, the `value` /
 *   `count` of a group), each row saying where it comes from.
 * - Search by label, key or source, and filter by source (all, report and project, or one name in scope).
 * - Show each field's kind.
 *
 * It only inserts text; the server's parser and validator remain the judge of what is valid, so a field not
 * offered here can still be typed by hand. Controlled: the caller computes `aliases` from the caret's line
 * (`utils/reportLayoutText.aliasesInScope`) and performs the insertion.
 */
import { useMemo, useState } from "react";

import type { ReportFieldCatalogue } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { placeholder, type AliasInScope } from "../utils/reportLayoutText";
import { nameText } from "../utils/reportLayoutTree";
import { TextField } from "./FormFields";

/** The source filter's value for the report and project placeholders. */
const SOURCE_GLOBAL = "\u0000global";
const SOURCE_ALL = "";

/** One placeholder the list offers. */
interface Entry {
  /** The text inserted, `{{req.title}}`. */
  text: string;
  label: string;
  kind: string | null;
  math: boolean;
  /** Which source filter value shows it. */
  source: string;
  /** Where it comes from, in words. */
  from: string;
  /** What it prints, for the entries whose label does not say (a group's value and count). */
  note?: string;
}

/** A readable label for a global placeholder name (`project_description` becomes "Project description"). */
function globalLabel(name: string): string {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * @param catalogue The record types and placeholders the scope can use.
 * @param aliases The names usable at the caret, outermost first.
 * @param onInsert Called with the text to put at the caret.
 */
export function ReportLayoutFieldPicker({
  catalogue, aliases, onInsert,
}: { catalogue: ReportFieldCatalogue; aliases: AliasInScope[]; onInsert: (text: string) => void }) {
  const text = useStrings().reportLayouts;
  const [filter, setFilter] = useState("");
  const [source, setSource] = useState(SOURCE_ALL);

  const entries = useMemo<Entry[]>(() => {
    const out: Entry[] = catalogue.placeholders.map((name) => ({
      text: placeholder(null, name), label: globalLabel(name), kind: null, math: false, source: SOURCE_GLOBAL, from: text.fieldsFromGlobal,
    }));
    // Innermost name first: it is the one most likely wanted at the caret.
    for (const alias of [...aliases].reverse()) {
      const type = catalogue.types.find((t) => t.type === alias.recordType);
      if (alias.kind === "group") {
        // A group's value is the field it groups by, so the entry says which field (the group's own name is only an alias).
        const byLabel = alias.by ? type?.fields.find((f) => f.key === alias.by)?.label ?? alias.by : undefined;
        for (const [key, kind] of Object.entries(catalogue.group_fields)) {
          out.push({
            text: placeholder(alias.name, key), label: key === "count" ? text.fieldsGroupCount : text.fieldsGroupValue(byLabel), kind, math: false,
            source: alias.name, from: `${nameText(alias)} (${text.fieldsGroup})`,
            note: key === "count" ? text.fieldsGroupCountNote : text.fieldsGroupValueNote,
          });
        }
        continue;
      }
      for (const field of type?.fields ?? []) {
        out.push({
          text: placeholder(alias.name, field.key), label: field.label, kind: field.kind, math: field.math === true, source: alias.name,
          from: `${nameText(alias)} (${type?.label ?? alias.recordType ?? "?"})`,
        });
      }
    }
    return out;
  }, [catalogue, aliases, text]);

  const needle = filter.trim().toLowerCase();
  const sourceValue = source === SOURCE_ALL || source === SOURCE_GLOBAL || aliases.some((a) => a.name === source) ? source : SOURCE_ALL;
  const shown = entries.filter(
    (e) => (sourceValue === SOURCE_ALL || e.source === sourceValue)
      && (needle === "" || e.label.toLowerCase().includes(needle) || e.text.toLowerCase().includes(needle) || e.from.toLowerCase().includes(needle)),
  );

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.fieldsHint}</p>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <TextField helpNotNeeded label={text.fieldsFilter} value={filter} onChange={setFilter} />
        </div>
        <label className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{text.fieldsSource}</span>
          <select className="input" value={sourceValue} onChange={(e) => setSource(e.target.value)}>
            <option value={SOURCE_ALL}>{text.fieldsSourceAll}</option>
            <option value={SOURCE_GLOBAL}>{text.fieldsFromGlobal}</option>
            {aliases.map((a) => <option key={a.name} value={a.name}>{nameText(a)}</option>)}
          </select>
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>{text.fieldsNoMatch}</p>
      ) : (
        <ul className="layout-field-list" aria-label={text.fieldsTab}>
          {shown.map((entry) => (
            <li key={`${entry.source}:${entry.text}`} className="row" style={{ justifyContent: "space-between" }}>
              <span className="stack" style={{ gap: 0 }}>
                <button type="button" className="btn btn-sm" aria-label={text.fieldInsert(entry.text)} onClick={() => onInsert(entry.text)}>
                  {entry.label}
                </button>
                <span className="text-muted" style={{ fontSize: "0.8rem" }}>{entry.note ? `${entry.from}. ${entry.note}` : entry.from}</span>
              </span>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                {entry.kind === null ? entry.text : entry.math ? `${entry.kind}, ${text.fieldsMath}` : entry.kind}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
