/**
 * Module: hooks/useReportRuns
 *
 * Loads the caller's own background custom report runs and keeps them current: while any run is waiting or
 * being prepared it asks again every few seconds, and it reloads at once when a run is queued from the report
 * runner (`REPORT_RUN_QUEUED_EVENT`). Once nothing is in progress it stops asking.
 *
 * A failed load is reported as `error` with the last known runs, so the panel degrades instead of breaking.
 */
import { useCallback, useEffect, useState } from "react";

import { reportRunsApi, type ReportRun } from "../api/reports";
import { toErrorMessage } from "../context/ToastContext";

/** Dispatched on `window` after a report is queued, so the panel shows it without waiting for a poll. */
export const REPORT_RUN_QUEUED_EVENT = "reqtrack:report-run-queued";
const POLL_MS = 4000;

export interface ReportRunsState {
  runs: ReportRun[];
  loading: boolean;
  error: string | null;
  /** Reloads the list now. */
  reload: () => void;
}

/**
 * @param organizationId Restrict the list to this organisation; `undefined` lists the caller's runs everywhere.
 * @returns The runs (newest first) and a `reload` function.
 */
export function useReportRuns(organizationId?: string): ReportRunsState {
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const busy = runs.some((run) => run.status === "queued" || run.status === "running");

  useEffect(() => {
    let cancelled = false;
    reportRunsApi
      .list(organizationId)
      .then((next) => {
        if (cancelled) return;
        setRuns(next);
        setError(null);
      })
      .catch((err) => !cancelled && setError(toErrorMessage(err, "Could not load your background reports.")))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [organizationId, tick]);

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, reload]);

  useEffect(() => {
    window.addEventListener(REPORT_RUN_QUEUED_EVENT, reload);
    return () => window.removeEventListener(REPORT_RUN_QUEUED_EVENT, reload);
  }, [reload]);

  return { runs, loading, error, reload };
}
