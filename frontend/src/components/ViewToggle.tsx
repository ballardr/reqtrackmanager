import { LayoutGrid, List } from "lucide-react";
import { useState } from "react";

export type ViewMode = "tiles" | "list";

const STORAGE_PREFIX = "view:";

/** Reads/writes a per-page tile-vs-list view preference, persisted in localStorage. */
export function useViewMode(pageKey: string, defaultMode: ViewMode = "tiles"): [ViewMode, (mode: ViewMode) => void] {
  const [mode, setModeState] = useState<ViewMode>(() => {
    const stored = localStorage.getItem(STORAGE_PREFIX + pageKey);
    return stored === "tiles" || stored === "list" ? stored : defaultMode;
  });

  function setMode(next: ViewMode) {
    setModeState(next);
    localStorage.setItem(STORAGE_PREFIX + pageKey, next);
  }

  return [mode, setMode];
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
