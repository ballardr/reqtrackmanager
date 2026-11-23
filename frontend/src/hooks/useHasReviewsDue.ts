/**
 * Module: hooks/useHasReviewsDue
 *
 * Whether the signed-in person has any requirement review due, so the "My reviews due" navigation entry is shown only
 * when that page has content. Reads one row of `GET /me/reviews/due` (its total is in a header) on sign-in and on the
 * notification poll's interval, never per navigation, so the cost is one small read every half minute.
 *
 * Design decisions: unknown counts as "nothing due", so the entry never appears and disappears; a failed read keeps
 * the last known answer. The page stays reachable by its address and from notifications whatever this returns.
 */
import { useState } from "react";

import { api } from "../api/client";
import { useLoadOnChange } from "./useLoadOnChange";

/** Matches the notification bell's poll, so a review that falls due appears at the same cadence as its notification. */
const REFRESH_INTERVAL_MS = 30_000;

/**
 * @param enabled False while nobody is signed in, so no request is made.
 * @returns True once the server reports at least one review due for the current person.
 */
export function useHasReviewsDue(enabled: boolean): boolean {
  const [hasDue, setHasDue] = useState(false);

  useLoadOnChange(async () => {
    if (!enabled) return;
    try {
      const page = await api.getPage<unknown>("/api/v1/me/reviews/due?limit=1");
      setHasDue(page.total > 0);
    } catch {
      // Keep the last known answer; the page itself shows any real error.
    }
  }, [enabled], { intervalMs: REFRESH_INTERVAL_MS });

  return enabled && hasDue;
}
