/**
 * Module: hooks/useLatest
 *
 * Returns a ref whose `.current` is always the value from the most recent render, for async code that outlives
 * the render that started it (a list page's post-mutation `reload()` runs after an `await` and must build its
 * request from the current filters, not those captured before the await).
 *
 * Updated in an effect (React disallows ref writes during render), so call this before any effect that reads it in
 * the same commit: effects run in declaration order.
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
