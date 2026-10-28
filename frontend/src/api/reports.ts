/**
 * Module: api/reports
 *
 * Types and calls for the core report framework's catalogue and run
 * endpoints. A module declares reports on the
 * backend; `GET .../report-catalogue` lists the ones the caller can run, and
 * each entry's `path` is a runnable route taking `format=json|pdf|csv` plus
 * the entry's declared parameters. Core UI addresses a report only through
 * its catalogue entry, never by a per-module URL.
 */
import { ApiError, api } from "./client";
import type { ReportRunStatus } from "./types";

export type ReportParamType = "string" | "integer" | "boolean" | "date" | "uuid";

/** One declared report parameter (`ReportParamOut`). */
export interface ReportParam {
  name: string;
  type: ReportParamType;
  default: string | number | boolean | null;
  choices: (string | number)[] | null;
  minimum: number | null;
  maximum: number | null;
  description: string;
  /** Declared control label; empty falls back to a humanised `name`. */
  label?: string;
  /** Declared labels keyed by choice value; a choice without one is humanised. */
  choice_labels?: Record<string, string> | null;
}

/**
 * The file formats a record list or module report can be downloaded in (the JSON form is the on-screen run).
 * A custom table report's `csv` is a zip of one CSV per sheet when it has several sheets.
 */
export type ReportDownloadKind = "pdf" | "docx" | "csv";

/**
 * Every file format a catalogue report may offer: the downloads above plus a custom report's HTML page, Excel workbook
 * and OpenDocument text (`odt`) and spreadsheet (`ods`) files.
 */
export type ReportFileKind = ReportDownloadKind | "html" | "xlsx" | "odt" | "ods";

/** One runnable report (`ReportCatalogueEntryOut`). */
export interface ReportCatalogueEntry {
  module_key: string;
  module_name: string;
  key: string;
  slug: string;
  title: string;
  description: string;
  scope: "project" | "organization";
  /** Route with the project/organisation id already substituted. */
  path: string;
  formats: ("json" | ReportFileKind)[];
  supports_include_children: boolean;
  /** Organisation-level entries accept `project_id` to narrow the run to one project in scope. */
  supports_project_filter: boolean;
  /**
   * An organisation-wide custom report is run once per project; it accepts `project_ids` (comma-separated) to
   * choose which of `projects` are included (none chosen means every one of them).
   */
  supports_project_multi_filter: boolean;
  /** Organisation entries: the per-project figures endpoint (`ReportBreakdownOut`); `null` for project entries. */
  breakdown_path: string | null;
  /** For organisation-level entries: exactly the projects the caller may narrow the report to (or choose among). */
  projects: { id: string; name: string }[];
  params: ReportParam[];
  /** A custom report's run-time variables (its run form); empty for a module report, which declares `params`. */
  variables: ReportVariable[];
  /** What the picker filters on: a table layout is a `sheet`. */
  kind: "report" | "sheet";
  /** Where the picker files it (the effective folder path: a placement, else the author's, else the default). */
  folder: string;
  /** The stable name placements use (`report:<module>.<key>` or `layout:<id>`). */
  placement_key: string;
  /** The record types the report names or reads (a record list offers the reports that use its type). */
  record_types: string[];
}

/** A custom report layout's run-time variable as the run form shows it (`ReportVariableOut`). */
export interface ReportVariable {
  name: string;
  type: "text" | "number" | "date" | "bool" | "enum";
  label: string;
  /** Takes a list of values. */
  multiple: boolean;
  /** What the form starts with (a date's `today` is already the person's own day); `null` when the person must choose. */
  default: VariableValue | null;
  /** The values on offer; `null` for free input. */
  options: string[] | null;
  /** The record field the options come from. */
  source: { record_type: string; field: string } | null;
}

/** One variable's value: a single value, or a list for a variable that takes several. */
export type VariableValue = string | number | boolean | string[] | number[];

/** The values of a report's variables by name; absent or `null` means not chosen yet. */
export type VariableValues = Record<string, VariableValue | null>;

/** The form's starting values: each variable's default. */
export function variableDefaults(variables: ReportVariable[]): VariableValues {
  return Object.fromEntries(variables.map((v) => [v.name, v.default]));
}

/** Whether a variable has a usable value (a list needs at least one entry; a blank is not a value). */
export function hasVariableValue(value: VariableValue | null | undefined): boolean {
  if (value === null || value === undefined || value === "") return false;
  return !(Array.isArray(value) && value.length === 0);
}

/** The names of the variables that still need a value before the report can run. */
export function missingVariables(variables: ReportVariable[], values: VariableValues): string[] {
  return variables.filter((v) => !hasVariableValue(values[v.name])).map((v) => v.name);
}

/**
 * The `variables` run value: the chosen values as JSON (the framework sends it as the `variables` query
 * parameter), omitted when the report has no variables so its request is unchanged.
 */
export function variablesRunValue(variables: ReportVariable[], values: VariableValues): string | undefined {
  if (variables.length === 0) return undefined;
  const chosen = Object.fromEntries(variables.filter((v) => hasVariableValue(values[v.name])).map((v) => [v.name, values[v.name]]));
  return JSON.stringify(chosen);
}

/** One table of a report (`ReportSectionOut`). */
export interface ReportSection {
  key: string;
  title: string;
  columns: string[];
  rows: string[][];
  note: string;
  /** Lists problems to fix. */
  gap: boolean;
  /** `false` for a table that only exists for the PDF/CSV exports; the screen skips it. */
  screen?: boolean;
}

/**
 * Where a headline figure leads (`ReportLinkOut`): one of the module's own
 * project pages (`module`, `target` = page path, `query` = its filters) or
 * another report of the module (`report`, `target` = slug, `section` = a gap
 * table to scroll to). Route-neutral; `utils/reportLinks` makes it a URL.
 */
export interface ReportLink {
  kind: "module" | "report";
  target: string;
  query: Record<string, string>;
  section: string | null;
}

/** One headline figure (`ReportMetricOut`). */
export interface ReportMetric {
  label: string;
  value: number | string;
  /** A non-zero value is a problem to fix. */
  gap?: boolean;
  /** Heading the figure sits under in a pack that combines several reports. */
  group?: string | null;
  /** Where clicking the figure leads; absent for figures with no sensible destination. */
  link?: ReportLink | null;
}

/** A collected report as JSON (`ReportOut`); `data` is report-specific. */
export interface ReportResult<TData = unknown> {
  key: string;
  title: string;
  scope_label: string;
  generated_at: string;
  notes: string[];
  sections: ReportSection[];
  metrics: ReportMetric[];
  data: TData;
  /** In-scope projects with the report's sub-component enabled; 0 = nothing to report on. */
  eligible_projects: number;
}

/** One project's headline figures in an organisation report's breakdown (`ReportBreakdownProjectOut`). */
export interface ReportBreakdownProject {
  project_id: string;
  project_name: string;
  metrics: ReportMetric[];
}

/** An organisation report's figures per project (`ReportBreakdownOut`). */
export interface ReportBreakdown {
  generated_at: string;
  projects: ReportBreakdownProject[];
  /** More projects were in scope than were evaluated. */
  truncated: boolean;
}

/** Run-time values for a report: declared parameters plus framework options. */
export type ReportRunValues = Record<string, string | number | boolean | null | undefined>;

/** Builds the query string for a run; blank/unset values are omitted so the server default applies. */
export function reportQuery(format: "json" | ReportFileKind, values: ReportRunValues): string {
  const query = new URLSearchParams({ format });
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    query.set(name, String(value));
  }
  return query.toString();
}

/** One of the caller's background runs of a custom report (`ReportRunOut`). */
export interface ReportRun {
  id: string;
  organization_id: string;
  project_id: string | null;
  scope: "project" | "organization";
  layout_name: string;
  layout_version: number;
  format: string;
  status: ReportRunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
  output_filename: string | null;
  output_size: number | null;
  error: string | null;
}

/** The `detail.code` of the 409 a file run answers when it is too big to produce while the person waits. */
export const ASYNC_REQUIRED = "async_required";

/** Whether `err` is the answer that asks for the report to be prepared in the background. */
export function isAsyncRequired(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.detail === "object" &&
    err.detail !== null &&
    (err.detail as { code?: unknown }).code === ASYNC_REQUIRED
  );
}

export const reportsApi = {
  projectCatalogue: (projectId: string) => api.get<ReportCatalogueEntry[]>(`/api/v1/projects/${projectId}/report-catalogue`),
  orgCatalogue: (orgId: string) => api.get<ReportCatalogueEntry[]>(`/api/v1/orgs/${orgId}/report-catalogue`),
  /** Runs a report and returns it as JSON. */
  run: <TData = unknown>(entry: ReportCatalogueEntry, values: ReportRunValues) =>
    api.get<ReportResult<TData>>(`${entry.path}?${reportQuery("json", values)}`),
  /** An organisation report's figures evaluated per project (for the "which projects?" list). */
  breakdown: (entry: ReportCatalogueEntry, values: ReportRunValues) => {
    if (!entry.breakdown_path) throw new Error("This report has no per-project breakdown.");
    return api.get<ReportBreakdown>(`${entry.breakdown_path}?${reportQuery("json", values)}`);
  },
  /** Runs a report and returns the PDF, Word (DOCX) or CSV file. */
  download: (entry: ReportCatalogueEntry, format: ReportFileKind, values: ReportRunValues) =>
    api.getForBlob(`${entry.path}?${reportQuery(format, values)}`),
  /**
   * Queues a custom report to be produced in the background (the entry's `run` route becomes `runs`).
   * `values` are the same run values as a download: `include_children`, `project_ids` (comma-separated) and
   * `report_template_id`.
   */
  queueRun: (entry: ReportCatalogueEntry, format: ReportFileKind, values: ReportRunValues) => {
    const body: Record<string, unknown> = { format };
    if (values.include_children) body.include_children = true;
    if (typeof values.project_ids === "string" && values.project_ids) body.project_ids = values.project_ids.split(",");
    if (values.report_template_id) body.report_template_id = values.report_template_id;
    if (typeof values.variables === "string" && values.variables) body.variables = JSON.parse(values.variables);
    return api.post<ReportRun>(entry.path.replace(/\/run$/, "/runs"), body);
  },
};

/** The caller's own background runs. */
export const reportRunsApi = {
  list: (organizationId?: string) =>
    api.get<ReportRun[]>(`/api/v1/report-runs${organizationId ? `?organization_id=${organizationId}` : ""}`),
  download: (id: string) => api.getForBlob(`/api/v1/report-runs/${id}/download`),
  /** Deletes the stored file (or cancels a waiting run); returns the run as it now is. */
  remove: (id: string) => api.delete<ReportRun>(`/api/v1/report-runs/${id}`),
};
