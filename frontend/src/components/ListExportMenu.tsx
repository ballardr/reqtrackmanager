/**
 * Module: components/ListExportMenu
 *
 * The "List actions" menu of a list that is **not** a registered record type and so has no Import (the project
 * History: an event is never authored). It offers the same Download shown items choice as the record lists
 * (`ListActions`): the filtered rows as CSV, PDF, Word, ODT or ODS, named by `REPORT_FORMAT`, with the outcome
 * in a toast. A list of records uses `ListPageLayout`'s `records` prop instead; this exists so the one list
 * without a record type does not hand-build a second export menu.
 */
import { useState } from "react";

import { REPORT_FORMAT } from "../api/reportFormats";
import { RECORD_LIST_EXPORT_KINDS } from "../api/recordTables";
import type { ReportDownloadKind } from "../api/reports";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { fileStem } from "../hooks/useRecordTableExport";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";

const strings = t();

/**
 * @param label The list's name (for the file name and the messages), e.g. `Project history`.
 * @param exportFile Fetches the filtered rows in the format; the server writes the file.
 * @param note One muted line under the items (for example that personal data was left out); omit for none.
 */
export function ListExportMenu({
  label, exportFile, note,
}: {
  label: string;
  exportFile: (kind: ReportDownloadKind) => Promise<Blob>;
  note?: string;
}) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const download = async (kind: ReportDownloadKind) => {
    setBusy(true);
    try {
      downloadBlob(await exportFile(kind), `${fileStem(label)}-export.${kind}`);
      showToast(strings.recordTables.exported(label, REPORT_FORMAT[kind].label));
    } catch (err) {
      showToast(toErrorMessage(err, strings.recordTables.exportFailed(label)), "error");
    } finally {
      setBusy(false);
    }
  };
  const items: ActionMenuItem[] = [{
    key: "download-shown",
    label: strings.recordTables.downloadShownItems,
    onSelect: () => undefined,
    children: RECORD_LIST_EXPORT_KINDS.map((kind): ActionMenuItem => ({
      key: `export:${kind}`,
      label: REPORT_FORMAT[kind].label,
      title: REPORT_FORMAT[kind].title,
      onSelect: () => void download(kind),
    })),
  }];
  return (
    <ActionMenu
      triggerLabel={strings.recordTables.menuLabel} items={items} disabled={busy}
      footer={note ? <span style={{ display: "block" }}>{note}</span> : undefined}
    />
  );
}
