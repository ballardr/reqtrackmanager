/**
 * Module: components/ReportLayoutFieldPicker
 *
 * The designer's field picker: lists what a `{{...}}` placeholder can name at the caret and inserts it.
 *
 * Responsibilities:
 * - Offer the fields of the record type behind the name in scope (`as req` in an enclosing For each), or the
 *   `value` / `count` of a group, as `{{name.field}}`; several names in scope are chosen from a select that
 *   defaults to the innermost.
 * - Always offer the global placeholders (`{{project_name}}`, `{{report_title}}` ...).
 * - Filter by label, show each field's kind.
 *
 * It only inserts text; the server's parser and validator remain the judge of what is valid, so a field not
 * offered here can still be typed by hand. Controlled: the caller computes `aliases` from the caret's line
 * (`utils/reportLayoutText.aliasesInScope`) and performs the insertion.
 */
import { useState } from "react";

import type { ReportFieldCatalogue, ReportFieldInfo } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { placeholder, type AliasInScope } from "../utils/reportLayoutText";
import { LabeledSelect } from "./LabeledSelect";
import { TextField } from "./FormFields";

/** What a group exposes, labelled; kinds come from the catalogue's `group_fields`. */
const GROUP_FIELD_LABEL: Record<string, string> = { value: "Value", count: "Count" };

/**
 * @param catalogue The record types and placeholders the scope can use.
 * @param aliases The names usable at the caret, outermost first.
 * @param onInsert Called with the text to put at the caret.
 */
export function ReportLayoutFieldPicker({
  catalogue, aliases, onInsert,
}: { catalogue: ReportFieldCatalogue; aliases: AliasInScope[]; onInsert: (text: string) => void }) {
  const text = useStrings().reportLayouts;
  const [chosen, setChosen] = useState<string>("");
  const [filter, setFilter] = useState("");

  const alias = aliases.find((a) => a.name === chosen) ?? aliases[aliases.length - 1] ?? null;
  const type = alias?.kind === "record" ? catalogue.types.find((t) => t.type === alias.recordType) ?? null : null;
  const fields: ReportFieldInfo[] = alias?.kind === "group"
    ? Object.entries(catalogue.group_fields).map(([key, kind]) => ({
      key, label: GROUP_FIELD_LABEL[key] ?? key, kind, reserved: true, choices: [],
    }))
    : type?.fields ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = fields.filter((f) => needle === "" || f.label.toLowerCase().includes(needle) || f.key.includes(needle));

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.fieldsHint}</p>

      <h3 style={{ margin: 0, fontSize: "1rem" }}>{text.fieldsGlobal}</h3>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {catalogue.placeholders.map((name) => (
          <button
            key={name} type="button" className="btn btn-sm" aria-label={text.fieldInsert(placeholder(null, name))}
            onClick={() => onInsert(placeholder(null, name))}
          >
            {placeholder(null, name)}
          </button>
        ))}
      </div>

      {alias === null ? (
        <p className="text-muted" style={{ margin: 0 }}>{text.fieldsAliasNone}</p>
      ) : (
        <>
          {aliases.length > 1 && (
            <LabeledSelect helpNotNeeded
              label={text.fieldsAlias}
              value={alias.name}
              onChange={setChosen}
              placeholder={null}
              options={aliases.map((a) => ({
                value: a.name,
                label: a.kind === "group" ? `${a.name} (${text.fieldsGroup})` : `${a.name} (${catalogue.types.find((t) => t.type === a.recordType)?.label ?? a.recordType ?? "?"})`,
              }))}
            />
          )}
          <h3 style={{ margin: 0, fontSize: "1rem" }}>
            {alias.kind === "group" ? text.fieldsGroup : type?.label ?? alias.recordType}
          </h3>
          <TextField helpNotNeeded label={text.fieldsFilter} value={filter} onChange={setFilter} />
          {shown.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>{text.fieldsNoMatch}</p>
          ) : (
            <ul className="layout-field-list" aria-label={text.fieldsTab}>
              {shown.map((field) => (
                <li key={field.key} className="row" style={{ justifyContent: "space-between" }}>
                  <button
                    type="button" className="btn btn-sm" aria-label={text.fieldInsert(field.label)}
                    onClick={() => onInsert(placeholder(alias.name, field.key))}
                  >
                    {field.label}
                  </button>
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>{field.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
