/**
 * Module: components/ReportLayoutColumnsEditor
 *
 * Edits the columns of a table or sheet block, and a sheet's joins.
 *
 * Responsibilities:
 * - Columns: an ordered list of `{field, label?, from?, width?}` shown as a short list (`ItemRowList`): one row per
 *   column with its name, move, remove and a gear whose popover holds the rest (field, heading, width, link, images
 *   settings; a new column's opens at once). The field is chosen from the fields of the block's record type, and in a sheet with joins a column also says which record it reads (`from`). An **images column**
 *   (`{images: {...}, label?, from?}`) shows the pictures attached to each row's record; its settings are the server's
 *   `image_column_fields`, drawn by the caller's `renderImageField` with the shared field forms.
 * - Links (sheets only): a column can open the row of its record on another sheet of the layout that lists the same
 *   record type (`link: {sheet}`); the choice offers only those sheets.
 * - Joins: up to a few linked record types added to a sheet, each named and following a link from an earlier
 *   name in the sheet (the root records or an earlier join).
 *
 * Design decisions: the editor lists only fields the field catalogue offers for the type, so a column cannot name
 * a Restricted or consent-sensitive field; the server still validates every name.
 */
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { BlockCatalogue, BlockField, ReportFieldCatalogue } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { nameOption, type NameInScope } from "../utils/reportLayoutTree";
import { TextField } from "./FormFields";
import { ItemRowList } from "./ItemRowList";
import { LabeledSelect } from "./LabeledSelect";
import { ReportLayoutSourceEditor } from "./ReportLayoutSourceEditor";
import { SettingsPopoverButton } from "./SettingsPopoverButton";

interface Column {
  field?: string;
  label?: string;
  from?: string;
  /** A forced width: a share of the table (`30%`) or a length (`4 cm`, `40 mm`); absent means automatic. */
  width?: string;
  /** Opens the row of the cell's record on the named sheet (a sheet column only). */
  link?: { sheet: string };
  /** Set for an image column (the pictures attached to each row's record): the rules and the size, never with a field. */
  images?: Record<string, unknown>;
}

/**
 * @param value The columns as stored.
 * @param onChange Called with the edited columns.
 * @param names The records a column can read: the block's own (and, for a sheet, its joins').
 * @param catalogue The record types and fields.
 * @param disabled Read-only.
 * @param sheets The layout's sheets and the record type each lists; when given, a column offers **Link to sheet** among the
 *   sheets that list its record's type.
 * @param imageFields The settings of an image column; with `renderImageField`, adds the Add images column button.
 * @param renderImageField Draws one setting of an image column: the field, the column's settings object, the record type the
 *   column reads, and the change callback (`undefined` removes the key).
 */
export function ReportLayoutColumnsEditor({
  value, onChange, names, catalogue, disabled, sheets, imageFields = [], renderImageField,
}: {
  value: Column[]; onChange: (next: Column[]) => void; names: NameInScope[]; catalogue: ReportFieldCatalogue; disabled?: boolean;
  sheets?: { name: string; recordType: string | null }[];
  imageFields?: BlockField[];
  renderImageField?: (field: BlockField, rules: Record<string, unknown>, recordType: string | null, change: (key: string, value: unknown) => void) => ReactNode;
}) {
  const strings = useStrings();
  const text = strings.reportOutline;
  const several = names.length > 1;
  /** The index of the column just added, whose settings open at once so its field can be chosen. */
  const [fresh, setFresh] = useState<number | null>(null);

  /** The sheets a column reading `recordType` can open: those that list it, and the one already chosen (so it still shows). */
  function linkTargets(recordType: string | null | undefined, chosen: string | undefined): string[] {
    if (!sheets) return [];
    const found = sheets.filter((s) => s.recordType !== null && s.recordType === recordType).map((s) => s.name);
    return chosen && !found.includes(chosen) ? [...found, chosen] : found;
  }

  function patch(i: number, change: Partial<Column>) {
    const next = { ...value[i], ...change };
    for (const key of ["label", "from", "width"] as const) if (next[key] === "") delete next[key];
    if (next.link?.sheet === "") delete next.link;
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

  /** The column's name in the list: its heading, else its field's label (an images column: "Images"). */
  function nameOf(column: Column, fields: { key: string; label: string }[]): string {
    if (column.label) return column.label;
    if (column.images !== undefined) return text.imagesHeadingPlaceholder;
    return fields.find((f) => f.key === column.field)?.label ?? "";
  }

  const rows = value.map((column, i) => {
    const owner = (several ? names.find((n) => n.name === (column.from ?? names[0].name)) : names[0]) ?? names[0];
    const fields = catalogue.types.find((t) => t.type === owner?.recordType)?.fields ?? [];
    const name = nameOf(column, fields);
    const shown = name || text.columnNeedsField;
    const isImages = column.images !== undefined;
    const marked = Boolean(column.width || column.link || (column.from && column.from !== names[0].name) || (isImages && Object.keys(column.images ?? {}).length > 0));
    return {
      id: String(i),
      name,
      detail: isImages ? text.imagesColumnKind : column.label && column.field ? column.field : undefined,
      actions: (
        <>
          {!disabled && (
            <>
              <button type="button" className="btn btn-sm btn-icon" disabled={i === 0} aria-label={text.moveColumnUp(shown)} onClick={() => move(i, -1)}>
                <ChevronUp size={14} aria-hidden="true" />
              </button>
              <button type="button" className="btn btn-sm btn-icon" disabled={i === value.length - 1} aria-label={text.moveColumnDown(shown)} onClick={() => move(i, 1)}>
                <ChevronDown size={14} aria-hidden="true" />
              </button>
            </>
          )}
          <SettingsPopoverButton
            label={text.columnSettings(shown)} title={text.columnSettings(shown)} marked={marked} defaultOpen={fresh === i}
          >
            <div className="stack" style={{ gap: "var(--space-2)" }}>
              {several && (
                <LabeledSelect helpNotNeeded
                  label={text.columnFrom} value={column.from ?? names[0].name} placeholder={null} disabled={disabled}
                  options={names.map(nameOption)} onChange={(from) => patch(i, isImages ? { from } : { from, field: "" })}
                />
              )}
              {!isImages && (
                <LabeledSelect helpNotNeeded
                  label={text.columnField} value={column.field ?? ""} placeholder={text.choose} disabled={disabled} required
                  options={fields.map((f) => ({ value: f.key, label: f.label }))} onChange={(field) => patch(i, { field })}
                />
              )}
              <TextField helpNotNeeded
                label={text.columnLabel} value={column.label ?? ""} disabled={disabled}
                placeholder={isImages ? text.imagesHeadingPlaceholder : text.columnHeadingPlaceholder}
                onChange={(label) => patch(i, { label })}
              />
              <TextField
                label={text.columnWidth} value={column.width ?? ""} placeholder={text.columnWidthPlaceholder} disabled={disabled}
                help={strings.help.reportColumnWidth} onChange={(width) => patch(i, { width })}
              />
              {!isImages && linkTargets(owner?.recordType, column.link?.sheet).length > 0 && (
                <LabeledSelect
                  label={text.columnLink} value={column.link?.sheet ?? ""} placeholder={text.columnNoLink} disabled={disabled}
                  help={strings.help.reportColumnLink}
                  options={linkTargets(owner?.recordType, column.link?.sheet).map((n) => ({ value: n, label: n }))}
                  onChange={(sheet) => patch(i, { link: { sheet } })}
                />
              )}
              {isImages && renderImageField && imageFields.map((f) => renderImageField(f, column.images ?? {}, owner?.recordType ?? null, (key, setting) => setRule(i, key, setting)))}
            </div>
          </SettingsPopoverButton>
          {!disabled && (
            <button type="button" className="btn btn-sm btn-icon" aria-label={text.removeColumn(shown)} title={text.removeColumn(shown)} onClick={() => onChange(value.filter((_, j) => j !== i))}>
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </>
      ),
    };
  });

  function add(column: Column) {
    setFresh(value.length);
    onChange([...value, column]);
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {rows.length > 0 && <ItemRowList items={rows} label={text.columnsList} emptyName={text.columnNeedsField} />}
      {!disabled && (
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <button type="button" className="btn btn-sm" onClick={() => add({ field: "" })}>{text.addColumn}</button>
          {renderImageField && imageFields.length > 0 && (
            <button type="button" className="btn btn-sm" onClick={() => add({ images: {} })}>{text.addImagesColumn}</button>
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
