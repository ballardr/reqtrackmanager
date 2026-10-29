/**
 * Module: components/ReportRunner
 *
 * Runs one catalogue report and shows it: the generated
 * parameter form, the on-screen result, and the downloads in every format the report offers. Everything
 * that is the same for every report lives here; only the result view varies,
 * and that is resolved generically (`getReportView`) so core never imports a
 * module's own view, falling back to `ReportViewer` for a report with none.
 *
 * Responsibilities:
 * - With `showResult` off (the record list's download dialog) only configure and download: nothing is run for
 *   the screen, so no result is fetched or shown.
 * - Own the run values (declared parameters, `include_children`) and re-run
 *   the report when they change (debounced, so typing in a text parameter
 *   does not fire a request per keystroke; the first run is immediate).
 * - Keep the previous result visible and marked busy while a re-run is in
 *   flight, and discard a response that a newer run has superseded.
 * - For an organisation-wide report, offer a "Project" picker (`project_id`)
 *   listing the catalogue entry's `projects`: exactly the ones the report
 *   accepts for this caller, so the picker never offers one that would fail.
 *   An organisation-wide custom report (run once per project) offers a
 *   "Projects" selector (`project_ids`) over the same list instead.
 * - For a custom report with run-time variables, show their form (`ReportVariablesForm`) and send the chosen values
 *   as the `variables` run value; a variable with no default and no value holds the run back until it has one, so
 *   the report is never produced for a choice the person has not made.
 * - Offer an optional branding template for downloads (it never
 *   changes the on-screen result) and download through the shared
 *   `ReportExportButton`, with a toast on success or failure. Downloads send
 *   the same values as the screen so a file never silently widens the view
 *   (style guide: "report export trigger").
 *
 * Dependencies: `api/reports`, `modules/registry` (view lookup only).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
  isAsyncRequired,
  reportsApi,
  type ReportCatalogueEntry,
  type ReportFileKind,
  type ReportMetric,
  type ReportResult,
  type ReportRunValues,
  type VariableValue,
  type VariableValues,
  missingVariables,
  variableDefaults,
  variablesRunValue,
} from "../api/reports";
import { REPORT_RUN_QUEUED_EVENT } from "../hooks/useReportRuns";
import { useReportTemplates } from "../hooks/useReportTemplates";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { getReportView } from "../modules/registry";
import { downloadBlob } from "../utils/download";
import { describeReportLink, reportLinkResolver } from "../utils/reportLinks";
import { LabeledSelect } from "./LabeledSelect";
import { ReportFigureProjectsDialog } from "./ReportFigureProjectsDialog";
import { ReportExportButton } from "./ReportExportButton";
import { ReportParamsForm } from "./ReportParamsForm";
import { ReportVariablesForm } from "./ReportVariablesForm";
import { ReportViewer, type ReportFigureActionResolver } from "./ReportViewer";
import { Spinner } from "./Spinner";
import { useStrings } from "../context/TerminologyContext";

const RERUN_DELAY_MS = 300;

/** The formats that lay the report out as a document, the only ones a branding template applies to. */
const DOCUMENT_KINDS: readonly ReportFileKind[] = ["pdf", "docx", "html", "odt"];

function initialValues(entry: ReportCatalogueEntry): ReportRunValues {
  const values: ReportRunValues = {};
  for (const param of entry.params) if (param.default !== null && param.default !== undefined) values[param.name] = param.default;
  if (entry.supports_include_children) values.include_children = false;
  return values;
}

/**
 * @param entry The catalogue entry to run.
 * @param scope What it runs against: a project or an organisation, by id.
 * @param organizationId The owning organisation, for the branding template list.
 * @param focusSection A section key to scroll to once the report has loaded (a figure's "see the gap table" link).
 * @param showResult False to show the parameters and the download menu without running the report on screen.
 */
/** How a download kind is named to the user (toasts). */
const DOWNLOAD_NAME: Record<ReportFileKind, string> = {
  pdf: "PDF", docx: "Word file", csv: "CSV", html: "HTML page", xlsx: "Excel workbook",
  odt: "OpenDocument text file", ods: "OpenDocument spreadsheet",
};

export function ReportRunner({
  entry, scope, organizationId, focusSection, showResult = true,
}: {
  entry: ReportCatalogueEntry;
  scope: { kind: "project" | "organization"; id: string };
  /** The owning organisation (branding templates); `undefined` offers no template choice. */
  organizationId: string | undefined;
  focusSection?: string;
  showResult?: boolean;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [values, setValues] = useState<ReportRunValues>(() => initialValues(entry));
  const [variableValues, setVariableValues] = useState<VariableValues>(() => variableDefaults(entry.variables));
  const [result, setResult] = useState<ReportResult | null>(null);
  // The run that last finished, by the values it ran with; the report is busy whenever the current values differ.
  const [settled, setSettled] = useState<{ signature: string; error: string | null } | null>(null);
  const templates = useReportTemplates(organizationId);
  const [templateId, setTemplateId] = useState("");
  // What a download uses when none is chosen: the layout's own template, else the organisation's default.
  const defaultTemplate = templates.find((t) => t.id === entry.report_template_id) ?? templates.find((t) => t.is_default);
  const [openedFigure, setOpenedFigure] = useState<{ metric: ReportMetric; values: ReportRunValues } | null>(null);
  const hasRun = useRef(false);
  // What a run sends: the report's values plus the chosen variables (as JSON); a report with none is unchanged.
  const runValues = useMemo<ReportRunValues>(
    () => ({ ...values, variables: variablesRunValue(entry.variables, variableValues) }),
    [values, entry.variables, variableValues],
  );
  const signature = JSON.stringify(runValues);
  const missing = missingVariables(entry.variables, variableValues);
  const blocked = missing.length > 0;

  useEffect(() => {
    if (blocked || !showResult) return undefined;
    let cancelled = false;
    const timer = setTimeout(
      () => {
        hasRun.current = true;
        reportsApi
          .run(entry, runValues)
          .then((next) => {
            if (cancelled) return;
            setResult(next);
            setSettled({ signature, error: null });
          })
          .catch((err) => !cancelled && setSettled({ signature, error: toErrorMessage(err, "Could not run this report.") }));
      },
      hasRun.current ? RERUN_DELAY_MS : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [entry, blocked, showResult, runValues, signature]);

  // Bring a linked-to gap table into view once its report has rendered (once per arrival, not per re-run).
  const scrolled = useRef<string | null>(null);
  useEffect(() => {
    if (!focusSection || result === null || scrolled.current === focusSection) return;
    const target = document.getElementById(`report-section-${focusSection}`);
    if (target) {
      scrolled.current = focusSection;
      target.scrollIntoView({ block: "start" });
    }
  }, [focusSection, result]);

  function setValue(name: string, value: string | number | boolean | null) {
    setValues((current) => ({ ...current, [name]: value }));
  }

  function setVariable(name: string, value: VariableValue | null) {
    setVariableValues((current) => ({ ...current, [name]: value }));
  }

  async function download(kind: ReportFileKind) {
    const name = DOWNLOAD_NAME[kind];
    const fileValues = DOCUMENT_KINDS.includes(kind) ? { ...runValues, report_template_id: templateId } : runValues;
    try {
      const blob = await reportsApi.download(entry, kind, fileValues);
      // A table layout of several sheets comes back as a zip of CSV files, whatever `csv` was asked for.
      downloadBlob(blob, `${entry.slug}.${blob.type === "application/zip" ? "zip" : kind}`);
      showToast(`Downloaded ${entry.title} (${name}).`, "success");
    } catch (err) {
      if (isAsyncRequired(err)) {
        // Too big to produce while the person waits: the same request goes to the background queue and a
        // notification says when the file is ready.
        try {
          await reportsApi.queueRun(entry, kind, fileValues);
          showToast(strings.reportRuns.queued(entry.title), "success");
          window.dispatchEvent(new Event(REPORT_RUN_QUEUED_EVENT));
        } catch (queueErr) {
          showToast(toErrorMessage(queueErr, strings.reportRuns.queueFailed), "error");
        }
        return;
      }
      showToast(toErrorMessage(err, `Could not generate the ${name} for ${entry.title}.`), "error");
    }
  }

  const busy = showResult && !blocked && settled?.signature !== signature;
  const error = busy ? null : (settled?.error ?? null);
  const view = getReportView(entry.module_key, entry.key);
  // Figures link to pages in a project report; an organisation report spans projects, so a figure opens a
  // per-project list instead (and only if the server offers the breakdown).
  const projectLinks = reportLinkResolver(scope, entry.module_key);
  const figureAction: ReportFigureActionResolver | undefined = projectLinks
    ? (metric) => (metric.link ? { to: projectLinks(metric.link), hint: describeReportLink(metric.link, metric.label) } : undefined)
    : entry.breakdown_path
      ? (metric) =>
        metric.link
          ? { onActivate: () => setOpenedFigure({ metric, values }), hint: `Shows which projects make up "${metric.label}"` }
          : undefined
      : undefined;
  const View = view?.component;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: "var(--space-5)" }}>
        <ReportParamsForm
          params={entry.params}
          values={values}
          onChange={setValue}
          hidden={view?.ownedParams}
          supportsIncludeChildren={entry.supports_include_children}
          projectOptions={entry.supports_project_filter ? entry.projects.map((p) => ({ value: p.id, label: p.name })) : undefined}
          projectMultiOptions={
            entry.supports_project_multi_filter && entry.projects.length > 0
              ? entry.projects.map((p) => ({ value: p.id, label: p.name }))
              : undefined
          }
        />
        <ReportVariablesForm variables={entry.variables} values={variableValues} onChange={setVariable} />
        <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-4)" }}>
          {templates.length > 0 && (
            <LabeledSelect help={strings.help.reportBrandingTemplate}
              label="Branding template"
              value={templateId}
              onChange={setTemplateId}
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
              placeholder={defaultTemplate ? strings.reports.templateDefaultNamed(defaultTemplate.name) : strings.reports.noTemplate}
            />
          )}
          {!blocked && <ReportExportButton onDownload={download} kinds={entry.formats.filter((f): f is ReportFileKind => f !== "json")} />}
        </div>
      </div>
      {error && (
        <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>
          {error}
        </p>
      )}
      {blocked && (
        <p role="status" className="text-muted" style={{ margin: 0 }}>
          {strings.reportVariables.needValues(entry.variables.filter((v) => missing.includes(v.name)).map((v) => v.label))}
        </p>
      )}
      {!blocked && result === null && busy && !error && <Spinner label="Running report…" />}
      {!blocked && result !== null && (
        <div className="stack" aria-busy={busy} style={busy ? { opacity: 0.6 } : undefined}>
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            {result.scope_label} · generated {new Date(result.generated_at).toLocaleString()}
          </p>
          {View ? (
            <View entry={entry} result={result} scope={scope} values={values} onValueChange={setValue} figureAction={figureAction} />
          ) : (
            <ReportViewer result={result} figureAction={figureAction} />
          )}
        </div>
      )}
      {openedFigure && (
        <ReportFigureProjectsDialog
          entry={entry}
          values={openedFigure.values}
          metric={openedFigure.metric}
          onClose={() => setOpenedFigure(null)}
        />
      )}
    </div>
  );
}
