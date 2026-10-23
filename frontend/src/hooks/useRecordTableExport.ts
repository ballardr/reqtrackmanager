/**
 * Module: hooks/useRecordTableExport
 *
 * Downloads a record list as a CSV with the list's own filters, and the import template, for the shared list
 * actions. Reports the outcome in a `Toast` (success or failure), so a caller only decides when to start it.
 * The server writes the file that re-imports, so the browser only saves what it is sent.
 */
import { useCallback } from "react";

import { recordTablesApi, type RecordTablesApi } from "../api/recordTables";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";

const strings = t();

/** A file name stem from a plural label: `Pain Points` becomes `pain-points`. */
export function fileStem(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "records";
}

/**
 * @param projectId The project whose list is exported.
 * @param recordType The registered record type.
 * @param label The type's plural name (for the file name and messages).
 * @param filters The list's filters as a query string without the leading `?` (`status=draft&tag=a`).
 * @param tables Injectable calls (stories pass fakes).
 * @returns `exportCsv`, which downloads the filtered list and resolves when the download started or failed.
 */
export function useRecordTableExport(
  projectId: string, recordType: string, label: string, filters: string, tables: RecordTablesApi = recordTablesApi,
): { exportCsv: () => Promise<void> } {
  const { showToast } = useToast();
  const exportCsv = useCallback(async () => {
    try {
      const blob = await tables.exportCsv(projectId, recordType, filters);
      downloadBlob(blob, `${fileStem(label)}-export.csv`);
      showToast(strings.recordTables.exported(label));
    } catch (err) {
      showToast(toErrorMessage(err, strings.recordTables.exportFailed(label)), "error");
    }
  }, [projectId, recordType, label, filters, tables, showToast]);
  return { exportCsv };
}
