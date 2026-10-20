import { useCallback, useSyncExternalStore } from "react";

/**
 * Tracks whether the viewport is currently at or below `breakpointPx` wide,
 * kept live via `matchMedia` (not just read once at mount) so a resize or
 * orientation change is reflected immediately.
 *
 * `FilterPanel`'s collapsible filter body is the
 * motivating caller: on desktop/wide viewports it must render as if always
 * expanded with no visible toggle, and only below the layout's existing
 * mobile breakpoint should it default to collapsed with a toggle to expand
 * — that's a viewport-driven default, not a per-user persisted preference
 * (`useUiPreference`/`CollapsibleSection`'s own model), so it needs its own
 * small hook rather than reusing either of those.
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
