/**
 * Module: components/ReportLayoutSourceEditor
 *
 * Edits where a block's records come from: all records of a type, the records linked to an enclosing record, or
 * the members of an enclosing group; with optional conditions (`where`), up to three sort keys and, for a type,
 * whether archived records are included.
 *
 * Responsibilities:
 * - Offer only what the surrounding blocks give: the "linked from" and "group" choices list the names in scope.
 * - Keep the stored shape exactly as the server validates it, dropping keys that no longer apply when the mode
 *   changes (a group source has no record type).
 *
 * Design decisions: link types are typed by name (a layout stores names, not ids, so it moves between projects),
 * so the server's check, not a client list, says whether a name exists. A sheet's join has no "all records" mode
 * (`joinMode`): it can only follow a link from an earlier name.
 */
import type { BlockCatalogue, ReportFieldCatalogue } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import type { NameInScope } from "../utils/reportLayoutTree";
import { ConditionListEditor, type Condition, type ConditionEnv } from "./ReportLayoutConditionEditor";
import { CommaListField } from "./CommaListField";
import { CheckboxField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";

type Source = Record<string, unknown>;
type Mode = "all" | "linked" | "group";

/** Most sort keys a source takes. */
const MAX_SORT_KEYS = 3;

const modeOf = (source: Source): Mode => ("group" in source ? "group" : "linked_from" in source ? "linked" : "all");

/**
 * @param value The source as stored (`{}` for a new block).
 * @param onChange Called with the edited source.
 * @param names The names the enclosing blocks bring into scope.
 * @param catalogue The record types and fields.
 * @param blocks The block catalogue (operators for the `where` tests).
 * @param variables Names of the layout's declared variables.
 * @param joinMode A sheet's join: it can only follow a link from an earlier name.
 * @param disabled Read-only.
 */
export function ReportLayoutSourceEditor({
  value, onChange, names, catalogue, blocks, variables, joinMode = false, disabled,
}: {
  value: Source;
  onChange: (next: Source) => void;
  names: NameInScope[];
  catalogue: ReportFieldCatalogue;
  blocks: BlockCatalogue;
  variables: string[];
  joinMode?: boolean;
  disabled?: boolean;
}) {
  const text = useStrings().reportOutline;
  const mode = joinMode ? "linked" : modeOf(value);
  const recordNames = names.filter((n) => n.kind === "record");
  const groupNames = names.filter((n) => n.kind === "group");
  const recordType = typeof value.record_type === "string" ? value.record_type : null;
  const memberType = mode === "group" ? (groupNames.find((n) => n.name === value.group)?.recordType ?? null) : recordType;
  const fields = catalogue.types.find((t) => t.type === memberType)?.fields ?? [];
  const sort = Array.isArray(value.sort) ? (value.sort as { field?: string; descending?: boolean }[]) : [];
  const where = Array.isArray(value.where) ? (value.where as Condition[]) : [];
  const conditionEnv: ConditionEnv = { mode: "record", recordType: memberType, catalogue, blocks, variables, modules: [], disabled };

  /** A copy with `patch` applied; an `undefined` value or an empty list removes the key. */
  function change(patch: Source) {
    const next: Source = { ...value, ...patch };
    for (const key of Object.keys(next)) {
      const v = next[key];
      if (v === undefined || (Array.isArray(v) && v.length === 0)) delete next[key];
    }
    onChange(next);
  }

  function setMode(next: Mode) {
    if (next === mode) return;
    const keep = { where: value.where, sort: value.sort };
    if (next === "all") onChange({ record_type: recordType ?? undefined, ...keep });
    else if (next === "linked") onChange({ record_type: recordType ?? undefined, linked_from: recordNames[0]?.name ?? "", ...keep });
    else onChange({ group: groupNames[0]?.name ?? "", ...keep });
  }

  const modeOptions = [
    { value: "all", label: text.sourceAll },
    { value: "linked", label: text.sourceLinked },
    { value: "group", label: text.sourceGroup },
  ];
  const linkTypes = Array.isArray(value.link_types) ? (value.link_types as string[]) : [];

  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      {!joinMode && (
        <LabeledSelect helpNotNeeded
          label={text.sourceMode} value={mode} placeholder={null} disabled={disabled}
          options={modeOptions} onChange={(m) => setMode(m as Mode)}
        />
      )}
      {mode !== "group" && (
        <LabeledSelect helpNotNeeded
          label={text.recordType} value={recordType ?? ""} placeholder={text.choose} disabled={disabled} required
          options={catalogue.types.map((t) => ({ value: t.type, label: t.label }))}
          onChange={(type) => change({ record_type: type === "" ? undefined : type, where: undefined, sort: undefined })}
        />
      )}
      {mode === "linked" && (
        <>
          <LabeledSelect helpNotNeeded
            label={text.linkedFrom} value={String(value.linked_from ?? "")} placeholder={text.choose} disabled={disabled} required
            options={recordNames.map((n) => ({ value: n.name, label: n.name }))} onChange={(name) => change({ linked_from: name })}
            hint={recordNames.length === 0 ? text.noNamesInScope : undefined}
          />
          <CommaListField
            label={text.linkTypes} value={linkTypes} disabled={disabled} hint={text.linkTypesHint}
            onChange={(next) => change({ link_types: next })}
          />
          <LabeledSelect helpNotNeeded
            label={text.direction} value={String(value.direction ?? "both")} placeholder={null} disabled={disabled}
            options={Object.entries(text.directionLabels).map(([v, label]) => ({ value: v, label }))}
            onChange={(d) => change({ direction: d === "both" ? undefined : d })}
          />
        </>
      )}
      {mode === "group" && (
        <LabeledSelect helpNotNeeded
          label={text.group} value={String(value.group ?? "")} placeholder={text.choose} disabled={disabled} required
          options={groupNames.map((n) => ({ value: n.name, label: n.name }))}
          onChange={(name) => change({ group: name, where: undefined, sort: undefined })}
          hint={groupNames.length === 0 ? text.noNamesInScope : undefined}
        />
      )}
      {mode !== "group" && (
        <CheckboxField helpNotNeeded
          label={text.includeArchived} checked={value.include_archived === true} disabled={disabled}
          onChange={(on) => change({ include_archived: on ? true : undefined })}
        />
      )}
      {memberType !== null && (
        <>
          <div className="stack" style={{ gap: "var(--space-2)" }} role="group" aria-label={text.where}>
            <strong>{text.where}</strong>
            <ConditionListEditor env={conditionEnv} value={where} onChange={(next) => change({ where: next })} />
          </div>
          <div className="stack" style={{ gap: "var(--space-2)" }} role="group" aria-label={text.sortBy}>
            <strong>{text.sortBy}</strong>
            {sort.map((key, i) => (
              <span key={i} className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end" }}>
                <LabeledSelect helpNotNeeded
                  label={text.sortField(i + 1)} value={key.field ?? ""} placeholder={text.choose} disabled={disabled}
                  options={fields.map((f) => ({ value: f.key, label: f.label }))}
                  onChange={(field) => change({ sort: sort.map((k, j) => (j === i ? { ...k, field } : k)) })}
                />
                <CheckboxField helpNotNeeded
                  label={text.descending} checked={key.descending === true} disabled={disabled} ariaLabel={`${text.sortField(i + 1)}: ${text.descending}`}
                  onChange={(on) => change({ sort: sort.map((k, j) => (j === i ? { field: k.field, ...(on ? { descending: true } : {}) } : k)) })}
                />
                {!disabled && (
                  <button type="button" className="btn btn-sm" aria-label={text.removeSort(i + 1)} onClick={() => change({ sort: sort.filter((_, j) => j !== i) })}>
                    {text.removeSort(i + 1)}
                  </button>
                )}
              </span>
            ))}
            {!disabled && sort.length < MAX_SORT_KEYS && (
              <div>
                <button type="button" className="btn btn-sm" onClick={() => change({ sort: [...sort, { field: "" }] })}>{text.addSort}</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
