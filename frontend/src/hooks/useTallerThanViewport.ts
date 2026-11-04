/**
 * Module: hooks/useTallerThanViewport
 *
 * Reports whether an element is taller than the browser window, kept live as the element or the window resizes.
 *
 * Responsibilities: observe the element's height (`ResizeObserver`) and the window's (`resize`), and return the
 * comparison. Used by the report designer to offer a second Save at the foot only when the content is long enough
 * that the foot is out of sight.
 *
 * Design decisions: the caller passes the element as state (a callback ref), so an element rendered later or
 * conditionally is picked up when it mounts. Measure an element that does not contain whatever the result shows or
 * hides, or the answer can flip back and forth around the threshold.
 */
import { useEffect, useState } from "react";

/**
 * @param element The element to measure, or `null` before it exists.
 * @returns `true` while the element is taller than the window; `false` when it is not or there is no element.
 */
export function useTallerThanViewport(element: HTMLElement | null): boolean {
  const [taller, setTaller] = useState(false);

  useEffect(() => {
    if (!element) return;
    const measure = () => setTaller(element.offsetHeight > window.innerHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [element]);

  return element !== null && taller;
}
