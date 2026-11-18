/**
 * Module: modules/architecture/MoveToFolderDialog
 *
 * Moves the records chosen in a list into one folder (or back to the top level): the "Move to folder" action of the
 * three lists. The folder is chosen from the owner's folders of the list's kind; saving runs the move and the caller
 * reloads the list.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { TreeSelectField } from "../../components/TreeSelectField";
import { ARCHITECTURE_HELP } from "./help";
import { folderSelectNodes } from "./folderTree";
import type { ArchitectureFolder } from "./types";

/**
 * @param count How many records are being moved (named in the title).
 * @param noun The records' kind in the plural (`elements`).
 * @param folders The owner's folders of the list's kind.
 * @param error A save error to show.
 * @param onMove Called with the chosen folder's id, or null for the top level.
 */
export function MoveToFolderDialog({
  count, noun, folders, error, onCancel, onMove,
}: {
  count: number;
  noun: string;
  folders: ArchitectureFolder[];
  error?: string | null;
  onCancel: () => void;
  onMove: (folderId: string | null) => void;
}) {
  const [folderId, setFolderId] = useState<string | null>(null);
  return (
    <Modal title={`Move ${count} ${count === 1 ? noun.replace(/s$/, "") : noun} to a folder`} onClose={onCancel}>
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TreeSelectField
            help={ARCHITECTURE_HELP.folderField} single searchable label="Folder" nodes={folderSelectNodes(folders)}
            value={folderId ? [folderId] : []} emptyLabel="Top level (no folder)" clearLabel="Top level (no folder)"
            onChange={([next]) => setFolderId(next ?? null)}
          />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onMove(folderId)} saveLabel="Move" />
      </div>
    </Modal>
  );
}
