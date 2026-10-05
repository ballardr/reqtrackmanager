/**
 * Module: hooks/useRequestSequence
 *
 * Guards a list page against out-of-order responses. A filter or search
 * change starts a new load while the previous one may still be in flight;
 * if the older, slower response lands last it would overwrite the newer
 * results. Each load calls `begin()` and applies its response only if
 * `isLatest()` is still true when it arrives.
 *
 * Shared by every filterable list page (2026-10-05) instead of each
 * keeping its own request-id ref.
 */
import { useCallback, useRef } from "react";

/**
 * @returns `begin`, which starts a request and returns an `isLatest()`
 *   check: true only while no later `begin()` call has been made.
 */
export function useRequestSequence(): () => () => boolean {
  const latest = useRef(0);
  return useCallback(() => {
    const id = ++latest.current;
    return () => id === latest.current;
  }, []);
}
