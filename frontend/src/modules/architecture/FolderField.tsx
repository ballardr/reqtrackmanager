/**
 * Module: modules/architecture/FolderField
 *
 * The Folder field of the create and edit forms of an element, a connection and a diagram: a one-choice tree of the
 * owner's folders of that kind, empty for the top level. It loads the folders itself, so a form needs no extra data.
 */
import { TreeSelectField } from "../../components/TreeSelectField";
import { ARCHITECTURE_HELP } from "./help";
import { folderSelectNodes } from "./folderTree";
import type { FolderKind } from "./types";
import { useFolders, type FolderOwner } from "./useFolders";

/**
 * @param kind Which tree to choose from.
 * @param owner The project (or, for an organisation element, the organisation) that owns the folders.
 * @param value The chosen folder's id, or null for the top level.
 * @param onChange Called with the chosen folder's id, or null.
 */
export function FolderField({
  kind, owner, value, onChange,
}: { kind: FolderKind; owner: FolderOwner; value: string | null; onChange: (next: string | null) => void }) {
  const { folders } = useFolders(owner, kind);
  return (
    <TreeSelectField
      help={ARCHITECTURE_HELP.folderField} single searchable label="Folder" nodes={folderSelectNodes(folders)}
      value={value ? [value] : []} emptyLabel="Top level (no folder)" clearLabel="Top level (no folder)"
      onChange={([next]) => onChange(next ?? null)}
    />
  );
}
