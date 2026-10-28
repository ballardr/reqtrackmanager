/**
 * Module: components/ReportRunsPanel
 *
 * The caller's background custom reports: reports too big to produce while they wait, with their state
 * (waiting, preparing, ready, failed, expired), a Download for a ready one and Delete file (or Cancel while
 * waiting). Shown in the Reports dialog (`ReportsDialog`); renders nothing until the person has a background
 * report, unless `emptyMessage` is given. Only the person who asked for a report sees it.
 *
 * Deleting a file is a Tier 1 confirmation (the report can be produced again); every action ends in a toast.
 */
import { useState } from "react";

import { reportRunsApi, type ReportRun } from "../api/reports";
import { REPORT_RUN_STATUS_LABEL, REPORT_RUN_STATUS_TONE } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { useReportRuns } from "../hooks/useReportRuns";
import { downloadBlob } from "../utils/download";
import { formatFileSize } from "../utils/formatFileSize";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";

/**
 * @param organizationId Show only the runs of this organisation (the page's own); omit for all.
 * @param emptyMessage Shown instead of nothing when there are no background reports.
 */
export function ReportRunsPanel({ organizationId, emptyMessage }: { organizationId?: string; emptyMessage?: string }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const { runs, error, reload } = useReportRuns(organizationId);
  const [removing, setRemoving] = useState<ReportRun | null>(null);

  if (runs.length === 0 && !error) return emptyMessage ? <p className="text-muted">{emptyMessage}</p> : null;

  async function download(run: ReportRun) {
    try {
      const blob = await reportRunsApi.download(run.id);
      downloadBlob(blob, run.output_filename ?? `${run.layout_name}.${run.format}`);
      showToast(strings.reportRuns.downloaded(run.layout_name), "success");
    } catch (err) {
      showToast(toErrorMessage(err, strings.reportRuns.downloadFailed), "error");
      reload();
    }
  }

  async function remove(run: ReportRun) {
    setRemoving(null);
    try {
      await reportRunsApi.remove(run.id);
      showToast(run.status === "queued" ? strings.reportRuns.cancelled : strings.reportRuns.removed, "success");
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
    reload();
  }

  return (
    <section className="stack" aria-label={strings.reportRuns.listLabel}>
      <h2 style={{ margin: 0 }}>{strings.reportRuns.title}</h2>
      <p className="text-muted" style={{ margin: 0 }}>{strings.reportRuns.description}</p>
      {error && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{error}</p>}
      <table>
        <thead>
          <tr>
            <th>{strings.reportRuns.reportHeading}</th>
            <th>{strings.reportRuns.formatHeading}</th>
            <th>{strings.reportRuns.statusHeading}</th>
            <th>{strings.reportRuns.requestedHeading}</th>
            <th>{strings.reportRuns.expiresHeading}</th>
            <th><span className="sr-only">{strings.reportRuns.actionsHeading}</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                {run.layout_name}
                {run.status === "ready" && run.output_size !== null && (
                  <span className="text-muted"> · {formatFileSize(run.output_size)}</span>
                )}
                {run.status === "failed" && run.error && (
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>{run.error}</div>
                )}
              </td>
              <td>{run.format.toUpperCase()}</td>
              <td><Badge tone={REPORT_RUN_STATUS_TONE[run.status]}>{REPORT_RUN_STATUS_LABEL[run.status]}</Badge></td>
              <td>{new Date(run.created_at).toLocaleString()}</td>
              <td>{run.status === "ready" && run.expires_at ? new Date(run.expires_at).toLocaleString() : strings.reportRuns.notReady}</td>
              <td>
                <div className="row" style={{ justifyContent: "flex-end", gap: "var(--space-2)" }}>
                  {run.status === "ready" && (
                    <button className="btn" aria-label={`${strings.reportRuns.download} ${run.layout_name}`} onClick={() => download(run)}>
                      {strings.reportRuns.download}
                    </button>
                  )}
                  {(run.status === "ready" || run.status === "queued") && (
                    <button
                      className="btn"
                      aria-label={`${run.status === "queued" ? strings.reportRuns.cancel : strings.reportRuns.remove} ${run.layout_name}`}
                      onClick={() => setRemoving(run)}
                    >
                      {run.status === "queued" ? strings.reportRuns.cancel : strings.reportRuns.remove}
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {removing && (
        <ConfirmDialog
          title={removing.status === "queued" ? strings.reportRuns.cancel : strings.reportRuns.remove}
          message={strings.reportRuns.confirmRemove(removing.layout_name, removing.status === "queued")}
          confirmLabel={removing.status === "queued" ? strings.reportRuns.cancel : strings.reportRuns.remove}
          onConfirm={() => remove(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}
    </section>
  );
}
