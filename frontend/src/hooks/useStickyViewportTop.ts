/**
 * Module: hooks/useStickyViewportTop
 *
 * Publishes the distance between the top of the window and where a sticky column currently starts, as a CSS custom
 * property on the column's container, so the column's `max-height` can be "the window less where it starts" at every
 * scroll position instead of only once it is stuck.
 *
 * Responsibilities: measure the container's top edge, never less than the column's own sticky offset (where it stops
 * moving), write it to `--sticky-viewport-top` (pixels) and keep it live on scroll, window resize and a size change
 * of the page.
 *
 * Design decisions: the value is written straight to the element's style, never to React state, so a scroll causes no
 * render. Updates are coalesced in `requestAnimationFrame` and the scroll listener is passive. The sticky offset is
 * read from the column's computed `top`, so the stylesheet is its one source. Until the first measurement the
 * stylesheet's fallback (the stuck offset) applies. The column's height does not feed back into its top edge (a
 * flex container aligned to the start), so the measurement cannot chase itself.
 */
import { useEffect } from "react";

/** The custom property the hook writes on the container, in pixels. */
export const STICKY_VIEWPORT_TOP_PROPERTY = "--sticky-viewport-top";

/**
 * @param container The element whose top edge is where the sticky column starts, or `null` before it exists.
 * @param column The sticky column; its computed `top` is the offset at which it stops moving. `null` before it exists.
 */
export function useStickyViewportTop(container: HTMLElement | null, column: HTMLElement | null): void {
  useEffect(() => {
    if (!container || !column) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const stuckAt = parseFloat(getComputedStyle(column).top) || 0;
      const top = Math.max(container.getBoundingClientRect().top, stuckAt);
      container.style.setProperty(STICKY_VIEWPORT_TOP_PROPERTY, `${Math.round(top)}px`);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const observer = new ResizeObserver(schedule);
    observer.observe(document.body);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer.disconnect();
      container.style.removeProperty(STICKY_VIEWPORT_TOP_PROPERTY);
    };
  }, [container, column]);
}
