/**
 * Module: modules/architecture/FolderPanel
 *
 * The folder tree of a System Architecture list, drawn in the list's filter panel: choose a folder to show only its
 * records (and, with "Include sub-folders", those below it). Folders organise a list and mean nothing else, so the panel
 * is optional: with no folders it shows only a line saying so. Making, editing and deleting folders are rows of the
 * page's actions menu (`useFolderActions`), not buttons here.
 *
 * - Choosing a folder is the list's filter (`selectedPath`, kept in the page address by the caller); choosing it again
 *   clears the choice.
 *
 * It knows no record: the caller supplies the folders and the choice.
 */
import { FilterCheckbox, FilterField } from "../../components/FilterPanel";
import { TreeView } from "../../components/TreeView";
import { buildFolderTree, type FolderNode } from "./folderTree";
import { ARCHITECTURE_HELP } from "./help";
import type { ArchitectureFolder } from "./types";

/**
 * @param folders The owner's folders of the list's kind.
 * @param selectedPath The chosen folder's path, or "" for no filter.
 * @param onSelect Called with a folder's path (or "" to clear the filter).
 * @param includeSub Whether the filter includes the chosen folder's sub-folders.
 * @param onIncludeSubChange Called when the Include sub-folders box changes.
 */
export function FolderPanel({
  folders, selectedPath, onSelect, includeSub, onIncludeSubChange,
}: {
  folders: ArchitectureFolder[];
  selectedPath: string;
  onSelect: (path: string) => void;
  includeSub: boolean;
  onIncludeSubChange: (next: boolean) => void;
}) {
  const chosen = folders.find((f) => f.path === selectedPath) ?? null;
  const hasChildren = chosen !== null && folders.some((f) => f.parent_id === chosen.id);

  function row(node: FolderNode) {
    const active = node.folder.path === selectedPath;
    return (
      <button
        type="button" aria-pressed={active} aria-label={`Folder ${node.folder.name}`}
        onClick={() => onSelect(active ? "" : node.folder.path)}
        className="row"
        style={{
          gap: "var(--space-2)", flexWrap: "nowrap", border: "none", background: active ? "var(--color-surface-alt)" : "transparent",
          color: "inherit", cursor: "pointer", padding: "var(--space-1) var(--space-2)", borderRadius: "var(--radius-sm, 4px)",
          fontWeight: active ? 600 : undefined, textAlign: "left",
        }}
      >
        <span>{node.folder.name}</span>
        <span className="text-muted">{node.folder.record_count}</span>
      </button>
    );
  }

  return (
    <FilterField label="Folders" help={ARCHITECTURE_HELP.folderFilter}>
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <TreeView
          nodes={buildFolderTree(folders)} nodeLabel={(node) => node.folder.name} renderNode={row} emptyText="No folders yet. Use New folder in the actions menu."
        />
        {hasChildren && (
          <FilterCheckbox label="Include sub-folders" help={ARCHITECTURE_HELP.folderIncludeSub} checked={includeSub} onChange={onIncludeSubChange} />
        )}
      </div>
    </FilterField>
  );
}
