/**
 * Module: modules/architecture/folderTree
 *
 * Pure helpers for the folder trees of the Elements, Connections and Diagrams lists: the tree a panel or a picker draws,
 * the folder ids below a folder (for "include sub-folders"), whether a record's folder path is inside a chosen folder
 * and the tree of folders another owner shares (built from the paths of the records the viewer may read, so no folder
 * outside those paths is ever shown).
 */
import type { TreeSelectNode } from "../../components/TreeSelect";
import type { ArchitectureFolder } from "./types";

/** The separator of a folder path (`Software/Modules`); a folder name never contains it. */
export const FOLDER_PATH_SEPARATOR = "/";

/** A folder with its sub-folders. */
export interface FolderNode {
  id: string;
  folder: ArchitectureFolder;
  children: FolderNode[];
}

/** Arranges `folders` by their parent links, siblings in the server's order (sort order, then name). */
export function buildFolderTree(folders: ArchitectureFolder[]): FolderNode[] {
  const nodes = new Map<string, FolderNode>(folders.map((f) => [f.id, { id: f.id, folder: f, children: [] }]));
  const roots: FolderNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.folder.parent_id ? nodes.get(node.folder.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

/** The picker nodes of a folder tree; `exclude` leaves out a folder and everything below it (a folder's own subtree is no place to move it). */
export function folderSelectNodes(folders: ArchitectureFolder[], exclude?: string): TreeSelectNode[] {
  const convert = (nodes: FolderNode[]): TreeSelectNode[] =>
    nodes.filter((n) => n.id !== exclude).map((n) => ({
      id: n.id, label: n.folder.name, pathLabel: n.folder.path, children: convert(n.children),
    }));
  return convert(buildFolderTree(folders));
}

/** The ids of `folderId` and every folder below it. */
export function folderSubtreeIds(folders: ArchitectureFolder[], folderId: string): Set<string> {
  const childrenOf = new Map<string, string[]>();
  for (const f of folders) {
    if (f.parent_id) childrenOf.set(f.parent_id, [...(childrenOf.get(f.parent_id) ?? []), f.id]);
  }
  const found = new Set<string>([folderId]);
  const queue = [folderId];
  while (queue.length > 0) {
    for (const child of childrenOf.get(queue.shift() as string) ?? []) {
      if (!found.has(child)) {
        found.add(child);
        queue.push(child);
      }
    }
  }
  return found;
}

/**
 * Whether a record in the folder at `recordPath` is shown when `chosenPath` is the chosen folder: it is in that
 * folder, or (with `includeSubfolders`) anywhere below it. No chosen folder shows everything; a record in no folder
 * matches only that choice.
 */
export function inChosenFolder(recordPath: string | null, chosenPath: string, includeSubfolders: boolean): boolean {
  if (!chosenPath) return true;
  if (!recordPath) return false;
  const record = recordPath.toLowerCase();
  const chosen = chosenPath.toLowerCase();
  return record === chosen || (includeSubfolders && record.startsWith(chosen + FOLDER_PATH_SEPARATOR));
}

/** A folder drawn from record paths only: its name, its full path and the folders below it. */
export interface PathFolderNode {
  id: string;
  name: string;
  path: string;
  children: PathFolderNode[];
}

/**
 * The folder tree implied by `paths` (one per record), each folder with its ancestors, in alphabetical order. Used for
 * the elements another owner shares: only the folders on the way to an element the person may read appear.
 */
export function treeFromPaths(paths: (string | null)[]): PathFolderNode[] {
  const roots: PathFolderNode[] = [];
  const byPath = new Map<string, PathFolderNode>();
  for (const path of new Set(paths.filter((p): p is string => Boolean(p)))) {
    let parent: PathFolderNode | undefined;
    let prefix = "";
    for (const name of path.split(FOLDER_PATH_SEPARATOR)) {
      prefix = prefix ? `${prefix}${FOLDER_PATH_SEPARATOR}${name}` : name;
      let node = byPath.get(prefix);
      if (!node) {
        node = { id: prefix, name, path: prefix, children: [] };
        byPath.set(prefix, node);
        (parent ? parent.children : roots).push(node);
      }
      parent = node;
    }
  }
  const sort = (nodes: PathFolderNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }));
    nodes.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

/** What an element picker needs of a record to place it in the folder tree: who owns it and where it is filed. */
export interface OwnedFolderRow {
  ownerKey: string;
  ownerLabel: string;
  folderPath: string | null;
}

const OWNER_NODE_PREFIX = "owner:";
const FOLDER_NODE_PREFIX = "folder:";

/**
 * The picker tree of the folders that hold `rows`: one top-level node per owner (the viewer's own project first), then
 * that owner's folders. Only the folders on the way to a listed record are drawn, so a picker never shows a folder
 * or structure of another owner that the viewer cannot reach.
 */
export function ownerFolderNodes(rows: OwnedFolderRow[], ownKey: string): TreeSelectNode[] {
  const owners = new Map<string, { label: string; paths: (string | null)[] }>();
  for (const row of rows) {
    const entry = owners.get(row.ownerKey) ?? { label: row.ownerLabel, paths: [] };
    entry.paths.push(row.folderPath);
    owners.set(row.ownerKey, entry);
  }
  const convert = (ownerKey: string, nodes: PathFolderNode[]): TreeSelectNode[] =>
    nodes.map((n) => ({ id: `${FOLDER_NODE_PREFIX}${ownerKey}|${n.path}`, label: n.name, pathLabel: n.path, children: convert(ownerKey, n.children) }));
  return [...owners.entries()]
    .sort(([a], [b]) => (a === ownKey ? -1 : b === ownKey ? 1 : a.localeCompare(b)))
    .map(([ownerKey, { label, paths }]) => ({
      id: `${OWNER_NODE_PREFIX}${ownerKey}`, label, children: convert(ownerKey, treeFromPaths(paths)),
    }));
}

/**
 * Whether a record owned by `ownerKey` and filed at `folderPath` is inside any of the picker nodes in `nodeIds` (an owner
 * node takes everything that owner has, a folder node its records and those in the folders below it). No node chosen
 * matches everything.
 */
export function inChosenOwnerFolders(nodeIds: string[], ownerKey: string, folderPath: string | null): boolean {
  if (nodeIds.length === 0) return true;
  return nodeIds.some((id) => {
    if (id.startsWith(OWNER_NODE_PREFIX)) return id.slice(OWNER_NODE_PREFIX.length) === ownerKey;
    const [owner, ...path] = id.slice(FOLDER_NODE_PREFIX.length).split("|");
    return owner === ownerKey && inChosenFolder(folderPath, path.join("|"), true);
  });
}
