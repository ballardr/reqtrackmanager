/**
 * Module: modules/architecture/useFolderActions
 *
 * The folder actions of a System Architecture list, as rows of the page's one actions menu (`ListPageLayout`'s `menuItems`)
 * and the dialogs they open: "New folder" (under the chosen folder) and, once a folder is chosen, "Edit folder" (rename and
 * move) and "Delete folder" (its records and sub-folders move up; nothing else is deleted). With no folder chosen there is no
 * Edit or Delete row, never a disabled one (docs/ux-style-guide.md, "Pattern: page actions menu").
 * It knows no record: the caller supplies the folders, the calls and the choice. Every change reads the folders again
 * through `onChanged`; where the person may not change folders (`calls` is null) the hook offers nothing.
 */
import { useMemo, useState, type ReactNode } from "react";

import type { ActionMenuItem } from "../../components/ActionMenu";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import type { projectFolderApi } from "./api";
import { FolderFormModal, type FolderValues } from "./FolderFormModal";
import type { ArchitectureFolder } from "./types";

type FolderCalls = ReturnType<typeof projectFolderApi>;

/**
 * @param noun What the folders organise, in the plural (`elements`), for the messages.
 * @param folders The owner's folders of the list's kind.
 * @param calls The create, update and delete calls for those folders, or null where the person may not change folders.
 * @param selectedPath The chosen folder's path, or "" for no filter.
 * @param onSelect Called with a folder's path (or "" to clear the filter) when the choice follows a rename or a delete.
 * @param onChanged Called after a folder was made, changed or deleted, so the caller reads the folders (and the list) again.
 * @returns `menuItems` (rows for the page's actions menu) and `dialogs` (the form and the confirmation, rendered once).
 */
export function useFolderActions({
  noun, folders, calls, selectedPath, onSelect, onChanged,
}: {
  noun: string;
  folders: ArchitectureFolder[];
  calls: FolderCalls | null;
  selectedPath: string;
  onSelect: (path: string) => void;
  onChanged: () => void;
}): { menuItems: ActionMenuItem[]; dialogs: ReactNode } {
  const { showToast } = useToast();
  const [editing, setEditing] = useState<ArchitectureFolder | "new" | null>(null);
  const [deleting, setDeleting] = useState<ArchitectureFolder | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const chosen = folders.find((f) => f.path === selectedPath) ?? null;

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

  const menuItems = useMemo<ActionMenuItem[]>(() => {
    if (!calls) return [];
    const items: ActionMenuItem[] = [{ key: "folder:new", label: "New folder", onSelect: () => { setFormError(null); setEditing("new"); } }];
    if (chosen) {
      items.push(
        { key: "folder:edit", label: "Edit folder", onSelect: () => { setFormError(null); setEditing(chosen); } },
        { key: "folder:delete", label: "Delete folder", danger: true, onSelect: () => setDeleting(chosen) },
      );
    }
    return items;
  }, [calls, chosen]);

  const dialogs: ReactNode = (
    <>
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
    </>
  );
  return { menuItems, dialogs };
}
