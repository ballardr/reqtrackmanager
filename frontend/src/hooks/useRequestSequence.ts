/**
 * Module: hooks/useRequestSequence
 *
 * Guards a list page against out-of-order responses. A filter or search change starts a new load while the
 * previous one may still be in flight; a slower, older response landing last would overwrite the newer results.
 * Each load calls `begin()` and applies its response only if `isLatest()` is still true when it arrives.
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
