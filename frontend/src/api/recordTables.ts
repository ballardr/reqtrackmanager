/**
 * Module: api/recordTables
 *
 * Types and calls for the generic record table routes (`/projects/{id}/records/{type}/columns|export|import`)
 * and the record-list report (`/projects/{id}/reports/record-list`, the PDF and Word of a list), which every
 * record list's Export and Import use. A record type is addressed only by its registered type
 * string; nothing here knows a particular type or module.
 */
import { api } from "./client";
import type { ReportDownloadKind } from "./reports";

/** One column of a record type's table (`RecordColumnOut`). */
export interface RecordColumn {
  key: string;
  label: string;
  kind: "text" | "enum" | "principal" | "date" | "number" | "bool" | "instant" | "list";
  importable: boolean;
  editable: boolean;
  required: boolean;
  sensitivity: string;
  /** False when the personal-data policy leaves the column out of exports and imports. */
  included: boolean;
  /** The accepted cell texts when they are a closed list, else null (free text). */
  choices: string[] | null;
}

/** A record type's table definition (`RecordColumnsOut`). */
export interface RecordColumns {
  label: string;
  columns: RecordColumn[];
  omitted_sensitivity: string[];
  /** Per omitted tag: `policy` (excluded by the organisation or server) or `permission` (the caller lacks the right). */
  omitted_reasons: Record<string, string>;
  importable: boolean;
  can_import: boolean;
  not_importable_reason: string | null;
  filter_params: string[];
  max_rows: number;
  max_bytes: number;
}

/** One cell an update changes. */
export interface ImportColumnChange {
  column: string;
  label: string;
  before: string;
  after: string;
}

/** What happened (or, in a preview, would happen) to one row. */
export interface ImportRowResult {
  row: number;
  action: "create" | "update" | "unchanged" | "error";
  code: string;
  changes: ImportColumnChange[];
  message: string;
}

/** The preview or result of an import (`ImportResultOut`). */
export interface RecordImportResult {
  applied: boolean;
  created: number;
  updated: number;
  unchanged: number;
  failed: number;
  rows: ImportRowResult[];
  ignored_columns: Record<string, string>;
  omitted_sensitivity: string[];
  error_csv: string;
}

/** Injectable calls so stories stay off the network. */
export interface RecordTablesApi {
  columns: (projectId: string, recordType: string) => Promise<RecordColumns>;
  /**
   * The list as a file, narrowed by the list's own filters (`filters` is a query string without the leading `?`):
   * the CSV that re-imports, or a PDF or Word document of the same rows (the record-list report).
   */
  exportFile: (projectId: string, recordType: string, kind: ReportDownloadKind, filters: string) => Promise<Blob>;
  /** A preview (`dryRun`) or an apply of the CSV. */
  importFile: (projectId: string, recordType: string, file: File, dryRun: boolean) => Promise<RecordImportResult>;
}

const base = (projectId: string, recordType: string) => `/api/v1/projects/${projectId}/records/${recordType}`;

export const recordTablesApi: RecordTablesApi = {
  columns: (projectId, recordType) => api.get<RecordColumns>(`${base(projectId, recordType)}/columns`),
  exportFile: (projectId, recordType, kind, filters) =>
    kind === "csv"
      ? api.getForBlob(`${base(projectId, recordType)}/export${filters ? `?${filters}` : ""}`)
      : api.getForBlob(
        `/api/v1/projects/${projectId}/reports/record-list?${new URLSearchParams({ record_type: recordType, format: kind })}${filters ? `&${filters}` : ""}`,
      ),
  importFile: (projectId, recordType, file, dryRun) =>
    api.postFile<RecordImportResult>(`${base(projectId, recordType)}/import?dry_run=${dryRun}`, file),
};

/** The one-line note for columns the policy left out, or an empty string when none were. */
export function omittedColumnsNote(columns: Pick<RecordColumns, "omitted_sensitivity" | "omitted_reasons">): string {
  if (columns.omitted_sensitivity.length === 0) return "";
  const byPermission = columns.omitted_sensitivity.every((tag) => columns.omitted_reasons[tag] === "permission");
  return byPermission
    ? "Some columns holding personal data are left out: you need the permission to export personal data."
    : "Some columns holding personal data are left out by your organisation's policy.";
}
