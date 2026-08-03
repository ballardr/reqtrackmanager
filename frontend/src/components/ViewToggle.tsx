import { LayoutGrid, List } from "lucide-react";

import { useUiPreference } from "../hooks/useUiPreference";

export type ViewMode = "tiles" | "list";

/** Reads/writes a per-page tile-vs-list view preference, keyed
 * `view_mode:<pageKey>` in the user's `ui_preferences` bag — synced
 * server-side (see `useUiPreference`), not localStorage, so it follows
 * them across devices/browsers the same way their theme/landing-page
 * choices already do. */
export function useViewMode(pageKey: string, defaultMode: ViewMode = "tiles"): [ViewMode, (mode: ViewMode) => void] {
  const [stored, setStored] = useUiPreference<string>(`view_mode:${pageKey}`, defaultMode);
  const mode: ViewMode = stored === "tiles" || stored === "list" ? stored : defaultMode;
  return [mode, setStored];
}

export function ViewToggle({ mode, onChange }: { mode: ViewMode; onChange: (mode: ViewMode) => void }) {
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
    </div>
  );
}
