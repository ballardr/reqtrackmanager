/**
 * Module: components/ReportRunDialog
 *
 * The dialog a "report ready" notification opens (and the page `/report-runs/:id` shows): one background report
 * of the person's own, with what its state allows. A ready one offers Download; one still waiting or being prepared
 * says so and refreshes itself; an expired or failed one says why and offers **Generate again**, which queues a fresh
 * run of the same request as the person is now (`POST /report-runs/{id}/again`) and does not revive the old file.
 *
 * Design decisions: Download is a click, not an automatic download on open, because browsers block a download
 * that no click started and the dialog is needed for the other states anyway. Generating again says it is a fresh run
 * and, once queued, whether the layout was edited since. Nothing here names a report or a module.
 *
 * Dependencies: `reportRunsApi`, `Modal`, `Badge`, `useToast`.
 */
import { useEffect, useState } from "react";

import { reportRunsApi, type ReportRun, type ReportRunAgain } from "../api/reports";
import { REPORT_RUN_STATUS_LABEL, REPORT_RUN_STATUS_TONE } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { REPORT_RUN_QUEUED_EVENT } from "../hooks/useActiveReportRuns";
import { downloadBlob } from "../utils/download";
import { formatFileSize } from "../utils/formatFileSize";
import { Badge } from "./Badge";
import { Modal } from "./Modal";

const POLL_MS = 4000;

/**
 * @param initial The run to show (as loaded by the caller).
 * @param onClose Closes the dialog.
 */
export function ReportRunDialog({ initial, onClose }: { initial: ReportRun; onClose: () => void }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [run, setRun] = useState<ReportRun>(initial);
  const [again, setAgain] = useState<ReportRunAgain | null>(null);
  const [busy, setBusy] = useState(false);
  const inProgress = run.status === "queued" || run.status === "running";

  useEffect(() => {
    if (!inProgress) return undefined;
    const timer = setInterval(() => {
      reportRunsApi.get(run.id).then(setRun).catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [inProgress, run.id]);

  async function download() {
    try {
      const blob = await reportRunsApi.download(run.id);
      downloadBlob(blob, run.output_filename ?? `${run.layout_name}.${run.format}`);
      showToast(strings.reportRuns.downloaded(run.layout_name), "success");
    } catch (err) {
      showToast(toErrorMessage(err, strings.reportRuns.downloadFailed), "error");
      reportRunsApi.get(run.id).then(setRun).catch(() => undefined);
    }
  }

  async function generateAgain() {
    setBusy(true);
    try {
      setAgain(await reportRunsApi.again(run.id));
      window.dispatchEvent(new Event(REPORT_RUN_QUEUED_EVENT));
    } catch (err) {
      showToast(toErrorMessage(err, strings.reportRuns.generateAgainFailed), "error");
    } finally {
      setBusy(false);
    }
  }

  const when = (iso: string) => new Date(iso).toLocaleString();
  const size = run.status === "ready" && run.output_size !== null ? formatFileSize(run.output_size) : null;

  return (
    <Modal title={run.layout_name} onClose={onClose}>
      <div className="stack">
        <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
          <Badge tone={REPORT_RUN_STATUS_TONE[run.status]}>{REPORT_RUN_STATUS_LABEL[run.status]}</Badge>
          <span className="text-muted">{strings.reportRuns.formatLine(run.format.toUpperCase(), size)}</span>
          <span className="text-muted">{strings.reportRuns.requested(when(run.created_at))}</span>
        </div>
        {again ? (
          <div role="status" className="stack" style={{ gap: "var(--space-1)" }}>
            <p style={{ margin: 0 }}>{strings.reportRuns.generatedAgain}</p>
            {again.definition_changed && <p className="text-muted" style={{ margin: 0 }}>{strings.reportRuns.generatedAgainChanged}</p>}
          </div>
        ) : (
          <>
            {run.status === "ready" && (
              <>
                <p style={{ margin: 0 }}>{run.expires_at ? strings.reportRuns.readyUntil(when(run.expires_at)) : null}</p>
                <div className="row">
                  <button className="btn btn-primary" onClick={download}>{strings.reportRuns.download}</button>
                </div>
              </>
            )}
            {inProgress && <p style={{ margin: 0 }}>{strings.reportRuns.preparing}</p>}
            {(run.status === "expired" || run.status === "failed") && (
              <>
                <p style={{ margin: 0 }} role={run.status === "failed" ? "alert" : undefined}>
                  {run.status === "expired" ? strings.reportRuns.expired : strings.reportRuns.failed(run.error ?? "")}
                </p>
                <p className="text-muted" style={{ margin: 0 }}>{strings.reportRuns.generateAgainNote}</p>
                <div className="row">
                  <button className="btn btn-primary" onClick={generateAgain} disabled={busy}>
                    {busy ? strings.reportRuns.generatingAgain : strings.reportRuns.generateAgain}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
