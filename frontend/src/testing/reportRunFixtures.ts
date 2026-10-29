/**
 * Module: testing/reportRunFixtures
 *
 * A background report run (`ReportRun`) with sensible defaults, for the stories of the report-run dialog, page and
 * top-bar indicator.
 */
import type { ReportRun } from "../api/reports";

/**
 * @param over Fields to change from a ready PDF run.
 * @returns A complete `ReportRun`.
 */
export function buildReportRun(over: Partial<ReportRun> = {}): ReportRun {
  return {
    id: "run-1", organization_id: "org-1", project_id: "project-1", scope: "project", layout_name: "Quarterly review",
    layout_version: 3, format: "pdf", status: "ready", created_at: "2026-10-27T01:00:00Z", started_at: "2026-10-27T01:00:05Z",
    finished_at: "2026-10-27T01:02:00Z", expires_at: "2026-11-03T01:02:00Z", output_filename: "quarterly-review.pdf",
    output_size: 2_400_000, error: null, ...over,
  };
}
