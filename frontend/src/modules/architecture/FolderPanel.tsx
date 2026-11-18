/**
 * Module: modules/architecture/FolderPanel
 *
 * The folder tree of a System Architecture list, drawn in the list's filter panel: choose a folder to show only its
 * records (and, with "Include sub-folders", those below it), and make, edit and delete folders there. Folders organise a
 * list and mean nothing else, so the panel is optional: with no folders it shows only "New folder".
 *
 * - Choosing a folder is the list's filter (`selectedPath`, kept in the page address by the caller); choosing it again
 *   clears the choice.
 * - "New folder" opens `FolderFormModal` with the chosen folder as the parent; "Edit folder" renames or moves the chosen
 *   one; "Delete folder" confirms, then moves the folder's records and sub-folders up (nothing else is deleted).
 * - Every change reads the folders again through `onChanged`, and the list reloads when records moved.
 *
 * It knows no record: the caller supplies the folders, the calls and the choice. Where the person may not change
 * folders the server answers 403 and the panel shows it as a toast.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FilterCheckbox, FilterField } from "../../components/FilterPanel";
import { TreeView } from "../../components/TreeView";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import type { projectFolderApi } from "./api";
import { FolderFormModal, type FolderValues } from "./FolderFormModal";
import { buildFolderTree, type FolderNode } from "./folderTree";
import { ARCHITECTURE_HELP } from "./help";
import type { ArchitectureFolder } from "./types";

type FolderCalls = ReturnType<typeof projectFolderApi>;

/**
 * @param noun What the folders organise, in the plural (`elements`), for the headings and messages.
 * @param folders The owner's folders of the list's kind.
 * @param calls The create, update and delete calls for those folders.
 * @param selectedPath The chosen folder's path, or "" for no filter.
 * @param onSelect Called with a folder's path (or "" to clear the filter).
 * @param includeSub Whether the filter includes the chosen folder's sub-folders.
 * @param onIncludeSubChange Called when the Include sub-folders box changes.
 * @param onChanged Called after a folder was made, changed or deleted, so the caller reads the folders (and the list) again.
 */
export function FolderPanel({
  noun, folders, calls, selectedPath, onSelect, includeSub, onIncludeSubChange, onChanged,
}: {
  noun: string;
  folders: ArchitectureFolder[];
  calls: FolderCalls | null;
  selectedPath: string;
  onSelect: (path: string) => void;
  includeSub: boolean;
  onIncludeSubChange: (next: boolean) => void;
  onChanged: () => void;
}) {
  const { showToast } = useToast();
  const [editing, setEditing] = useState<ArchitectureFolder | "new" | null>(null);
  const [deleting, setDeleting] = useState<ArchitectureFolder | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const chosen = folders.find((f) => f.path === selectedPath) ?? null;
  const hasChildren = chosen !== null && folders.some((f) => f.parent_id === chosen.id);

  async function save(values: FolderValues) {
    if (!calls || !editing) return;
    setFormError(null);
    try {
      if (editing === "new") {
        await calls.create(values);
        showToast("Folder created.");
      } else {
        const updated = await calls.update(editing.id, values);
        showToast("Folder saved.");
        // A renamed or moved folder changes the path of the choice, so keep the choice on the same folder.
        if (chosen && chosen.id === editing.id) onSelect(updated.path);
        else if (chosen && selectedPath.startsWith(`${editing.path}/`)) onSelect(`${updated.path}${selectedPath.slice(editing.path.length)}`);
      }
      setEditing(null);
      onChanged();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save the folder."));
    }
  }

  async function remove(folder: ArchitectureFolder) {
    setDeleting(null);
    if (!calls) return;
    try {
      await calls.remove(folder.id);
      showToast("Folder deleted.");
      if (selectedPath === folder.path || selectedPath.startsWith(`${folder.path}/`)) onSelect(folder.parent_id ? (folders.find((f) => f.id === folder.parent_id)?.path ?? "") : "");
      onChanged();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete the folder."), "error");
    }
  }

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
        {folders.length > 0 && (
          <TreeView
            nodes={buildFolderTree(folders)} nodeLabel={(node) => node.folder.name} renderNode={row} emptyText="No folders yet."
          />
        )}
        {hasChildren && (
          <FilterCheckbox label="Include sub-folders" help={ARCHITECTURE_HELP.folderIncludeSub} checked={includeSub} onChange={onIncludeSubChange} />
        )}
        {calls && (
          <div className="row" style={{ gap: "var(--space-2)" }}>
            <button type="button" className="btn btn-sm" onClick={() => { setFormError(null); setEditing("new"); }}>New folder</button>
            {chosen && (
              <>
                <button type="button" className="btn btn-sm" onClick={() => { setFormError(null); setEditing(chosen); }}>Edit folder</button>
                <button type="button" className="btn btn-sm" onClick={() => setDeleting(chosen)}>Delete folder</button>
              </>
            )}
          </div>
        )}
      </div>
      {editing && (
        <FolderFormModal
          initial={editing === "new" ? undefined : editing} folders={folders} defaultParentId={chosen?.id ?? null} error={formError}
          onCancel={() => { setEditing(null); setFormError(null); }} onSave={save}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete folder ${deleting.name}?`}
          message={`Its ${noun} and sub-folders move up to its parent folder. Nothing else is deleted.`}
          confirmLabel="Delete" onCancel={() => setDeleting(null)} onConfirm={() => void remove(deleting)}
        />
      )}
    </FilterField>
  );
}
