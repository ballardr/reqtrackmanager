/**
 * Module: hooks/useLatest
 *
 * Returns a ref whose `.current` is always the value from the most recent
 * render. For async code that outlives the render that started it — e.g. a
 * list page's post-mutation `reload()`, which runs after an `await` and
 * would otherwise build its request from the filters as they were before
 * that await, then (being the newest request) overwrite results for
 * filters the user has changed since.
 *
 * Updated in an effect (not during render, which React disallows for
 * refs), so call this *before* any effect that reads it in the same
 * commit — effects run in declaration order.
 */
import { useEffect, useRef, type RefObject } from "react";

/**
 * @param value The value to track.
 * @returns A ref holding the latest committed `value`.
 */
export function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  });
  return ref;
}
