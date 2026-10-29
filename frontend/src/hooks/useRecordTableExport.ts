/**
 * Module: hooks/useRecordTableExport
 *
 * Downloads a record list as a CSV (the file that re-imports), a PDF, Word, OpenDocument text or OpenDocument spreadsheet file, each with the list's own
 * filters, for the shared list actions. Reports the outcome in a `Toast` (success or failure), so a caller only
 * decides when to start it. The server writes every file, so the browser only saves what it is sent.
 */
import { useCallback } from "react";

import { REPORT_FORMAT } from "../api/reportFormats";
import type { ReportDownloadKind } from "../api/reports";
import { recordTablesApi, type RecordOwner, type RecordTablesApi } from "../api/recordTables";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";

const strings = t();

/** A file name stem from a plural label: `Pain Points` becomes `pain-points`. */
export function fileStem(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "records";
}

/**
 * @param owner The project (or organisation) whose list is exported.
 * @param recordType The registered record type.
 * @param label The type's plural name (for the file name and messages).
 * @param filters The list's filters as a query string without the leading `?` (`status=draft&tag=a`).
 * @param tables Injectable calls (stories pass fakes).
 * @returns `exportList`, which downloads the filtered list in the chosen format and resolves when the download
 *   started or failed.
 */
export function useRecordTableExport(
  owner: RecordOwner, recordType: string, label: string, filters: string, tables: RecordTablesApi = recordTablesApi,
): { exportList: (kind: ReportDownloadKind) => Promise<void> } {
  const { showToast } = useToast();
  const exportList = useCallback(async (kind: ReportDownloadKind) => {
    try {
      const blob = await tables.exportFile(owner, recordType, kind, filters);
      downloadBlob(blob, `${fileStem(label)}-export.${kind}`);
      showToast(strings.recordTables.exported(label, REPORT_FORMAT[kind].label));
    } catch (err) {
      showToast(toErrorMessage(err, strings.recordTables.exportFailed(label)), "error");
    }
  }, [owner, recordType, label, filters, tables, showToast]);
  return { exportList };
}
