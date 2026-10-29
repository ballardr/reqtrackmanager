/**
 * Module: components/ReportKindIcon
 *
 * The one type icon of a report in a folder list: a document, a sheet of rows or a pack of files. The report chooser and
 * the Report setup list both draw it, so a report looks the same in both.
 */
import { FileText, Package, Table } from "lucide-react";

export type ReportKind = "report" | "sheet" | "pack";

/**
 * @param kind What the report is.
 * @returns A decorative icon (the row names the type in words beside it).
 */
export function ReportKindIcon({ kind }: { kind: ReportKind }) {
  if (kind === "sheet") return <Table aria-hidden="true" />;
  if (kind === "pack") return <Package aria-hidden="true" />;
  return <FileText aria-hidden="true" />;
}
