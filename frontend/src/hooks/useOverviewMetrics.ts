/**
 * Module: hooks/useOverviewMetrics
 *
 * Fetches the figures of every visible overview widget in one batched request (a hidden widget asks for
 * nothing), each in its own project scope (the widget's override, else the overview's). The server evaluates
 * identical figures once and answers a state per widget, so one slow or unreadable figure never blanks the page.
 */
import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import type { OverviewMetricResult, OverviewMetricsResponse, OverviewMetricSpec, OverviewScope, OverviewWidget } from "../api/types";
import { visibleMetricSpecs } from "../utils/overviewWidgets";

export interface OverviewMetricsState {
  /** Results by widget id; `null` until the first answer for this project. */
  results: Record<string, OverviewMetricResult> | null;
  error: string | null;
}

/** A fetched answer and the project it belongs to, so another project's figures are never shown. */
interface Fetched {
  projectId: string;
  results: Record<string, OverviewMetricResult>;
  error: string | null;
}

/**
 * @param projectId The project whose figures are read.
 * @param widgets The layout in force.
 * @param scope The overview's project scope; a widget with its own scope reads in that one.
 * @param failure The message to show when the request fails without a server message.
 */
export function useOverviewMetrics(
  projectId: string | undefined, widgets: OverviewWidget[] | null, scope: OverviewScope, failure: string,
): OverviewMetricsState {
  // The references as text, so a new layout array with the same figures does not refetch.
  const specsJson = useMemo(() => (widgets ? JSON.stringify(visibleMetricSpecs(widgets, scope)) : null), [widgets, scope]);
  const [fetched, setFetched] = useState<Fetched | null>(null);

  useEffect(() => {
    if (!projectId || specsJson === null) return undefined;
    const specs = JSON.parse(specsJson) as OverviewMetricSpec[];
    if (specs.length === 0) return undefined;
    let cancelled = false;
    api
      .post<OverviewMetricsResponse>(`/api/v1/projects/${projectId}/overview-metrics`, { metrics: specs })
      .then((body) => {
        if (!cancelled) setFetched({ projectId, results: body.results, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFetched({ projectId, results: {}, error: err instanceof ApiError ? err.message : failure });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, specsJson, failure]);

  // No visible widget needs a figure: nothing is requested and the answer is known at once.
  if (specsJson === "[]") return { results: {}, error: null };
  if (!fetched || fetched.projectId !== projectId) return { results: null, error: null };
  return { results: fetched.results, error: fetched.error };
}
