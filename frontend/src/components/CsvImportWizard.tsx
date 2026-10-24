/**
 * Module: components/CsvImportWizard
 *
 * The import wizard of every record list (docs/ux-style-guide.md, "Pattern: list actions (export and import)"):
 * a picked CSV is mapped onto the record type's columns, previewed by the server, then applied.
 *
 * Steps (one `Modal`, its Back/Cancel/primary buttons pinned in the header through `FormActions`):
 * 1. **Map.** The file is parsed in the browser and each of the type's importable columns is paired with one of
 *    the file's headers (guessed from the key or label), or, for a column with a closed list of values
 *    (`choices`), given one fixed value for every row. A column left unmapped is not sent, so an update leaves
 *    that field alone.
 * 2. **Preview.** The file is rebuilt in the server's own headers and sent as a dry run: the server runs every row
 *    through the type's own create/update path and rolls it back, so the creates, updates (before and after of
 *    each changed field) and row errors shown are what an apply would do.
 * 3. **Apply.** The same file is sent for real. A `Toast` reads "N created, N updated, N failed"; failed rows come
 *    back as an error CSV to fix and upload again.
 *
 * The wizard knows no record type: the columns, their hints and their accepted values come from
 * `GET .../records/{type}/columns`. The mapping/fixed-value choice is purely client-side; the server only ever
 * receives the canonical CSV an export writes. Dependencies: papaparse, `api/recordTables`, `utils/recordImport`.
 */
import Papa from "papaparse";
import { useEffect, useMemo, useState } from "react";

import {
  omittedColumnsNote,
  recordTablesApi,
  type RecordColumn,
  type RecordColumns,
  type RecordImportResult,
  type RecordOwner,
  type RecordTablesApi,
} from "../api/recordTables";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";
import {
  buildImportCsv,
  CODE_COLUMN_KEY,
  guessMapping,
  missingRequired,
  type ColumnSource,
} from "../utils/recordImport";
import { RequiredMark } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { InlineSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

const strings = t();

/** Rows shown per list in the preview; the counts above them are always the full totals. */
const PREVIEW_LIMIT = 50;

type Step = "map" | "preview" | "done";

type ParsedFile = { headers: string[]; rows: Record<string, string>[] };

/** The one-line hint under a column's name: what its cells look like. */
function columnHint(column: RecordColumn): string {
  if (column.key === CODE_COLUMN_KEY) return strings.recordTables.codeHint;
  return strings.recordTables.kindHint[column.kind] ?? "";
}

/**
 * @param owner The project (or organisation) whose list is imported into.
 * @param recordType The registered record type.
 * @param columns The type's table definition (`GET .../columns`).
 * @param file The CSV the person picked.
 * @param onClose Called when the wizard should go away (cancel, or done).
 * @param onApplied Called after an apply wrote anything, so the list can reload.
 * @param tables Injectable calls (stories pass fakes).
 */
export function CsvImportWizard({
  owner, recordType, columns, file, onClose, onApplied, tables = recordTablesApi,
}: {
  owner: RecordOwner;
  recordType: string;
  columns: RecordColumns;
  file: File;
  onClose: () => void;
  onApplied: (result: RecordImportResult) => void;
  tables?: RecordTablesApi;
}) {
  const { showToast } = useToast();
  const [parsed, setParsed] = useState<ParsedFile | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [sources, setSources] = useState<Record<string, ColumnSource | undefined>>({});
  const [step, setStep] = useState<Step>("map");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RecordImportResult | null>(null);
  const [result, setResult] = useState<RecordImportResult | null>(null);

  /** `code` first, then every column the policy lets in that an import writes. */
  const mappable = useMemo(
    () => columns.columns.filter((c) => c.key === CODE_COLUMN_KEY || (c.importable && c.included)),
    [columns],
  );

  useEffect(() => {
    let active = true;
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        if (!active) return;
        const headers = results.meta.fields ?? [];
        setParsed({ headers, rows: results.data });
        const guessed = guessMapping(headers, mappable);
        setSources(Object.fromEntries(Object.entries(guessed).map(([key, header]) => [key, { kind: "header", header } as ColumnSource])));
      },
      error: () => active && setReadError(strings.recordTables.fileUnreadable),
    });
    return () => {
      active = false;
    };
  }, [file, mappable]);

  const setSource = (key: string, source: ColumnSource | undefined) => setSources((prev) => ({ ...prev, [key]: source }));

  const title = strings.recordTables.importTitle(columns.label);
  const tooMany = parsed !== null && parsed.rows.length > columns.max_rows;
  const tooBig = file.size > columns.max_bytes;
  const missing = missingRequired(mappable, sources);
  const sizeError = tooMany
    ? strings.recordTables.tooManyRows(columns.max_rows)
    : tooBig ? strings.recordTables.tooBig(Math.round(columns.max_bytes / (1024 * 1024))) : null;
  const omittedNote = omittedColumnsNote(columns);

  /** The file rebuilt in the server's headers, as an uploadable file. */
  function canonicalFile(): File {
    const text = buildImportCsv(parsed?.rows ?? [], mappable, sources);
    return new File([text], "import.csv", { type: "text/csv" });
  }

  async function runPreview() {
    setBusy(true);
    setError(null);
    try {
      setPreview(await tables.importFile(owner, recordType, canonicalFile(), true));
      setStep("preview");
    } catch (err) {
      setError(toErrorMessage(err, strings.recordTables.importFailed));
    } finally {
      setBusy(false);
    }
  }

  async function runApply() {
    setBusy(true);
    setError(null);
    try {
      const applied = await tables.importFile(owner, recordType, canonicalFile(), false);
      showToast(strings.recordTables.applied(applied.created, applied.updated, applied.failed), applied.failed > 0 ? "error" : "success");
      if (applied.created > 0 || applied.updated > 0) onApplied(applied);
      if (applied.failed > 0) {
        setResult(applied);
        setStep("done");
      } else {
        onClose();
      }
    } catch (err) {
      setError(toErrorMessage(err, strings.recordTables.importFailed));
    } finally {
      setBusy(false);
    }
  }

  function downloadErrors() {
    if (!result) return;
    downloadBlob(new Blob([result.error_csv], { type: "text/csv" }), strings.recordTables.errorsFileName(columns.label));
  }

  function renderMapRow(column: RecordColumn) {
    const source = sources[column.key];
    const fixed = source?.kind === "fixed";
    const canFix = column.choices !== null && column.key !== CODE_COLUMN_KEY;
    const lower = column.label.toLowerCase();
    return (
      <tr key={column.key}>
        <td>
          {column.label}
          {column.required && <RequiredMark />}
        </td>
        <td>
          {canFix && (
            <label className="checkbox-label" style={{ gap: "var(--space-2)", marginBottom: "var(--space-1)" }}>
              <input
                type="checkbox"
                checked={fixed}
                // Every fixed-value toggle shares the visible text, so an explicit name keeps them apart.
                aria-label={`Use the same ${lower} for every row`}
                onChange={(e) => setSource(column.key, e.target.checked ? { kind: "fixed", value: "" } : undefined)}
              />
              <span className="text-muted">{strings.recordTables.sameValue}</span>
            </label>
          )}
          {fixed ? (
            <InlineSelect
              ariaLabel={`Fixed ${lower}`} placeholder={strings.recordTables.fixedChoose}
              value={source.value} onChange={(value) => setSource(column.key, { kind: "fixed", value })}
              options={(column.choices ?? []).map((choice) => ({ value: choice, label: choice }))}
            />
          ) : (
            <InlineSelect
              ariaLabel={`Map ${column.label}`} placeholder={strings.recordTables.unmapped}
              value={source?.kind === "header" ? source.header : ""}
              options={(parsed?.headers ?? []).map((h) => ({ value: h, label: h }))}
              onChange={(header) => setSource(column.key, header ? { kind: "header", header } : undefined)}
            />
          )}
        </td>
        <td className="text-muted">{columnHint(column)}</td>
      </tr>
    );
  }

  const changes = preview?.rows.filter((r) => r.action === "update") ?? [];
  const errors = (step === "done" ? result : preview)?.rows.filter((r) => r.action === "error") ?? [];
  const writes = (preview?.created ?? 0) + (preview?.updated ?? 0);

  return (
    <Modal title={title} onClose={onClose} size="lg">
      <div className="stack">
        {readError && <p style={{ color: "var(--color-danger)", margin: 0 }}>{readError}</p>}

        {step === "map" && parsed && (
          <>
            <p className="text-muted" style={{ margin: 0 }}>{strings.recordTables.mapIntro}</p>
            <p className="text-muted" style={{ margin: 0 }}>{strings.recordTables.fileSummary(parsed.rows.length, parsed.headers.length)}</p>
            {omittedNote && <p className="text-muted" style={{ margin: 0 }}>{omittedNote}</p>}
            <table>
              <thead>
                <tr><th>Field</th><th>Your column</th><th>What it's for</th></tr>
              </thead>
              <tbody>{mappable.map(renderMapRow)}</tbody>
            </table>
            {missing.length > 0 && (
              <p style={{ color: "var(--color-danger)", margin: 0 }}>{strings.recordTables.needsColumns(missing.join(", "))}</p>
            )}
            {sizeError && <p style={{ color: "var(--color-danger)", margin: 0 }}>{sizeError}</p>}
            <FormActions
              error={error} onCancel={onClose} cancelDisabled={busy}
              onSave={runPreview} saveDisabled={busy || missing.length > 0 || sizeError !== null || parsed.rows.length === 0}
              saveLabel={busy ? strings.recordTables.previewing : strings.recordTables.preview}
            />
          </>
        )}

        {step === "preview" && preview && (
          <>
            <p className="text-muted" style={{ margin: 0 }}>{strings.recordTables.previewIntro}</p>
            <strong>{strings.recordTables.previewSummary(preview.created, preview.updated, preview.unchanged, preview.failed)}</strong>
            {Object.keys(preview.ignored_columns).length > 0 && (
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                <strong>{strings.recordTables.ignoredColumns}</strong>
                <ul style={{ margin: 0 }}>
                  {Object.entries(preview.ignored_columns).map(([name, reason]) => (
                    <li key={name} className="text-muted">{name}: {reason}</li>
                  ))}
                </ul>
              </div>
            )}
            {changes.length > 0 && (
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                <strong>{strings.recordTables.changesHeading}</strong>
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr><th>Record</th><th>Field</th><th>Before</th><th>After</th></tr>
                    </thead>
                    <tbody>
                      {changes.slice(0, PREVIEW_LIMIT).flatMap((row) =>
                        row.changes.map((change) => (
                          <tr key={`${row.row}-${change.column}`}>
                            <td>{row.code}</td>
                            <td>{change.label}</td>
                            <td className="text-muted">{change.before}</td>
                            <td>{change.after}</td>
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                </div>
                {changes.length > PREVIEW_LIMIT && (
                  <span className="text-muted">…and {changes.length - PREVIEW_LIMIT} more updated record(s).</span>
                )}
              </div>
            )}
            {errors.length > 0 && (
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                <strong>{strings.recordTables.errorsHeading}</strong>
                <ul style={{ margin: 0 }}>
                  {errors.slice(0, PREVIEW_LIMIT).map((row) => (
                    <li key={row.row} className="text-muted">{strings.recordTables.errorRow(row.row, row.message)}</li>
                  ))}
                </ul>
                {errors.length > PREVIEW_LIMIT && <span className="text-muted">…and {errors.length - PREVIEW_LIMIT} more.</span>}
              </div>
            )}
            {writes === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.recordTables.nothingToApply}</p>}
            <FormActions
              error={error} onCancel={onClose} cancelDisabled={busy}
              leading={<button className="btn" disabled={busy} onClick={() => setStep("map")}>{strings.common.back}</button>}
              onSave={runApply} saveDisabled={busy || writes === 0}
              saveLabel={busy ? strings.recordTables.applying : strings.recordTables.apply(writes)}
            />
          </>
        )}

        {step === "done" && result && (
          <>
            <strong>{strings.recordTables.applied(result.created, result.updated, result.failed)}</strong>
            <ul style={{ margin: 0 }}>
              {errors.slice(0, PREVIEW_LIMIT).map((row) => (
                <li key={row.row} className="text-muted">{strings.recordTables.errorRow(row.row, row.message)}</li>
              ))}
            </ul>
            <p className="text-muted" style={{ margin: 0 }}>{strings.recordTables.errorFileHint}</p>
            <FormActions
              onCancel={onClose} cancelLabel={strings.common.close}
              onSave={downloadErrors} saveLabel={strings.recordTables.downloadErrors}
            />
          </>
        )}
      </div>
    </Modal>
  );
}
