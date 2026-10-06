/**
 * Module: testing/reportFixtures
 *
 * Storybook-only builders for the core report framework's catalogue entries
 * and results (Module 1 Phase 13). They describe a synthetic, module-neutral
 * report so the generic components (viewer, parameter form, runner,
 * catalogue) are proven independent of Context & Strategy.
 */
import type { ReportCatalogueEntry, ReportResult } from "../api/reports";

/** A synthetic project-level report with one choice and one integer parameter. */
export function buildReportCatalogueEntry(overrides: Partial<ReportCatalogueEntry> = {}): ReportCatalogueEntry {
  return {
    module_key: "fixture_report_module",
    module_name: "Fixture Module",
    key: "f1",
    slug: "fixture-report",
    title: "Fixture report",
    description: "A synthetic report used to exercise the generic Reports UI.",
    scope: "project",
    path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/fixture-report",
    formats: ["json", "pdf", "csv"],
    supports_include_children: true,
    supports_project_filter: false,
    breakdown_path: null,
    projects: [],
    params: [
      { name: "rollup", type: "string", default: "weighted_average", choices: ["weighted_average", "worst_case"], minimum: null, maximum: null, description: "How values combine." },
      { name: "stale_months", type: "integer", default: 6, choices: null, minimum: 1, maximum: 120, description: "Months before an item is stale." },
    ],
    ...overrides,
  };
}

/** A synthetic collected report: two metrics, a plain table and a gap table. */
export function buildReportResult(overrides: Partial<ReportResult> = {}): ReportResult {
  return {
    key: "f1",
    title: "Fixture report",
    scope_label: "Atlas Platform",
    generated_at: "2026-10-06T09:30:00Z",
    notes: ["Covers this project only."],
    sections: [
      { key: "items", title: "Items", columns: ["Name", "Status"], rows: [["Alpha", "Open"], ["Beta", "Closed"]], note: "", gap: false },
      { key: "gaps", title: "Unowned items", columns: ["Name"], rows: [["Alpha"]], note: "Nobody owns these.", gap: true },
    ],
    metrics: [{ label: "Items", value: 2 }, { label: "Unowned", value: 1 }],
    data: null,
    eligible_projects: 1,
    ...overrides,
  };
}
