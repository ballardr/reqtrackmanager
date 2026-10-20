/**
 * Module: hooks/useLiveSearch
 *
 * The request behaviour behind the header search's live dropdown, built so the results never flicker
 * while someone types:
 *
 * 1. a debounce (300ms after the last keystroke) and no request under 2 characters;
 * 2. a new request aborts the one in flight, and a response for a query that has since changed is dropped;
 * 3. while a request is in flight the previous results stay (`pending` lets the UI dim them) and are
 *    replaced in one render when the new ones arrive: never cleared to a spinner or an empty state;
 * 4. `slow` turns true only if a request takes longer than ~250ms, so a fast one shows no spinner;
 * 5. a result already fetched for the same query, scope and fields is reused for a few minutes, so
 *    backspacing does not refetch;
 * 6. "no results" is for a completed request for the current query only (`settled`).
 *
 * `pending`, `slow` and `error` are derived from the request's identity (`key`), so a change of query
 * clears them without any state being reset. The cache lives in the hook instance (the header box), so
 * it is dropped on sign-out.
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { isAbort, SEARCH_MIN_QUERY, type SearchApi, type SearchRequest, type SearchResponse } from "../api/search";

export const LIVE_SEARCH_DEBOUNCE_MS = 300;
export const LIVE_SEARCH_SLOW_MS = 250;
export const LIVE_SEARCH_CACHE_MS = 5 * 60 * 1000;
/** Rows the dropdown asks for; lower than the page so its queries are cheaper. */
export const LIVE_SEARCH_LIMIT = 8;

export interface LiveSearchState {
  /** The latest completed response (kept while a newer request is in flight), or null before the first. */
  response: SearchResponse | null;
  /** The query text `response` answers. */
  answered: string;
  /** A request for the current query is in flight (the UI dims the kept results). */
  pending: boolean;
  /** That request has taken longer than `LIVE_SEARCH_SLOW_MS` (the UI shows a spinner). */
  slow: boolean;
  /** `response` is for the current query: only then may "no results" be shown. */
  settled: boolean;
  error: "timeout" | "rate_limited" | "failed" | null;
}

interface Internal {
  response: SearchResponse | null;
  answered: string;
  pendingKey: string | null;
  slowKey: string | null;
  failure: { key: string; kind: "timeout" | "rate_limited" | "failed" } | null;
}

/**
 * @param request The search to run for the current text (scope, project, fields); `null` when none applies.
 * @param api Injectable calls (stories pass a fake).
 */
export function useLiveSearch(request: Omit<SearchRequest, "limit" | "counts"> | null, api: SearchApi): LiveSearchState {
  const [state, setState] = useState<Internal>({ response: null, answered: "", pendingKey: null, slowKey: null, failure: null });
  const cache = useRef(new Map<string, { at: number; response: SearchResponse }>());
  const key = request ? JSON.stringify(request) : null;
  const query = request?.q.trim() ?? "";

  useEffect(() => {
    // The request is rebuilt from its serialised identity, so the effect depends on `key` alone and
    // does not re-run when the caller passes an equal object.
    const wanted = key ? (JSON.parse(key) as Omit<SearchRequest, "limit" | "counts">) : null;
    const text = wanted?.q.trim() ?? "";
    if (!key || !wanted || text.length < SEARCH_MIN_QUERY) return;
    const controller = new AbortController();
    let slowTimer: ReturnType<typeof setTimeout> | undefined;
    const debounce = setTimeout(() => {
      const cached = cache.current.get(key);
      if (cached && Date.now() - cached.at < LIVE_SEARCH_CACHE_MS) {
        setState({ response: cached.response, answered: text, pendingKey: null, slowKey: null, failure: null });
        return;
      }
      setState((s) => ({ ...s, pendingKey: key, slowKey: null, failure: null }));
      slowTimer = setTimeout(() => setState((s) => (s.pendingKey === key ? { ...s, slowKey: key } : s)), LIVE_SEARCH_SLOW_MS);
      api
        .search({ ...wanted, limit: LIVE_SEARCH_LIMIT, counts: false }, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          cache.current.set(key, { at: Date.now(), response });
          setState({ response, answered: text, pendingKey: null, slowKey: null, failure: null });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || isAbort(err)) return;
          const kind = err instanceof ApiError && err.status === 408 ? "timeout" : err instanceof ApiError && err.status === 429 ? "rate_limited" : "failed";
          setState((s) => ({ ...s, pendingKey: null, slowKey: null, failure: { key, kind } }));
        })
        .finally(() => clearTimeout(slowTimer));
    }, LIVE_SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(debounce);
      clearTimeout(slowTimer);
      controller.abort();
    };
  }, [key, api]);

  const error = state.failure && state.failure.key === key ? state.failure.kind : null;
  const pending = key !== null && state.pendingKey === key;
  return {
    response: state.response,
    answered: state.answered,
    pending,
    slow: pending && state.slowKey === key,
    settled: key !== null && state.answered === query && !pending && error === null,
    error,
  };
}
