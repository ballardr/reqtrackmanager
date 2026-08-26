import { GitBranch, LayoutGrid, List } from "lucide-react";

import { useUiPreference } from "../hooks/useUiPreference";

export type ViewMode = "tiles" | "list" | "tree";

/** Reads/writes a per-page tile-vs-list-vs-tree view preference, keyed
 * `view_mode:<pageKey>` in the user's `ui_preferences` bag — synced
 * server-side (see `useUiPreference`), not localStorage, so it follows
 * them across devices/browsers the same way their theme/landing-page
 * choices already do. */
export function useViewMode(pageKey: string, defaultMode: ViewMode = "tiles"): [ViewMode, (mode: ViewMode) => void] {
  const [stored, setStored] = useUiPreference<string>(`view_mode:${pageKey}`, defaultMode);
  const mode: ViewMode = stored === "tiles" || stored === "list" || stored === "tree" ? stored : defaultMode;
  return [mode, setStored];
}

/**
 * `showTreeOption` (hierarchical projects, docs/decisions.md): the tree
 * button only renders when the page's current project set actually
 * contains a parent/child relationship — a tree mode with nothing to show
 * a hierarchy for doesn't mean anything, and forcing it into every page's
 * toggle regardless would be a poor fit for pages like Favourites (a flat,
 * intentionally-curated pinboard). If the caller was on tree mode and it
 * becomes unavailable, they've already been switched back to list by the
 * page (see `ProjectListPage`/`FavouritesPage`'s own `useEffect`), so this
 * component doesn't need to handle that fallback itself.
 */
export function ViewToggle({
  mode,
  onChange,
  showTreeOption = false,
}: {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  showTreeOption?: boolean;
}) {
  return (
    <div className="row" style={{ gap: "0.25rem" }}>
      <button
        className={`btn ${mode === "tiles" ? "btn-primary" : ""}`}
        onClick={() => onChange("tiles")}
        title="Tile view"
        aria-label="Tile view"
        aria-pressed={mode === "tiles"}
      >
        <LayoutGrid size={16} />
      </button>
      <button
        className={`btn ${mode === "list" ? "btn-primary" : ""}`}
        onClick={() => onChange("list")}
        title="List view"
        aria-label="List view"
        aria-pressed={mode === "list"}
      >
        <List size={16} />
      </button>
      {showTreeOption && (
        <button
          className={`btn ${mode === "tree" ? "btn-primary" : ""}`}
          onClick={() => onChange("tree")}
          title="Tree view"
          aria-label="Tree view"
          aria-pressed={mode === "tree"}
        >
          <GitBranch size={16} />
        </button>
      )}
    </div>
  );
}
