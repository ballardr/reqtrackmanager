/**
 * Module: components/folderTreeIcons
 *
 * The folder-row icons `FolderTreeList` lists share. A list whose rows are something other than folders (groups,
 * components) passes its own icon instead; core keeps no map from a kind of row to an icon.
 *
 * Dependencies: `lucide-react`, the `FolderTreeFolderIcon` type.
 */
import { Folder, FolderOpen } from "lucide-react";

import type { FolderTreeFolderIcon } from "./FolderTreeList";

/**
 * The icon for rows that really are folders (a report folder).
 *
 * @param open Whether the folder is expanded.
 * @returns A closed folder, or an open folder when expanded.
 */
export const realFolderIcon: FolderTreeFolderIcon = (open) => (open ? <FolderOpen aria-hidden="true" /> : <Folder aria-hidden="true" />);
