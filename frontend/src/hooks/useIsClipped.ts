/**
 * Module: hooks/useIsClipped
 *
 * Reports whether an element's text is cut off (an ellipsis or a line clamp is hiding some of it), so a full-text
 * tooltip is shown only when it tells the person something they cannot already see. Shared by `CellText` and by the
 * summary of a closed picker (`TreeSelect`, `MultiSelectDropdown`).
 *
 * Measures after every render (a changed text or line limit) and whenever the element resizes. Browser-only (uses
 * `ResizeObserver`).
 */
import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from "react";

/**
 * Tracks whether the referenced element clips its content.
 *
 * @returns The ref to attach to the element, and whether its content is currently clipped.
 */
export function useIsClipped<T extends HTMLElement>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [clipped, setClipped] = useState(false);

  const measure = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    // One pixel of slack: sub-pixel rounding makes an exactly fitting text read as one pixel over.
    setClipped(element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1);
  }, []);

  // After every render: the text or the line limit may have changed (setting the same value again does not re-render).
  useLayoutEffect(measure);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  return [ref, clipped];
}
