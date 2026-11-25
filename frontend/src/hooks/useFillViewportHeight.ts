/**
 * Module: hooks/useFillViewportHeight
 *
 * The height an element needs to reach the bottom of the browser window from where it starts, so a working surface
 * (the diagram canvas) is wholly in view without scrolling the page.
 *
 * Responsibilities: subtract the element's offset from the top of the page and a bottom gap from the window height,
 * never go below a minimum, and stay live as the window or the content above the element resizes (`ResizeObserver`
 * on the document body, `resize` on the window).
 *
 * Design decisions: the offset is `top + scrollY`, so scrolling does not change the answer. The caller passes the
 * element as state (a callback ref), as in `useTallerThanViewport`. Measure a wrapper whose height does not come from
 * the result, or the answer chases itself. Below the minimum the page scrolls.
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
