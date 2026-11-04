/**
 * Module: hooks/useActiveReportRuns
 *
 * The caller's own background reports that are waiting or being prepared, for the top-bar indicator
 * (`ReportRunsIndicator`). While any is in progress it asks again every few seconds; with none it asks only
 * rarely (a report queued from another tab or by an MCP client still shows up), and it reloads at once when a
 * report is queued from the report runner (`REPORT_RUN_QUEUED_EVENT`). A failed load keeps the last known list: an
 * indicator that cannot reach the server must not look like "nothing is running".
 */
import { useCallback, useEffect, useState } from "react";

import { reportRunsApi, type ReportRun } from "../api/reports";
import { useLatest } from "./useLatest";

/** Dispatched on `window` after a report is queued, so the indicator shows it without waiting for a poll. */
export const REPORT_RUN_QUEUED_EVENT = "reqtrack:report-run-queued";
const BUSY_POLL_MS = 4000;
const IDLE_POLL_MS = 60_000;

/**
 * @returns The caller's runs that are waiting or being prepared (oldest first), and a `reload` function.
 */
export function useActiveReportRuns(): { runs: ReportRun[]; reload: () => void } {
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const busy = runs.length > 0;
  const latestReload = useLatest(reload);

  useEffect(() => {
    let cancelled = false;
    reportRunsApi
      .list({ active: true })
      .then((next) => !cancelled && setRuns([...next].reverse()))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tick]);

  useEffect(() => {
    const timer = setInterval(() => latestReload.current(), busy ? BUSY_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(timer);
  }, [busy, latestReload]);

  useEffect(() => {
    const onQueued = () => latestReload.current();
    window.addEventListener(REPORT_RUN_QUEUED_EVENT, onQueued);
    return () => window.removeEventListener(REPORT_RUN_QUEUED_EVENT, onQueued);
  }, [latestReload]);

  return { runs, reload };
}
