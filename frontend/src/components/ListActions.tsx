/**
 * Module: components/ListActions
 *
 * The Export and Import controls of a record list (docs/ux-style-guide.md, "Pattern: list actions (export and
 * import)"), rendered by `ListPageLayout` beside the page's own actions so no list hand-builds them.
 *
 * - **Export** is `ReportExportButton`'s popover: the list as a CSV that re-imports, a PDF or a Word document
 *   (the record-list report), each narrowed by the page's own filters (never the full set), plus the import
 *   template, plus a note when the personal-data policy left columns out.
 * - **Import** is a file picker that opens `CsvImportWizard`; it is shown only to a person who may create or
 *   update the type's records, and not at all for a type that gives a reason it cannot be imported.
 *
 * It reads the type's columns once (`GET .../records/{type}/columns`) and renders nothing when the type has no
 * table or the caller cannot see it. It knows no record type or module.
 *
 * A list that shows several record kinds at once (the People list) renders one `ListActions` per kind, each with a
 * `kindLabel`, so the buttons read "Export personas" and "Export stakeholders" and each acts on its own kind.
 */
import { Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { ReportDownloadKind } from "../api/reports";
import { omittedColumnsNote, recordTablesApi, type RecordColumns, type RecordTablesApi } from "../api/recordTables";
import { useRecordTableExport, fileStem } from "../hooks/useRecordTableExport";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";
import { CODE_COLUMN_KEY, templateCsv } from "../utils/recordImport";
import { CsvImportWizard } from "./CsvImportWizard";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { ReportExportButton } from "./ReportExportButton";

const strings = t();

/** The formats of the Export menu: the CSV that re-imports, then the record-list report's PDF and Word. */
const EXPORT_KINDS: readonly ReportDownloadKind[] = ["csv", "pdf", "docx"];

/** What a list page tells `ListPageLayout` so it can offer Export and Import. */
export interface RecordListActions {
  projectId: string;
  /** The registered record type string. */
  recordType: string;
  /** The page's filters as a query string without `?` (the same names its list request sends, minus paging and sort). */
  filters?: string;
  /** Names the kind when a list shows several (`personas`): the buttons then read "Export personas". */
  kindLabel?: string;
  /** Called after an import wrote records, so the page reloads its list. */
  onImported?: () => void;
  /** Injectable calls (stories pass fakes). */
  tables?: RecordTablesApi;
}

/**
 * @param projectId The project whose list this is.
 * @param recordType The registered record type.
 * @param filters The page's current filters as a query string.
 * @param kindLabel Names the kind when the list shows several.
 * @param onImported Called after an import wrote records.
 * @param tables Injectable calls.
 */
export function ListActions({ projectId, recordType, filters = "", kindLabel, onImported, tables = recordTablesApi }: RecordListActions) {
  const [columns, setColumns] = useState<RecordColumns | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const label = columns?.label ?? "";
  const { exportList } = useRecordTableExport(projectId, recordType, label, filters, tables);

  useEffect(() => {
    let active = true;
    tables.columns(projectId, recordType).then((value) => active && setColumns(value)).catch(() => active && setColumns(null));
    return () => {
      active = false;
    };
  }, [projectId, recordType, tables]);

  const downloadTemplate = useCallback(() => {
    if (!columns) return;
    const writable = columns.columns.filter((c) => c.key === CODE_COLUMN_KEY || (c.importable && c.included));
    downloadBlob(new Blob([templateCsv(writable)], { type: "text/csv" }), `${fileStem(columns.label)}-import-template.csv`);
  }, [columns]);

  if (!columns) return null;
  const canImport = columns.importable && columns.can_import;
  return (
    <>
      <ReportExportButton
        label={kindLabel ? `${strings.recordTables.exportLabel} ${kindLabel}` : undefined}
        kinds={EXPORT_KINDS}
        onDownload={exportList}
        extras={canImport ? [{ key: "template", label: strings.recordTables.downloadTemplate, onSelect: downloadTemplate }] : []}
        note={omittedColumnsNote(columns) || undefined}
      />
      {canImport && (
        <FileUploadTrigger accept=".csv,text/csv" onSelect={setFile}>
          <Upload size={16} /> {kindLabel ? `${strings.recordTables.import} ${kindLabel}` : strings.recordTables.import}
        </FileUploadTrigger>
      )}
      {file && (
        <CsvImportWizard
          projectId={projectId} recordType={recordType} columns={columns} file={file} tables={tables}
          onClose={() => setFile(null)} onApplied={() => onImported?.()}
        />
      )}
    </>
  );
}
