import { GitBranch, LayoutGrid, List, Table2 } from "lucide-react";

import { useUiPreference } from "../hooks/useUiPreference";

export type ViewMode = "tiles" | "list" | "tree" | "grid";

/** Reads/writes a per-page tile-vs-list-vs-tree view preference, keyed
 * `view_mode:<pageKey>` in the user's `ui_preferences` bag — synced
 * server-side (see `useUiPreference`), not localStorage, so it follows
 * them across devices/browsers the same way their theme/landing-page
 * choices already do. */
export function useViewMode(pageKey: string, defaultMode: ViewMode = "tiles"): [ViewMode, (mode: ViewMode) => void] {
  const [stored, setStored] = useUiPreference<string>(`view_mode:${pageKey}`, defaultMode);
  const mode: ViewMode = stored === "tiles" || stored === "list" || stored === "tree" || stored === "grid" ? stored : defaultMode;
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
 *
 * `showTilesOption`: the mirror-image
 * case — a caller whose two real view modes are "tree" and "list" only
 * (`RequirementTree.tsx`'s authoring-tree vs. scanning-list toggle), where
 * a "tiles" mode means nothing at all, not just "nothing to show a
 * hierarchy for." Defaults `true` (every existing caller keeps its tiles
 * button) so this is additive, not a behaviour change for tile/list pages.
 *
 * `showGridOption`: a record list whose type has editable columns offers the bulk edit grid
 * (`RecordGrid`, "Pattern: bulk edit grid") as one more view of the same rows. Off by default.
 */
export function ViewToggle({
  mode,
  onChange,
  showTreeOption = false,
  showTilesOption = true,
  showGridOption = false,
}: {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  showTreeOption?: boolean;
  showTilesOption?: boolean;
  showGridOption?: boolean;
}) {
  return (
    <div className="row" style={{ gap: "var(--space-1)" }}>
      {showTilesOption && (
        <button
          className={`btn ${mode === "tiles" ? "btn-primary" : ""}`}
          onClick={() => onChange("tiles")}
          title="Tile view"
          aria-label="Tile view"
          aria-pressed={mode === "tiles"}
        >
          <LayoutGrid />
        </button>
      )}
      <button
        className={`btn ${mode === "list" ? "btn-primary" : ""}`}
        onClick={() => onChange("list")}
        title="List view"
        aria-label="List view"
        aria-pressed={mode === "list"}
      >
        <List />
      </button>
      {showTreeOption && (
        <button
          className={`btn ${mode === "tree" ? "btn-primary" : ""}`}
          onClick={() => onChange("tree")}
          title="Tree view"
          aria-label="Tree view"
          aria-pressed={mode === "tree"}
        >
          <GitBranch />
        </button>
      )}
      {showGridOption && (
        <button
          className={`btn ${mode === "grid" ? "btn-primary" : ""}`}
          onClick={() => onChange("grid")}
          title="Grid view"
          aria-label="Grid view"
          aria-pressed={mode === "grid"}
        >
          <Table2 />
        </button>
      )}
    </div>
  );
}
