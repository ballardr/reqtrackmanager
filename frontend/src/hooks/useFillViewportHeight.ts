/**
 * Module: hooks/useFillViewportHeight
 *
 * The height an element needs to reach the bottom of the browser window from where it starts, so a working surface
 * (the diagram canvas) is wholly in view without scrolling the page.
 *
 * Responsibilities: measure the element's offset from the top of the page, subtract it and a bottom gap from the window
 * height, never go below a minimum, and keep the answer live as the window or the content above the element changes
 * size (`ResizeObserver` on the document body, `resize` on the window).
 *
 * Design decisions: the offset is taken from the page (`top + scrollY`), not the viewport, so scrolling does not
 * change the answer. The caller passes the element as state (a callback ref), as in `useTallerThanViewport`. Measure a
 * wrapper that does not take its height from the result's own content, or the answer can chase itself. Where the
 * window is shorter than the minimum, the minimum wins and the page scrolls.
 */
import { useEffect, useState } from "react";

/**
 * @param element The element to measure, or `null` before it exists.
 * @param minHeight The smallest height to return, in pixels.
 * @param bottomGap Space to leave below the element, in pixels.
 * @returns The height in pixels, or `minHeight` while there is no element.
 */
export function useFillViewportHeight(element: HTMLElement | null, minHeight: number, bottomGap = 16): number {
  const [height, setHeight] = useState(minHeight);

  useEffect(() => {
    if (!element) return;
    const measure = () => {
      const top = element.getBoundingClientRect().top + window.scrollY;
      setHeight(Math.max(minHeight, Math.floor(window.innerHeight - top - bottomGap)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [element, minHeight, bottomGap]);

  return element === null ? minHeight : height;
}
