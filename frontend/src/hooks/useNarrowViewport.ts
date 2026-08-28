import { useEffect, useState } from "react";

/**
 * Tracks whether the viewport is currently at or below `breakpointPx` wide,
 * kept live via `matchMedia` (not just read once at mount) so a resize or
 * orientation change is reflected immediately.
 *
 * `FilterPanel`'s collapsible filter body (2026-08 UX audit roadmap) is the
 * motivating caller: on desktop/wide viewports it must render as if always
 * expanded with no visible toggle, and only below the layout's existing
 * mobile breakpoint should it default to collapsed with a toggle to expand
 * — that's a viewport-driven default, not a per-user persisted preference
 * (`useUiPreference`/`CollapsibleSection`'s own model), so it needs its own
 * small hook rather than reusing either of those.
 */
export function useNarrowViewport(breakpointPx: number): boolean {
  const query = `(max-width: ${breakpointPx}px)`;
  const [isNarrow, setIsNarrow] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setIsNarrow(mql.matches);
    const listener = (event: MediaQueryListEvent) => setIsNarrow(event.matches);
    mql.addEventListener("change", listener);
    return () => mql.removeEventListener("change", listener);
  }, [query]);

  return isNarrow;
}
