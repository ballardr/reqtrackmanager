/**
 * Module: components/ReportPackRunner
 *
 * Runs one report pack from the Reports page: the pack's variable form, its saved choices, a live count of what
 * each report in the zip would include, and the download.
 *
 * Responsibilities:
 * - Show the pack's variables (`ReportVariablesForm`, the same control per variable as for a single layout) and a
 *   "Saved choices" select that fills the form from a saved set (the values this project would use, with its own
 *   overrides applied); a value typed afterwards wins.
 * - Hold the pack back (and the download) until every variable with no default has a value, so a pack is never
 *   produced for a choice nobody made.
 * - Preview, a moment after the values stop changing, how many records each report would include and which are
 *   not available here and why (nothing is stored or produced), so a wrong choice is visible before anything is sent on.
 * - Download the zip with the same values; a pack too big to produce while the person waits is queued in the
 *   background and announced with a toast (a notification says when it is ready).
 *
 * Design decisions: the counts are the *included* records, after the variables narrow them, because the point of
 * the preview is to show what a choice does. The form states that variables narrow, they do not limit what the
 * person may read. The component is stateless about the pack itself: everything comes through `ReportPackRunApi`.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
  isNothingToRun,
  PACK_ENTRY_STATUS_LABEL,
  PACK_FORMAT_LABEL,
  type PackFormat,
  type PackValues,
  type ReportPackForm,
  type ReportPackPreview,
  type ReportPackRunApi,
  type ReportPackRunBody,
} from "../api/reportPacks";
import {
  hasVariableValue,
  isAsyncRequired,
  missingVariables,
  variableDefaults,
  type VariableValue,
  type VariableValues,
} from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { REPORT_RUN_QUEUED_EVENT } from "../hooks/useReportRuns";
import { useReportTemplates } from "../hooks/useReportTemplates";
import { downloadBlob } from "../utils/download";
import { Badge } from "./Badge";
import { LabeledSelect } from "./LabeledSelect";
import { ReportVariablesForm } from "./ReportVariablesForm";
import { Spinner } from "./Spinner";

const PREVIEW_DELAY_MS = 300;

/** The chosen values as the server takes them: only variables that have a value. */
function chosen(form: ReportPackForm, values: VariableValues): PackValues {
  const out: PackValues = {};
  for (const variable of form.variables) {
    const value = values[variable.name];
    if (value !== null && value !== undefined && hasVariableValue(value)) out[variable.name] = value;
  }
  return out;
}

/** A file stem safe to offer a browser: letters and digits, everything else a dash. */
function zipName(name: string): string {
  return `${name.replace(/[^A-Za-z0-9._ -]+/g, "-").trim() || "report-pack"}.zip`;
}

/**
 * @param api The calls that run this pack.
 * @param organizationId The owning organisation (branding templates).
 * @param name The pack's name (the download's file name and the toasts).
 * @param includeChildren Project runs: also read readable child projects.
 */
export function ReportPackRunner({
  api, organizationId, name, includeChildren = false,
}: {
  api: ReportPackRunApi;
  organizationId: string;
  name: string;
  includeChildren?: boolean;
}) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const { showToast } = useToast();
  const templates = useReportTemplates(organizationId);
  const [form, setForm] = useState<ReportPackForm | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [values, setValues] = useState<VariableValues>({});
  const [setId, setSetId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [preview, setPreview] = useState<{ signature: string; result: ReportPackPreview | null; error: string | null } | null>(null);
  const [downloading, setDownloading] = useState(false);
  const hasPreviewed = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api
      .form()
      .then((loaded) => {
        if (cancelled) return;
        setForm(loaded);
        setValues(variableDefaults(loaded.variables));
      })
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, [api]);

  const missing = form ? missingVariables(form.variables, values) : [];
  const blocked = missing.length > 0;
  const body = useMemo<ReportPackRunBody | null>(() => {
    if (!form) return null;
    const out: ReportPackRunBody = { variables: chosen(form, values), include_children: includeChildren || undefined };
    if (setId) out.variable_set_id = setId;
    if (templateId) out.report_template_id = templateId;
    return out;
  }, [form, values, setId, templateId, includeChildren]);
  const signature = JSON.stringify(body);

  useEffect(() => {
    if (!body || blocked) return undefined;
    let cancelled = false;
    const timer = setTimeout(
      () => {
        hasPreviewed.current = true;
        api
          .preview(body)
          .then((result) => !cancelled && setPreview({ signature, result, error: null }))
          .catch((err) => !cancelled && setPreview({ signature, result: null, error: toErrorMessage(err, text.downloadFailed) }));
      },
      hasPreviewed.current ? PREVIEW_DELAY_MS : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [api, body, blocked, signature, text.downloadFailed]);

  function pickSet(id: string) {
    setSetId(id);
    if (!form) return;
    const set = form.sets.find((s) => s.id === id);
    // Start from the defaults, then the set's values; a value typed afterwards wins.
    setValues({ ...variableDefaults(form.variables), ...(set?.values ?? {}) });
  }

  function setVariable(variable: string, value: VariableValue | null) {
    setValues((current) => ({ ...current, [variable]: value }));
  }

  async function download() {
    if (!body) return;
    setDownloading(true);
    try {
      downloadBlob(await api.download(body), zipName(name));
      showToast(text.downloaded(name), "success");
    } catch (err) {
      if (isAsyncRequired(err)) {
        try {
          await api.queue(body);
          showToast(text.queued(name), "success");
          window.dispatchEvent(new Event(REPORT_RUN_QUEUED_EVENT));
        } catch (queueErr) {
          showToast(toErrorMessage(queueErr, text.queueFailed), "error");
        }
      } else {
        showToast(isNothingToRun(err) ? text.nothingToRun : toErrorMessage(err, text.downloadFailed), "error");
      }
    } finally {
      setDownloading(false);
    }
  }

  if (loadFailed) return <p className="text-muted" role="alert">{text.runnerLoadFailed}</p>;
  if (!form) return <Spinner />;

  const current = preview?.signature === signature ? preview : null;
  const result = current?.result ?? preview?.result ?? null;
  const settling = !blocked && current === null;
  const canDownload = !blocked && !downloading && result !== null && result.entries.some((e) => e.status === "included");

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-end" }}>
        {form.sets.length > 0 && (
          <LabeledSelect help={strings.help.reportPackSavedSet}
            label={text.savedSetLabel}
            value={setId}
            onChange={pickSet}
            options={form.sets.map((s) => ({ value: s.id, label: s.name }))}
            placeholder={text.savedSetPlaceholder}
          />
        )}
        <ReportVariablesForm variables={form.variables} values={values} onChange={setVariable} />
        {templates.length > 0 && (
          <LabeledSelect help={strings.help.reportBrandingTemplate}
            label={text.brandingLabel}
            value={templateId}
            onChange={setTemplateId}
            options={templates.map((t) => ({ value: t.id, label: t.name }))}
            placeholder="No template"
          />
        )}
      </div>
      {form.sets.find((s) => s.id === setId)?.warnings.map((warning) => (
        <p key={warning} role="status" className="text-muted" style={{ margin: 0 }}>{warning}</p>
      ))}
      <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{text.variablesNotLimits}</p>
      {blocked && (
        <p role="status" className="text-muted" style={{ margin: 0 }}>
          {strings.reportVariables.needValues(form.variables.filter((v) => missing.includes(v.name)).map((v) => v.label))}
        </p>
      )}
      {current?.error && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{current.error}</p>}
      {!blocked && result === null && settling && <Spinner label={text.previewing} />}
      {!blocked && result !== null && (
        <div className="stack" aria-busy={settling} style={settling ? { opacity: 0.6 } : undefined}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>{text.whatsIncludedHeading}</h3>
          <table aria-label={text.whatsIncludedHeading}>
            <thead>
              <tr>
                <th>{text.positionHeading}</th>
                <th>{text.reportHeading}</th>
                <th>{text.formatHeading}</th>
                <th>{text.statusHeading}</th>
                <th>{text.recordsHeading}</th>
              </tr>
            </thead>
            <tbody>
              {result.entries.map((entry) => (
                <tr key={entry.position}>
                  <td>{entry.position}</td>
                  <td>
                    <span className="stack" style={{ gap: 0 }}>
                      <span>{entry.title}</span>
                      {entry.reason && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{entry.reason}</span>}
                    </span>
                  </td>
                  <td>{PACK_FORMAT_LABEL[entry.format as PackFormat] ?? entry.format}</td>
                  <td><Badge tone={entry.status === "included" ? "accent" : "warning"}>{PACK_ENTRY_STATUS_LABEL[entry.status]}</Badge></td>
                  <td>{entry.status === "included" ? entry.records : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-muted" style={{ margin: 0 }}>
            {text.totalRecords(result.total_records)}
            {result.not_available > 0 && ` · ${text.notAvailableCount(result.not_available)}`}
          </p>
          {result.warnings.map((warning) => (
            <p key={warning} role="status" className="text-muted" style={{ margin: 0 }}>{warning}</p>
          ))}
        </div>
      )}
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={!canDownload} onClick={() => void download()}>
          {text.downloadZip}
        </button>
      </div>
    </div>
  );
}
