/**
 * Module: components/ReportRunner
 *
 * Runs one catalogue report and shows it (Module 1 Phase 13): the generated
 * parameter form, the on-screen result, and PDF/CSV downloads. Everything
 * that is the same for every report lives here; only the result view varies,
 * and that is resolved generically (`getReportView`) so core never imports a
 * module's own view, falling back to `ReportViewer` for a report with none.
 *
 * Responsibilities:
 * - Own the run values (declared parameters, `include_children`) and re-run
 *   the report when they change (debounced, so typing in a text parameter
 *   does not fire a request per keystroke; the first run is immediate).
 * - Keep the previous result visible and marked busy while a re-run is in
 *   flight, and discard a response that a newer run has superseded.
 * - For an organisation-wide report, offer a "Project" picker (`project_id`)
 *   listing the catalogue entry's `projects`: exactly the ones the report
 *   accepts for this caller, so the picker never offers one that would fail.
 * - Offer an optional branding template for downloads (PDF only; it never
 *   changes the on-screen result) and download through the shared
 *   `ReportExportButton`, with a toast on success or failure. Downloads send
 *   the same values as the screen so a file never silently widens the view
 *   (style guide: "report export trigger").
 *
 * Dependencies: `api/reports`, `modules/registry` (view lookup only).
 */
import { useEffect, useRef, useState } from "react";

import { reportsApi, type ReportCatalogueEntry, type ReportResult, type ReportRunValues } from "../api/reports";
import { api } from "../api/client";
import type { ReportTemplate } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { getReportView } from "../modules/registry";
import { downloadBlob } from "../utils/download";
import { LabeledSelect } from "./LabeledSelect";
import { ReportExportButton } from "./ReportExportButton";
import { ReportParamsForm } from "./ReportParamsForm";
import { ReportViewer } from "./ReportViewer";
import { Spinner } from "./Spinner";

const RERUN_DELAY_MS = 300;

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
 */
export function ReportRunner({
  entry, scope, organizationId,
}: {
  entry: ReportCatalogueEntry;
  scope: { kind: "project" | "organization"; id: string };
  organizationId: string;
}) {
  const { showToast } = useToast();
  const [values, setValues] = useState<ReportRunValues>(() => initialValues(entry));
  const [result, setResult] = useState<ReportResult | null>(null);
  // The run that last finished, by the values it ran with; the report is busy whenever the current values differ.
  const [settled, setSettled] = useState<{ signature: string; error: string | null } | null>(null);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const hasRun = useRef(false);
  const signature = JSON.stringify(values);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(
      () => {
        hasRun.current = true;
        reportsApi
          .run(entry, values)
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
  }, [entry, values, signature]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<ReportTemplate[]>(`/api/v1/orgs/${organizationId}/report-templates`)
      .then((list) => !cancelled && setTemplates(list))
      .catch(() => !cancelled && setTemplates([]));
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  function setValue(name: string, value: string | number | boolean | null) {
    setValues((current) => ({ ...current, [name]: value }));
  }

  async function download(kind: "pdf" | "csv") {
    try {
      const blob = await reportsApi.download(entry, kind, kind === "pdf" ? { ...values, report_template_id: templateId } : values);
      downloadBlob(blob, `${entry.slug}.${kind}`);
      showToast(`Downloaded ${entry.title} (${kind.toUpperCase()}).`, "success");
    } catch (err) {
      showToast(toErrorMessage(err, `Could not generate the ${kind.toUpperCase()} for ${entry.title}.`), "error");
    }
  }

  const busy = settled?.signature !== signature;
  const error = busy ? null : (settled?.error ?? null);
  const view = getReportView(entry.module_key, entry.key);
  const View = view?.component;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: "1rem" }}>
        <ReportParamsForm
          params={entry.params}
          values={values}
          onChange={setValue}
          hidden={view?.ownedParams}
          supportsIncludeChildren={entry.supports_include_children}
          projectOptions={entry.supports_project_filter ? entry.projects.map((p) => ({ value: p.id, label: p.name })) : undefined}
        />
        <div className="row" style={{ alignItems: "flex-end", gap: "0.75rem" }}>
          {templates.length > 0 && (
            <LabeledSelect
              label="Branding template (PDF)"
              value={templateId}
              onChange={setTemplateId}
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
              placeholder="No template"
            />
          )}
          <ReportExportButton onDownload={download} />
        </div>
      </div>
      {error && (
        <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>
          {error}
        </p>
      )}
      {result === null && busy && !error && <Spinner label="Running report…" />}
      {result !== null && (
        <div className="stack" aria-busy={busy} style={busy ? { opacity: 0.6 } : undefined}>
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            {result.scope_label} · generated {new Date(result.generated_at).toLocaleString()}
          </p>
          {View ? (
            <View entry={entry} result={result} scope={scope} values={values} onValueChange={setValue} />
          ) : (
            <ReportViewer result={result} />
          )}
        </div>
      )}
    </div>
  );
}
