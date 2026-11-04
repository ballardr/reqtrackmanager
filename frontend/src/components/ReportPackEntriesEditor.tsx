/**
 * Module: components/ReportPackEntriesEditor
 *
 * The "Reports" tab of the pack editor: the ordered list of reports in the pack. Each is a custom layout (named, with
 * an optional owner tier) or a module report, with its format, the file name inside the zip, and values it pins
 * (a layout's variables) or options it sets (a module report's filters).
 *
 * Responsibilities:
 * - Add, remove and reorder entries; each entry carries a client-only `uid` so a reorder keeps the right text in
 *   the right box (`DraftEntry`).
 * - Offer only what the scope can use: the layouts the scope can reach and the module reports the catalogue lists,
 *   with the formats each can be produced in (a document layout: PDF, Word, HTML; a table layout: CSV, Excel; a
 *   module report: PDF, Word, CSV).
 * - Stay controlled: the editor owns the draft and the save; this component only edits the list it is given.
 *
 * Design decisions: an entry names its layout (not an id) so the pack is portable between organisations and resolves
 * for the project it runs in; a layout name no longer in the list is still shown, so a pack naming a layout that was
 * renamed or hidden can be seen and corrected rather than silently changed.
 */
import {
  REPORT_ENTRY_FORMATS,
  type FixedValue,
  type LayoutPackEntry,
  type PackFormat,
  type ReportPackEntry,
  type ReportPackReportEntry,
} from "../api/reportPacks";
import { reportFormatLabel } from "../api/reportFormats";
import { useStrings } from "../context/TerminologyContext";
import { FAMILY_FORMATS, layoutFormats, newUid, type LayoutChoice } from "../utils/reportPackDraft";
import { FileNameField } from "./FileNameField";
import { JsonObjectField } from "./JsonObjectField";
import { LabeledSelect } from "./LabeledSelect";

/** An entry in the editor's draft, with a client-only id that is dropped when the pack is saved. */
export interface DraftEntry {
  uid: string;
  entry: ReportPackEntry;
}

/** A module report the scope can run, as the picker offers it. */
export interface ReportChoice {
  module_key: string;
  report: string;
  title: string;
}

/**
 * @param entries The draft entries, in order.
 * @param onChange Called with the new list after any edit.
 * @param layouts The layouts the scope can reach.
 * @param reports The module reports the scope can run.
 * @param inProject Whether the pack is a project's (an entry can then pin which owner's layout it means).
 * @param disabled Read-only (a pack shared from elsewhere).
 * @param onValidity Called with an entry's uid and whether its JSON boxes are currently acceptable.
 */
export function ReportPackEntriesEditor({
  entries, onChange, layouts, reports, inProject, disabled = false, onValidity,
}: {
  entries: DraftEntry[];
  onChange: (next: DraftEntry[]) => void;
  layouts: LayoutChoice[];
  reports: ReportChoice[];
  inProject: boolean;
  disabled?: boolean;
  onValidity?: (key: string, valid: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportPacks;

  function patch(uid: string, change: Partial<LayoutPackEntry> | Partial<ReportPackReportEntry>) {
    onChange(entries.map((d) => (d.uid === uid ? { ...d, entry: { ...d.entry, ...change } as ReportPackEntry } : d)));
  }
  function move(index: number, by: -1 | 1) {
    const next = [...entries];
    const target = index + by;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.entriesIntro}</p>
      {entries.length === 0 && <p className="text-muted">{text.noEntries}</p>}
      {entries.map((draft, index) => {
        const entry = draft.entry;
        return (
          <section key={draft.uid} className="card stack" aria-label={text.entryLabel(index + 1)}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>{text.entryLabel(index + 1)}</strong>
              {!disabled && (
                <div className="row">
                  <button type="button" className="btn" disabled={index === 0} onClick={() => move(index, -1)}>{text.moveUp}</button>
                  <button type="button" className="btn" disabled={index === entries.length - 1} onClick={() => move(index, 1)}>{text.moveDown}</button>
                  <button type="button" className="btn btn-danger" onClick={() => onChange(entries.filter((d) => d.uid !== draft.uid))}>
                    {text.removeEntry}
                  </button>
                </div>
              )}
            </div>
            <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }}>
              {entry.kind === "layout" ? (
                <>
                  <LabeledSelect helpNotNeeded required
                    label={text.layoutLabel}
                    value={entry.name}
                    disabled={disabled}
                    placeholder={text.layoutPlaceholder}
                    onChange={(name) => {
                      const formats = layoutFormats(layouts, name);
                      patch(draft.uid, { name, format: formats.includes(entry.format) ? entry.format : formats[0] });
                    }}
                    options={[
                      ...layouts.map((l) => ({ value: l.name, label: l.name })),
                      ...(entry.name && !layouts.some((l) => l.name === entry.name) ? [{ value: entry.name, label: entry.name }] : []),
                    ]}
                  />
                  {inProject && (
                    <LabeledSelect help={strings.help.reportPackTier}
                      label={text.tierLabel}
                      value={entry.tier ?? ""}
                      disabled={disabled}
                      placeholder={text.tierAny}
                      onChange={(tier) => patch(draft.uid, { tier: tier === "" ? undefined : (tier as "organization" | "project") })}
                      options={[{ value: "organization", label: text.tierOrganization }, { value: "project", label: text.tierProject }]}
                    />
                  )}
                </>
              ) : (
                <LabeledSelect helpNotNeeded required
                  label={text.moduleReportLabel}
                  value={`${entry.module_key}|${entry.report}`}
                  disabled={disabled}
                  placeholder={text.moduleReportPlaceholder}
                  onChange={(value) => {
                    const [module_key, report] = value.split("|");
                    patch(draft.uid, { module_key, report });
                  }}
                  options={[
                    ...reports.map((r) => ({ value: `${r.module_key}|${r.report}`, label: r.title })),
                    ...(entry.report && !reports.some((r) => r.module_key === entry.module_key && r.report === entry.report)
                      ? [{ value: `${entry.module_key}|${entry.report}`, label: `${entry.module_key}: ${entry.report}` }]
                      : []),
                  ]}
                />
              )}
              <LabeledSelect helpNotNeeded required
                label={text.formatLabel}
                value={entry.format}
                disabled={disabled}
                placeholder={null}
                onChange={(format) => patch(draft.uid, { format: format as PackFormat })}
                options={(entry.kind === "layout" ? layoutFormats(layouts, entry.name) : REPORT_ENTRY_FORMATS).map((f) => ({
                  value: f, label: reportFormatLabel(f),
                }))}
              />
              <FileNameField help={strings.help.reportPackFilename}
                label={text.filenameLabel}
                value={entry.filename ?? ""}
                disabled={disabled}
                kind="entry"
                extension={entry.format}
                onChange={(filename) => patch(draft.uid, { filename: filename === "" ? undefined : filename })}
              />
            </div>
            {entry.kind === "layout" ? (
              <JsonObjectField
                label={text.fixedLabel}
                help={strings.help.reportPackFixed}
                hint={text.fixedHint}
                value={entry.variables}
                onChange={(variables) => patch(draft.uid, { variables: variables as Record<string, FixedValue> | undefined })}
                onValidity={(ok) => onValidity?.(draft.uid, ok)}
              />
            ) : (
              <JsonObjectField
                label={text.paramsLabel}
                help={strings.help.reportPackParams}
                hint={text.paramsHint}
                value={entry.params}
                onChange={(params) => patch(draft.uid, { params: params as ReportPackReportEntry["params"] })}
                onValidity={(ok) => onValidity?.(draft.uid, ok)}
              />
            )}
          </section>
        );
      })}
      {!disabled && (
        <div className="row">
          <button
            type="button" className="btn"
            onClick={() => {
              const first = layouts[0];
              onChange([...entries, {
                uid: newUid(),
                entry: { kind: "layout", name: first?.name ?? "", format: first ? FAMILY_FORMATS[first.family][0] : "pdf" },
              }]);
            }}
          >
            {text.addLayout}
          </button>
          <button
            type="button" className="btn"
            onClick={() => {
              const first = reports[0];
              onChange([...entries, {
                uid: newUid(), entry: { kind: "report", module_key: first?.module_key ?? "", report: first?.report ?? "", format: "pdf" },
              }]);
            }}
          >
            {text.addReport}
          </button>
        </div>
      )}
    </div>
  );
}
