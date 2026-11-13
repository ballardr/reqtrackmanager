/**
 * Module: modules/architecture/FolderFormModal
 *
 * Create and edit dialog for a folder (a name and the folder it sits in), told apart by whether `initial` is passed;
 * editing is also how a folder is renamed and moved. A new folder may be given its parent in advance. The parent choices
 * leave out the folder itself and everything below it, so the dialog never offers a cycle.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { TreeSelectField } from "../../components/TreeSelectField";
import { ARCHITECTURE_HELP } from "./help";
import { folderSelectNodes, folderSubtreeIds } from "./folderTree";
import type { ArchitectureFolder } from "./types";

/** What the dialog saves. */
export interface FolderValues {
  name: string;
  parent_id: string | null;
}

/**
 * @param initial The folder being edited; omit to create.
 * @param folders The owner's folders of the same kind, for the parent choice.
 * @param defaultParentId A parent to preselect for a new folder (the folder chosen in the list).
 * @param error A save error to show.
 * @param onSave Called with the trimmed name and the parent.
 */
export function FolderFormModal({
  initial, folders, defaultParentId = null, error, onCancel, onSave,
}: {
  initial?: ArchitectureFolder;
  folders: ArchitectureFolder[];
  defaultParentId?: string | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: FolderValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [parentId, setParentId] = useState<string | null>(initial ? initial.parent_id : defaultParentId);
  const blocked = initial ? folderSubtreeIds(folders, initial.id) : new Set<string>();
  const choices = folders.filter((f) => !blocked.has(f.id));
  const valid = name.trim() !== "" && !name.includes("/");

  return (
    <Modal title={initial ? `Edit folder ${initial.name}` : "New folder"} onClose={onCancel}>
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField
            helpNotNeeded required label="Name" value={name} onChange={setName}
            hint={name.includes("/") ? "A folder name cannot contain a slash." : undefined}
          />
          <TreeSelectField
            help={ARCHITECTURE_HELP.folderParent} single searchable label="Parent folder" nodes={folderSelectNodes(choices)}
            value={parentId ? [parentId] : []} emptyLabel="Top level" clearLabel="Top level" onChange={([next]) => setParentId(next ?? null)}
          />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave({ name: name.trim(), parent_id: parentId })} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
