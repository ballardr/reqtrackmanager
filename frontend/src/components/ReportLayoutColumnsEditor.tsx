/**
 * Module: components/ReportLayoutColumnsEditor
 *
 * Edits the columns of a table or sheet block, and a sheet's joins.
 *
 * Responsibilities:
 * - Columns: an ordered list of `{field, label?, from?}`; the field is chosen from the fields of the block's
 *   record type, and in a sheet with joins a column also says which record it reads (`from`). An **images column**
 *   (`{images: {...}, label?, from?}`) shows the pictures attached to each row's record; its settings are the server's
 *   `image_column_fields`, drawn by the caller's `renderImageField` with the shared field forms.
 * - Joins: up to a few linked record types added to a sheet, each named and following a link from an earlier
 *   name in the sheet (the root records or an earlier join).
 *
 * Design decisions: the editor lists only fields the field catalogue offers for the type, so a column cannot name
 * a Restricted or consent-sensitive field; the server still validates every name.
 */
import type { ReactNode } from "react";

import type { BlockCatalogue, BlockField, ReportFieldCatalogue } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import type { NameInScope } from "../utils/reportLayoutTree";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ReportLayoutSourceEditor } from "./ReportLayoutSourceEditor";

interface Column {
  field?: string;
  label?: string;
  from?: string;
  /** Set for an image column (the pictures attached to each row's record): the rules and the size, never with a field. */
  images?: Record<string, unknown>;
}

/**
 * @param value The columns as stored.
 * @param onChange Called with the edited columns.
 * @param names The records a column can read: the block's own (and, for a sheet, its joins').
 * @param catalogue The record types and fields.
 * @param disabled Read-only.
 * @param imageFields The settings of an image column; with `renderImageField`, adds the Add images column button.
 * @param renderImageField Draws one setting of an image column: the field, the column's settings object, the record type the
 *   column reads, and the change callback (`undefined` removes the key).
 */
export function ReportLayoutColumnsEditor({
  value, onChange, names, catalogue, disabled, imageFields = [], renderImageField,
}: {
  value: Column[]; onChange: (next: Column[]) => void; names: NameInScope[]; catalogue: ReportFieldCatalogue; disabled?: boolean;
  imageFields?: BlockField[];
  renderImageField?: (field: BlockField, rules: Record<string, unknown>, recordType: string | null, change: (key: string, value: unknown) => void) => ReactNode;
}) {
  const text = useStrings().reportOutline;
  const several = names.length > 1;

  function patch(i: number, change: Partial<Column>) {
    const next = { ...value[i], ...change };
    for (const key of ["label", "from"] as const) if (next[key] === "") delete next[key];
    onChange(value.map((c, j) => (j === i ? next : c)));
  }

  /** Changes one setting of image column `i`; an emptied one is removed, so the column keeps only what was set. */
  function setRule(i: number, key: string, setting: unknown) {
    const rules = { ...(value[i].images ?? {}) };
    if (setting === undefined || (Array.isArray(setting) && setting.length === 0)) delete rules[key];
    else rules[key] = setting;
    onChange(value.map((c, j) => (j === i ? { ...c, images: rules } : c)));
  }

  function move(i: number, delta: -1 | 1) {
    const next = [...value];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    onChange(next);
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {value.map((column, i) => {
        const owner = (several ? names.find((n) => n.name === (column.from ?? names[0].name)) : names[0]) ?? names[0];
        const fields = catalogue.types.find((t) => t.type === owner?.recordType)?.fields ?? [];
        const actions = !disabled && (
          <span className="row" style={{ gap: "var(--space-1)" }}>
            <button type="button" className="btn btn-sm" disabled={i === 0} onClick={() => move(i, -1)}>{text.moveColumnUp(i + 1)}</button>
            <button type="button" className="btn btn-sm" disabled={i === value.length - 1} onClick={() => move(i, 1)}>{text.moveColumnDown(i + 1)}</button>
            <button type="button" className="btn btn-sm" onClick={() => onChange(value.filter((_, j) => j !== i))}>{text.removeColumn(i + 1)}</button>
          </span>
        );
        if (column.images !== undefined) {
          const rules = column.images;
          return (
            <fieldset key={i} className="card stack" style={{ gap: "var(--space-2)" }} aria-label={text.imagesColumn(i + 1)}>
              <legend><strong>{text.imagesColumn(i + 1)}</strong></legend>
              {several && (
                <LabeledSelect helpNotNeeded
                  label={text.columnFrom(i + 1)} value={column.from ?? names[0].name} placeholder={null} disabled={disabled}
                  options={names.map((n) => ({ value: n.name, label: n.name }))} onChange={(from) => patch(i, { from })}
                />
              )}
              <TextField helpNotNeeded
                label={text.columnLabel(i + 1)} value={column.label ?? ""} placeholder={text.imagesHeadingPlaceholder} disabled={disabled}
                onChange={(label) => patch(i, { label })}
              />
              {renderImageField && imageFields.map((f) => renderImageField(f, rules, owner?.recordType ?? null, (key, setting) => setRule(i, key, setting)))}
              {actions}
            </fieldset>
          );
        }
        return (
          <span key={i} className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}>
            {several && (
              <LabeledSelect helpNotNeeded
                label={text.columnFrom(i + 1)} value={column.from ?? names[0].name} placeholder={null} disabled={disabled}
                options={names.map((n) => ({ value: n.name, label: n.name }))} onChange={(from) => patch(i, { from, field: "" })}
              />
            )}
            <LabeledSelect helpNotNeeded
              label={text.columnField(i + 1)} value={column.field ?? ""} placeholder={text.choose} disabled={disabled} required
              options={fields.map((f) => ({ value: f.key, label: f.label }))} onChange={(field) => patch(i, { field })}
            />
            <TextField helpNotNeeded
              label={text.columnLabel(i + 1)} value={column.label ?? ""} placeholder={text.columnHeadingPlaceholder} disabled={disabled}
              onChange={(label) => patch(i, { label })}
            />
            {actions}
          </span>
        );
      })}
      {!disabled && (
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <button type="button" className="btn btn-sm" onClick={() => onChange([...value, { field: "" }])}>{text.addColumn}</button>
          {renderImageField && imageFields.length > 0 && (
            <button type="button" className="btn btn-sm" onClick={() => onChange([...value, { images: {} }])}>{text.addImagesColumn}</button>
          )}
        </div>
      )}
    </div>
  );
}

interface Join {
  as?: string;
  source?: Record<string, unknown>;
}

/** Most joins a sheet takes. */
const MAX_JOINS = 5;

/**
 * A sheet's joins.
 *
 * @param value The joins as stored.
 * @param onChange Called with the edited joins.
 * @param rootName The sheet's own name for its records (`as`, default `record`).
 * @param rootType The record type of the sheet's own records.
 * @param catalogue The record types and fields.
 * @param blocks The block catalogue.
 * @param variables Names of the layout's declared variables.
 * @param disabled Read-only.
 */
export function ReportLayoutJoinsEditor({
  value, onChange, rootName, rootType, catalogue, blocks, variables, disabled,
}: {
  value: Join[];
  onChange: (next: Join[]) => void;
  rootName: string;
  rootType: string | null;
  catalogue: ReportFieldCatalogue;
  blocks: BlockCatalogue;
  variables: string[];
  disabled?: boolean;
}) {
  const text = useStrings().reportOutline;
  /** The names visible to join `i`: the root and the joins before it. */
  const namesBefore = (i: number): NameInScope[] => [
    { name: rootName, kind: "record", recordType: rootType },
    ...value.slice(0, i).map((j) => ({
      name: j.as || "joined", kind: "record" as const,
      recordType: typeof j.source?.record_type === "string" ? j.source.record_type : null,
    })),
  ];

  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      {value.map((join, i) => (
        <div key={i} className="card stack" style={{ gap: "var(--space-2)" }} role="group" aria-label={text.joinAs(i + 1)}>
          <TextField helpNotNeeded
            label={text.joinAs(i + 1)} value={join.as ?? ""} placeholder="joined" disabled={disabled}
            onChange={(as) => onChange(value.map((j, k) => (k === i ? { ...j, as: as === "" ? undefined : as } : j)))}
          />
          <ReportLayoutSourceEditor
            joinMode value={join.source ?? {}} names={namesBefore(i)} catalogue={catalogue} blocks={blocks} variables={variables}
            disabled={disabled} onChange={(source) => onChange(value.map((j, k) => (k === i ? { ...j, source } : j)))}
          />
          {!disabled && (
            <div><button type="button" className="btn btn-sm" onClick={() => onChange(value.filter((_, k) => k !== i))}>{text.removeJoin(i + 1)}</button></div>
          )}
        </div>
      ))}
      {!disabled && value.length < MAX_JOINS && (
        <div>
          <button type="button" className="btn btn-sm" onClick={() => onChange([...value, { as: value.length === 0 ? "joined" : `joined${value.length + 1}`, source: { linked_from: rootName } }])}>
            {text.addJoin}
          </button>
        </div>
      )}
    </div>
  );
}
