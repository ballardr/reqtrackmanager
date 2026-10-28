/**
 * Module: components/ReportPackVariablesEditor
 *
 * The "Variables" tab of the pack editor: the choices a person makes once when downloading the pack (for example
 * the categories to include). A layout in the pack receives the pack variable of the same name, type and list-ness.
 *
 * Responsibilities:
 * - Edit the declarations (name, label, type, whether it takes several values, default, options) and, optionally,
 *   the record field its options come from (a record type and a field of a compatible kind).
 * - Keep each variable's client-only `uid` so a reorder or removal keeps the right text in the right box.
 *
 * Design decisions: a default is typed as text and turned into the variable's type here (a number, a list split on
 * commas), because the server checks it against the declaration anyway; a default that does not fit is reported by the
 * server's positioned problems rather than guessed at. The compatible field kinds mirror the server's rule so the
 * picker never offers a field the pack would be refused for.
 */
import { useState, type ReactNode } from "react";

import type { ReportFieldCatalogue } from "../api/reportLayouts";
import type { PackVariableDeclaration } from "../api/reportPacks";
import { useStrings } from "../context/TerminologyContext";
import { newUid } from "../utils/reportPackDraft";
import { TextField, ToggleField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";

/** A variable in the editor's draft, with a client-only id that is dropped when the pack is saved. */
export interface DraftVariable {
  uid: string;
  variable: PackVariableDeclaration;
}

type VariableType = PackVariableDeclaration["type"];

/** The kinds of record field whose values a variable of each type can offer as options (the server's rule). */
const SOURCE_KINDS: Record<VariableType, string[]> = {
  text: ["text", "principal", "enum"],
  enum: ["enum", "text"],
  number: ["number"],
  date: ["date"],
  bool: ["bool"],
};

const TYPES: VariableType[] = ["text", "number", "date", "bool", "enum"];

/**
 * A text box that keeps what is typed (a trailing comma, a space) while the host holds the parsed value: the box
 * re-reads the host's value only when it no longer means what the text says, so typing "a, " is not swallowed.
 *
 * @param value The host's value as text.
 * @param canon What the host's value would be for a given text (so the box can tell an outside change from its own).
 * @param onText Called with the text as typed.
 */
function BufferedTextField({
  label, value, canon, onText, disabled, hint, help,
}: {
  label: string;
  value: string;
  canon: (raw: string) => string;
  onText: (raw: string) => void;
  disabled?: boolean;
  hint?: string;
  help?: string;
}) {
  const [raw, setRaw] = useState(value);
  // The host's value no longer means what the text says: it was changed from outside, so show it.
  if (value !== canon(raw)) setRaw(value);
  const shared = { label, value: raw, disabled, hint, onChange: (next: string) => { setRaw(next); onText(next); } };
  return help ? <TextField {...shared} help={help} /> : <TextField {...shared} helpNotNeeded />;
}

/** A comma-separated list as text, trimmed and without empty entries. */
function listText(raw: string): string {
  return raw.split(",").map((o) => o.trim()).filter((o) => o !== "").join(", ");
}

/** A default as the text box shows it (a list joined with commas). */
function defaultText(variable: PackVariableDeclaration): string {
  const value = variable.default;
  if (value === undefined) return "";
  return Array.isArray(value) ? value.join(", ") : String(value);
}

/** The text typed as a default, as the variable's type wants it; empty text means no default. */
function parseDefault(variable: PackVariableDeclaration, raw: string): PackVariableDeclaration["default"] {
  if (raw.trim() === "") return undefined;
  const items = (variable.multiple ? raw.split(",") : [raw]).map((v) => v.trim()).filter((v) => v !== "");
  const typed = variable.type === "number" ? items.map((v) => (Number.isNaN(Number(v)) ? v : Number(v))) : items;
  return (variable.multiple ? typed : typed[0]) as PackVariableDeclaration["default"];
}

/**
 * @param variables The draft variables, in order.
 * @param onChange Called with the new list after any edit.
 * @param catalogue The record types and fields options can come from, or `null` while unavailable.
 * @param disabled Read-only (a pack shared from elsewhere).
 * @param intro / emptyText Optional wording that replaces the pack's own.
 */
export function ReportPackVariablesEditor({
  variables, onChange, catalogue, disabled = false, intro, emptyText,
}: {
  variables: DraftVariable[];
  onChange: (next: DraftVariable[]) => void;
  catalogue: ReportFieldCatalogue | null;
  disabled?: boolean;
  /** Replaces the pack wording above the list (the layout outline uses the same editor for a layout's variables). */
  intro?: string;
  /** Replaces the pack wording shown when there are no variables. */
  emptyText?: string;
}) {
  const strings = useStrings();
  const text = strings.reportPacks;

  function patch(uid: string, change: Partial<PackVariableDeclaration>) {
    onChange(variables.map((d) => {
      if (d.uid !== uid) return d;
      const next = { ...d.variable, ...change };
      // Keys that no longer apply are dropped so the saved declaration is valid.
      if (next.type !== "enum") delete next.options;
      if (next.type === "bool") delete next.multiple;
      return { ...d, variable: next };
    }));
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{intro ?? text.variablesIntro}</p>
      {variables.length === 0 && <p className="text-muted">{emptyText ?? text.noVariables}</p>}
      {variables.map((draft, index) => {
        const v = draft.variable;
        const recordType = catalogue?.types.find((t) => t.type === v.source?.record_type);
        const fields = recordType?.fields.filter((f) => SOURCE_KINDS[v.type].includes(f.kind)) ?? [];
        let sourceControls: ReactNode = null;
        if (catalogue) {
          sourceControls = (
            <>
              <LabeledSelect help={strings.help.reportPackVariableSource}
                label={text.variableSourceType}
                value={v.source?.record_type ?? ""}
                disabled={disabled || v.options !== undefined}
                placeholder={text.variableSourceNone}
                onChange={(record_type) => {
                  if (record_type === "") {
                    const next = { ...v };
                    delete next.source;
                    onChange(variables.map((d) => (d.uid === draft.uid ? { ...d, variable: next } : d)));
                  } else {
                    patch(draft.uid, { source: { record_type, field: "" } });
                  }
                }}
                options={catalogue.types.map((t) => ({ value: t.type, label: t.label }))}
              />
              {v.source && (
                <LabeledSelect helpNotNeeded
                  label={text.variableSourceField}
                  value={v.source.field}
                  disabled={disabled}
                  onChange={(field) => patch(draft.uid, { source: { record_type: v.source?.record_type ?? "", field } })}
                  options={fields.map((f) => ({ value: f.key, label: f.label }))}
                />
              )}
            </>
          );
        }
        return (
          <section key={draft.uid} className="card stack" aria-label={text.variableLabel(index + 1)}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>{text.variableLabel(index + 1)}</strong>
              {!disabled && (
                <button type="button" className="btn btn-danger" onClick={() => onChange(variables.filter((d) => d.uid !== draft.uid))}>
                  {text.removeVariable}
                </button>
              )}
            </div>
            <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }}>
              <TextField helpNotNeeded required
                label={text.variableName} value={v.name} disabled={disabled} onChange={(name) => patch(draft.uid, { name })}
                inputProps={{ maxLength: 32 }}
              />
              <TextField helpNotNeeded
                label={text.variableDisplayLabel} value={v.label ?? ""} disabled={disabled}
                onChange={(label) => patch(draft.uid, { label: label === "" ? undefined : label })}
              />
              <LabeledSelect helpNotNeeded required
                label={text.variableType} value={v.type} disabled={disabled} placeholder={null}
                onChange={(type) => patch(draft.uid, { type: type as VariableType })}
                options={TYPES.map((t) => ({ value: t, label: text.typeLabels[t] }))}
              />
              {v.type !== "bool" && (
                <ToggleField helpNotNeeded
                  label={text.variableMultiple} checked={v.multiple === true} disabled={disabled}
                  onChange={(multiple) => patch(draft.uid, { multiple: multiple || undefined })}
                />
              )}
            </div>
            <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }}>
              <BufferedTextField help={strings.help.reportPackVariableDefault}
                label={text.variableDefault} value={defaultText(v)} disabled={disabled}
                canon={(raw) => defaultText({ ...v, default: parseDefault(v, raw) })}
                onText={(raw) => patch(draft.uid, { default: parseDefault(v, raw) })}
              />
              {v.type === "enum" && !v.source && (
                <BufferedTextField
                  label={text.variableOptions} hint={text.variableOptionsHint} value={(v.options ?? []).join(", ")} disabled={disabled}
                  canon={listText}
                  onText={(raw) => {
                    const options = listText(raw).split(", ").filter((o) => o !== "");
                    patch(draft.uid, { options: options.length > 0 ? options : undefined });
                  }}
                />
              )}
              {v.options === undefined && sourceControls}
            </div>
          </section>
        );
      })}
      {!disabled && (
        <div className="row">
          <button
            type="button" className="btn"
            onClick={() => onChange([...variables, { uid: newUid(), variable: { name: "", type: "text" } }])}
          >
            {text.addVariable}
          </button>
        </div>
      )}
    </div>
  );
}
