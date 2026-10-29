/**
 * Module: api/recordTables
 *
 * Types and calls for the generic record table routes (`/projects/{id}/records/{type}/columns|export|import`,
 * and `/orgs/{id}/records/{type}/...` for the records an organisation owns) and the record-list report
 * (`.../reports/record-list`, the PDF and Word of a list), which every record list's Export and Import use, and the
 * bulk edit grid's `.../records/{type}/grid` and `.../rows/{code}` (a project's lists only). A
 * record type is addressed only by its registered type string; nothing here knows a particular type or module.
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

/** One column of the bulk edit grid (`GridColumnOut`). */
export interface GridColumn {
  key: string;
  label: string;
  kind: RecordColumn["kind"];
  /** True when the grid edits it: an importable, closed-value column the provider marked editable. */
  editable: boolean;
  required: boolean;
  choices: string[] | null;
}

/** One record of the grid (`GridRowOut`). */
export interface GridRow {
  id: string;
  /** The code as an export writes it (qualified for another project's record). */
  code: string;
  /** Cell text by column key. */
  cells: Record<string, string>;
  /** Why the whole row cannot be edited (a locked record, another project's), or null. */
  read_only: string | null;
  /** Why a single cell cannot be edited, by column key. */
  locks: Record<string, string>;
  /** The project that owns the record (a related project's row differs from the list's), or null for one the organisation owns. */
  project_id: string | null;
}

/** A list prepared for the bulk edit grid (`RecordGridOut`). */
export interface RecordGridData {
  label: string;
  columns: GridColumn[];
  rows: GridRow[];
  total: number;
  /** True when the filters matched more records than the grid loaded. */
  truncated: boolean;
  max_rows: number;
  /** False when the caller may not update this type's records. */
  can_edit: boolean;
  omitted_sensitivity: string[];
}

/** Whose records a list shows: a project's, or the ones an organisation owns itself. */
export type RecordOwner = { projectId: string; organizationId?: undefined } | { organizationId: string; projectId?: undefined };

/**
 * @param ids Exactly one of the two ids a list page has.
 * @returns The owner the table calls take.
 * @throws Error when neither id is given.
 */
export function recordOwner(ids: { projectId?: string; organizationId?: string }): RecordOwner {
  if (ids.projectId) return { projectId: ids.projectId };
  if (ids.organizationId) return { organizationId: ids.organizationId };
  throw new Error("A record list needs a project or an organisation.");
}

/** Injectable calls so stories stay off the network. */
export interface RecordTablesApi {
  columns: (owner: RecordOwner, recordType: string) => Promise<RecordColumns>;
  /**
   * The list as a file, narrowed by the list's own filters (`filters` is a query string without the leading `?`):
   * the CSV that re-imports, or a PDF or Word document of the same rows (the record-list report).
   */
  exportFile: (owner: RecordOwner, recordType: string, kind: ReportDownloadKind, filters: string) => Promise<Blob>;
  /** A preview (`dryRun`) or an apply of the CSV. */
  importFile: (owner: RecordOwner, recordType: string, file: File, dryRun: boolean) => Promise<RecordImportResult>;
  /** The list's rows for the bulk edit grid, narrowed by the list's own filters (`filters`: a query string without `?`). */
  grid: (projectId: string, recordType: string, filters: string) => Promise<RecordGridData>;
  /**
   * Saves the changed cells of one record. `expected` is what each cell held when the grid loaded it, so a cell
   * someone else changed since is refused (409) instead of overwritten. Resolves to the row as it is now.
   */
  saveRow: (projectId: string, recordType: string, code: string, cells: Record<string, string>, expected: Record<string, string>) => Promise<GridRow>;
}

/**
 * The formats of the record-list menu's Download shown items: the CSV that re-imports first, then the record-list
 * report as PDF, Word and OpenDocument text and spreadsheet. HTML and Excel are left to Download report.
 */
export const RECORD_LIST_EXPORT_KINDS: readonly ReportDownloadKind[] = ["csv", "pdf", "docx", "odt", "ods"];

const ownerRoot = (owner: RecordOwner) => (owner.projectId ? `/api/v1/projects/${owner.projectId}` : `/api/v1/orgs/${owner.organizationId}`);
const base = (owner: RecordOwner, recordType: string) => `${ownerRoot(owner)}/records/${recordType}`;

export const recordTablesApi: RecordTablesApi = {
  columns: (owner, recordType) => api.get<RecordColumns>(`${base(owner, recordType)}/columns`),
  exportFile: (owner, recordType, kind, filters) =>
    kind === "csv"
      ? api.getForBlob(`${base(owner, recordType)}/export${filters ? `?${filters}` : ""}`)
      : api.getForBlob(
        `${ownerRoot(owner)}/reports/record-list?${new URLSearchParams({ record_type: recordType, format: kind })}${filters ? `&${filters}` : ""}`,
      ),
  importFile: (owner, recordType, file, dryRun) =>
    api.postFile<RecordImportResult>(`${base(owner, recordType)}/import?dry_run=${dryRun}`, file),
  grid: (projectId, recordType, filters) =>
    api.get<RecordGridData>(`${base({ projectId }, recordType)}/grid${filters ? `?${filters}` : ""}`),
  saveRow: (projectId, recordType, code, cells, expected) =>
    api.patch<GridRow>(`${base({ projectId }, recordType)}/rows/${encodeURIComponent(code)}`, { cells, expected }),
};

/** The one-line note for columns the policy left out, or an empty string when none were. */
export function omittedColumnsNote(columns: Pick<RecordColumns, "omitted_sensitivity" | "omitted_reasons">): string {
  if (columns.omitted_sensitivity.length === 0) return "";
  const byPermission = columns.omitted_sensitivity.every((tag) => columns.omitted_reasons[tag] === "permission");
  return byPermission
    ? "Some columns holding personal data are left out: you need the permission to export personal data."
    : "Some columns holding personal data are left out by your organisation's policy.";
}
