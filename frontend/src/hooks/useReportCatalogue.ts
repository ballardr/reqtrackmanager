/**
 * Module: hooks/useReportCatalogue
 *
 * Loads the reports a caller can run for one project or organisation from the
 * core report framework's catalogue endpoint (Module 1 Phase 13). The
 * catalogue is the single source of which reports exist: it already reflects
 * module and sub-component enablement and, for an organisation, the caller's
 * report role, so callers show or hide their Reports surface from `entries`
 * alone and keep no frontend list of reports.
 *
 * A failed load is reported as `error` with no entries, so a page that merely
 * *offers* reports (the project Reports page, the Org Overview group) degrades
 * to "no reports" instead of breaking.
 */
import { useEffect, useState } from "react";

import { reportsApi, type ReportCatalogueEntry } from "../api/reports";
import { toErrorMessage } from "../context/ToastContext";

export interface ReportCatalogueState {
  /** Runnable reports; empty while loading, on error, or when none apply. */
  entries: ReportCatalogueEntry[];
  loading: boolean;
  error: string | null;
}

interface Loaded {
  key: string;
  entries: ReportCatalogueEntry[];
  error: string | null;
}

/**
 * @param scope Whether to load the project or the organisation catalogue.
 * @param id The project or organisation id; `undefined` skips loading.
 * @returns The catalogue state (never throws).
 */
export function useReportCatalogue(scope: "project" | "organization", id: string | undefined): ReportCatalogueState {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = id ? `${scope}:${id}` : null;

  useEffect(() => {
    if (!id || !key) return;
    let cancelled = false;
    (scope === "project" ? reportsApi.projectCatalogue(id) : reportsApi.orgCatalogue(id))
      .then((entries) => !cancelled && setLoaded({ key, entries, error: null }))
      .catch((err) => !cancelled && setLoaded({ key, entries: [], error: toErrorMessage(err, "Could not load reports.") }));
    return () => {
      cancelled = true;
    };
  }, [scope, id, key]);

  // Loading is derived (the loaded result is for another key, or none yet) so no effect sets state synchronously.
  const current = loaded !== null && loaded.key === key ? loaded : null;
  return { entries: current?.entries ?? [], loading: key !== null && current === null, error: current?.error ?? null };
}
