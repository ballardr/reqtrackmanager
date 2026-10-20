/**
 * Module: hooks/useLoadOnChange
 *
 * Runs a page's `load` function when it mounts and whenever the listed
 * values change: the "fetch this page's data" effect, written once. `load` is
 * read through `useLatest`, so it may close over any state without being a
 * dependency (and without the stale-closure risk of omitting it), and only
 * `deps` decide when a reload happens. The caller's own `reload()` (called after
 * a mutation) is unaffected. With `intervalMs` it also reloads on a timer (polling).
 *
 * Keeping the effect here, rather than at each call site, is deliberate: a
 * page's `load` sets state once its response arrives, and the shared effect
 * simply starts it, instead of every page re-implementing an effect that
 * synchronises with nothing but its own state setters.
 */
import { useEffect } from "react";

import { useLatest } from "./useLatest";

/**
 * @param load Starts the load; may return a promise (ignored, so it must handle its own errors).
 * @param deps Plain values (ids, filters, a sort state) whose change should trigger another load; compared by their JSON form.
 * @param options `intervalMs`: also reload every this many milliseconds while mounted.
 */
export function useLoadOnChange(load: () => unknown, deps: readonly unknown[], options: { intervalMs?: number } = {}): void {
  const latestLoad = useLatest(load);
  const key = JSON.stringify(deps);
  const { intervalMs } = options;
  useEffect(() => {
    void latestLoad.current();
    if (intervalMs === undefined) return;
    const timer = setInterval(() => void latestLoad.current(), intervalMs);
    return () => clearInterval(timer);
  }, [key, latestLoad, intervalMs]);
}
