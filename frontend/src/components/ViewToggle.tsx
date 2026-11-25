import { GitBranch, LayoutGrid, List, Table2 } from "lucide-react";

import { useUiPreference } from "../hooks/useUiPreference";

export type ViewMode = "tiles" | "list" | "tree" | "grid";

/** Reads and writes a per-page tile, list or tree view preference, keyed `view_mode:<pageKey>` in the user's
 * `ui_preferences` bag, synced server-side (see `useUiPreference`) so it follows the person across devices. */
export function useViewMode(pageKey: string, defaultMode: ViewMode = "tiles"): [ViewMode, (mode: ViewMode) => void] {
  const [stored, setStored] = useUiPreference<string>(`view_mode:${pageKey}`, defaultMode);
  const mode: ViewMode = stored === "tiles" || stored === "list" || stored === "tree" || stored === "grid" ? stored : defaultMode;
  return [mode, setStored];
}

/**
 * `showTreeOption` (hierarchical projects, docs/decisions.md): the tree button renders only when the page's current
 * project set contains a parent/child relationship, since a tree mode with nothing to show a hierarchy for means nothing
 * (and a curated flat pinboard such as Favourites has none). A page on tree mode when it becomes unavailable switches
 * back to list itself (see `ProjectListPage`/`FavouritesPage`).
 *
 * `showTilesOption`: false for a caller whose two real view modes are "tree" and "list" only
 * (`RequirementTree.tsx`'s authoring tree versus scanning list), where tiles mean nothing. Defaults `true`.
 *
 * `showGridOption`: a record list whose type has editable columns offers the bulk edit grid (`RecordGrid`, "Pattern: bulk
 * edit grid") as one more view of the same rows. Off by default.
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
