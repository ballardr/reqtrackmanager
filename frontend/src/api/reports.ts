/**
 * Module: api/reports
 *
 * Types and calls for the core report framework's catalogue and run
 * endpoints (Module 1 Phase 12b/13). A module declares reports on the
 * backend; `GET .../report-catalogue` lists the ones the caller can run, and
 * each entry's `path` is a runnable route taking `format=json|pdf|csv` plus
 * the entry's declared parameters. Core UI addresses a report only through
 * its catalogue entry, never by a per-module URL.
 */
import { api } from "./client";

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
}

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
  formats: ("json" | "pdf" | "csv")[];
  supports_include_children: boolean;
  /** Organisation-level entries accept `project_id` to narrow the run to one project in scope. */
  supports_project_filter: boolean;
  /** For organisation-level entries: exactly the projects the caller may narrow the report to. */
  projects: { id: string; name: string }[];
  params: ReportParam[];
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
}

/** A collected report as JSON (`ReportOut`); `data` is report-specific. */
export interface ReportResult<TData = unknown> {
  key: string;
  title: string;
  scope_label: string;
  generated_at: string;
  notes: string[];
  sections: ReportSection[];
  metrics: { label: string; value: number | string }[];
  data: TData;
  /** In-scope projects with the report's sub-component enabled; 0 = nothing to report on. */
  eligible_projects: number;
}

/** Run-time values for a report: declared parameters plus framework options. */
export type ReportRunValues = Record<string, string | number | boolean | null | undefined>;

/** Builds the query string for a run; blank/unset values are omitted so the server default applies. */
export function reportQuery(format: "json" | "pdf" | "csv", values: ReportRunValues): string {
  const query = new URLSearchParams({ format });
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    query.set(name, String(value));
  }
  return query.toString();
}

export const reportsApi = {
  projectCatalogue: (projectId: string) => api.get<ReportCatalogueEntry[]>(`/api/v1/projects/${projectId}/report-catalogue`),
  orgCatalogue: (orgId: string) => api.get<ReportCatalogueEntry[]>(`/api/v1/orgs/${orgId}/report-catalogue`),
  /** Runs a report and returns it as JSON. */
  run: <TData = unknown>(entry: ReportCatalogueEntry, values: ReportRunValues) =>
    api.get<ReportResult<TData>>(`${entry.path}?${reportQuery("json", values)}`),
  /** Runs a report and returns the PDF or CSV file. */
  download: (entry: ReportCatalogueEntry, format: "pdf" | "csv", values: ReportRunValues) =>
    api.getForBlob(`${entry.path}?${reportQuery(format, values)}`),
};
