import { useCallback, useSyncExternalStore } from "react";

/**
 * Tracks whether the viewport is at or below `breakpointPx` wide, kept live via `matchMedia` so a resize or
 * orientation change is reflected immediately.
 *
 * `FilterPanel`'s collapsible body uses it: on wide viewports it renders expanded with no toggle, and below the
 * mobile breakpoint it defaults to collapsed. That is a viewport-driven default, not a persisted per-user
 * preference (`useUiPreference`, `CollapsibleSection`).
 */
export function useNarrowViewport(breakpointPx: number): boolean {
  const query = `(max-width: ${breakpointPx}px)`;
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches);
}
