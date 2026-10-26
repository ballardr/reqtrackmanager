/**
 * Module: components/ReportLayoutPreviewPanel
 *
 * The designer's live preview: runs the draft text on the real records, as the signed-in person, and shows the
 * result without storing anything (`ReportLayoutApi.preview`).
 *
 * Responsibilities:
 * - Run on demand (a button), never on every keystroke: a run reads real data and has caps.
 * - Show a document as the server's standalone HTML page in a fully sandboxed frame (no scripts, no same-origin
 *   access, a restrictive CSP inside the page), and a table layout as capped sheets with the real row counts.
 * - Offer the scope's options with the Reports page's own form: "include child projects" for a project, the
 *   projects to include for an organisation (`ReportParamsForm`).
 * - Surface the run's warnings, its counters and any refusal (over a limit, no projects) in words.
 *
 * Design decisions: the frame's `sandbox` attribute is deliberately empty; the preview never receives a token,
 * cookie or script. The result is dropped when the text changes (`stale`) rather than shown against text it was
 * not produced from.
 */
import { useState } from "react";

import type { PreviewResult, ReportLayoutApi } from "../api/reportLayouts";
import type { ReportRunValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { ReportParamsForm } from "./ReportParamsForm";
import { ReportSectionTable } from "./ReportViewer";
import { Spinner } from "./Spinner";

/**
 * @param api The calls, bound to the layout's scope.
 * @param text The draft text view to preview.
 * @param name The title to print on the report.
 * @param disabled True while the text has problems; the button is then disabled with the reason.
 * @param projectOptions Organisation scope: the projects a run can be narrowed to.
 */
export function ReportLayoutPreviewPanel({
  api, text: draft, name, disabled, projectOptions,
}: {
  api: ReportLayoutApi;
  text: string;
  name: string;
  disabled: boolean;
  projectOptions?: { value: string; label: string }[];
}) {
  const text = useStrings().reportLayouts;
  const [values, setValues] = useState<ReportRunValues>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [produced, setProduced] = useState<{ draft: string; result: PreviewResult } | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const ids = typeof values.project_ids === "string" && values.project_ids !== "" ? values.project_ids.split(",") : undefined;
      const result = await api.preview({ text: draft, name, include_children: values.include_children === true, project_ids: ids });
      setProduced({ draft, result });
    } catch (err) {
      setProduced(null);
      setError(toErrorMessage(err, text.previewFailed));
    } finally {
      setRunning(false);
    }
  }

  const current = produced && produced.draft === draft && produced.result.ok ? produced.result : null;

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.previewHint}</p>
      <ReportParamsForm
        params={[]}
        values={values}
        onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
        supportsIncludeChildren={api.scope.kind === "project"}
        projectMultiOptions={api.scope.kind === "organization" ? projectOptions : undefined}
      />
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={disabled || running} onClick={() => void run()}>
          {text.refreshPreview}
        </button>
        {disabled && <span className="text-muted">{text.previewFixFirst}</span>}
      </div>
      {running && <Spinner />}
      {error && <div role="alert" style={{ color: "var(--color-danger)" }}>{error}</div>}
      {current && <PreviewResultView result={current} />}
    </div>
  );
}

function PreviewResultView({ result }: { result: PreviewResult }) {
  const text = useStrings().reportLayouts;
  return (
    <div className="stack">
      <span className="text-muted" role="status">{text.previewSummary(result.records_read, result.projects, result.duration_ms)}</span>
      {result.warnings.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: "1.2rem" }} aria-label="Warnings">
          {result.warnings.map((warning, index) => <li key={index} className="text-muted">{warning}</li>)}
        </ul>
      )}
      {result.html !== null && (
        <iframe className="layout-preview-frame" title={text.previewFrameTitle} sandbox="" srcDoc={result.html} />
      )}
      {result.html === null && result.sheets.length === 0 && <p className="text-muted">{text.previewNothing}</p>}
      {result.sheets.map((sheet) => (
        <ReportSectionTable
          key={sheet.name}
          section={{
            key: sheet.name, title: sheet.name, columns: sheet.columns, rows: sheet.rows, gap: false,
            note: sheet.total_rows > sheet.rows.length ? text.sheetTruncated(sheet.rows.length, sheet.total_rows) : "",
          }}
        />
      ))}
    </div>
  );
}
