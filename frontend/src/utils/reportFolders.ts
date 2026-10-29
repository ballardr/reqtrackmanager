/**
 * Module: utils/reportFolders
 *
 * Folder paths of the Reports picker and the tree built from them.
 *
 * Responsibilities: split and join a path (`Handover/Quarterly`, up to three levels), build a nested tree of folders
 * holding items from a flat list (levels merged case-insensitively, the first spelling kept), list every folder
 * path so a form can offer the existing ones, and follow a path through a rename or delete. Pure functions over plain
 * data: nothing here knows what a report is.
 *
 * Design decisions: a folder is only a label on each item, so the tree is derived on every render and never stored;
 * folders sort by name and items by title so the picker reads the same for everyone.
 */
import type { TreeViewNode } from "../components/TreeView";

export const FOLDER_SEPARATOR = "/";
export const MAX_FOLDER_DEPTH = 3;
export const MAX_FOLDER_LEVEL_CHARS = 40;
export const MAX_FOLDER_CHARS = 120;

/** The levels of a folder path, tidied the way the server tidies them (trimmed, empty levels dropped). */
export function folderLevels(path: string): string[] {
  return path.split(FOLDER_SEPARATOR).map((level) => level.replace(/\s+/g, " ").trim()).filter((level) => level !== "");
}

/** The tidied path (`" A / B "` → `"A/B"`), or `""`. */
export function tidyFolder(path: string): string {
  return folderLevels(path).join(FOLDER_SEPARATOR);
}

/** Why a typed folder would be refused by the server, or `null` when it is fine. */
export function folderProblem(path: string): string | null {
  const levels = folderLevels(path);
  if (levels.length > MAX_FOLDER_DEPTH) return `A folder is at most ${MAX_FOLDER_DEPTH} levels deep.`;
  if (levels.some((level) => level.length > MAX_FOLDER_LEVEL_CHARS)) return `Each level is at most ${MAX_FOLDER_LEVEL_CHARS} characters.`;
  if (levels.join(FOLDER_SEPARATOR).length > MAX_FOLDER_CHARS) return `A folder path is at most ${MAX_FOLDER_CHARS} characters.`;
  return null;
}

/** A node of the picker's tree: a folder (with sub-folders and items) or an item (a leaf). */
export interface FolderNode<T> extends TreeViewNode<FolderNode<T>> {
  kind: "folder" | "item";
  /** The folder's level name, or the item's title. */
  name: string;
  /** For a folder, its full path; for an item, its folder's. */
  path: string;
  /** For an item, what it is. */
  item?: T;
  /** For a folder, how many items it holds, sub-folders included. */
  count: number;
}

/** The id of a folder node (stable across renders, so expansion survives). */
export function folderNodeId(path: string, prefix = "f"): string {
  return `${prefix}:${path.toLowerCase()}`;
}

/**
 * Builds the folder tree of `items`.
 *
 * @param items What to file.
 * @param folderOf The item's folder path (`""` files it at the top level).
 * @param titleOf The item's title (its name in the tree, and its sort key).
 * @param idOf A unique id for the item.
 * @param prefix Distinguishes the ids of two trees shown at once (the favourites folder repeats items).
 * @returns The top-level folders first, then top-level items, each level sorted by name.
 */
export function buildFolderTree<T>(
  items: T[], folderOf: (item: T) => string, titleOf: (item: T) => string, idOf: (item: T) => string, prefix = "f",
): FolderNode<T>[] {
  const root: FolderNode<T> = { id: "", kind: "folder", name: "", path: "", children: [], count: 0 };
  const folders = new Map<string, FolderNode<T>>();
  const folderFor = (levels: string[]): FolderNode<T> => {
    let parent = root;
    let path = "";
    for (const level of levels) {
      path = path === "" ? level : `${path}${FOLDER_SEPARATOR}${level}`;
      const key = path.toLowerCase();
      let node = folders.get(key);
      if (!node) {
        node = { id: folderNodeId(path, prefix), kind: "folder", name: level, path, children: [], count: 0 };
        folders.set(key, node);
        parent.children.push(node);
      }
      parent = node;
    }
    return parent;
  };
  for (const item of items) {
    const levels = folderLevels(folderOf(item));
    const folder = folderFor(levels);
    folder.children.push({
      id: `${prefix}:item:${idOf(item)}`, kind: "item", name: titleOf(item), path: folder.path, item, children: [], count: 1,
    });
    // `count` is the number of items at or below each folder on the path.
    let path = "";
    for (const level of levels) {
      path = path === "" ? level : `${path}${FOLDER_SEPARATOR}${level}`;
      const ancestor = folders.get(path.toLowerCase());
      if (ancestor) ancestor.count += 1;
    }
  }
  const sort = (nodes: FolderNode<T>[]) => {
    nodes.sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) : a.kind === "folder" ? -1 : 1));
    for (const node of nodes) sort(node.children);
  };
  sort(root.children);
  return root.children;
}

/** The ids of every folder node in `nodes` (to expand them all). */
export function allFolderIds<T>(nodes: FolderNode<T>[]): string[] {
  return nodes.flatMap((node) => (node.kind === "folder" ? [node.id, ...allFolderIds(node.children)] : []));
}

/** Every distinct folder path in `paths` and the paths above them, sorted (what a form offers as suggestions). */
export function distinctFolders(paths: string[]): string[] {
  const seen = new Map<string, string>();
  for (const raw of paths) {
    const levels = folderLevels(raw);
    for (let depth = 1; depth <= levels.length; depth += 1) {
      const path = levels.slice(0, depth).join(FOLDER_SEPARATOR);
      if (!seen.has(path.toLowerCase())) seen.set(path.toLowerCase(), path);
    }
  }
  return [...seen.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
}

/** The path one level up (`""` for a first-level folder). */
export function parentFolder(path: string): string {
  return folderLevels(path).slice(0, -1).join(FOLDER_SEPARATOR);
}

/** Whether `path` is `folder` or inside it (case-insensitive). */
export function isInsideFolder(path: string, folder: string): boolean {
  const a = path.toLowerCase();
  const b = folder.toLowerCase();
  return a === b || a.startsWith(`${b}${FOLDER_SEPARATOR}`);
}

/**
 * Where `path` ends up when `from` becomes `to` (a rename, or a delete where `to` is the deleted folder's parent): a path
 * at or inside `from` is re-rooted under `to`; any other path is unchanged.
 */
export function followFolder(path: string, from: string, to: string): string {
  if (!isInsideFolder(path, from)) return path;
  return [to, ...folderLevels(path).slice(folderLevels(from).length)].filter((level) => level !== "").join(FOLDER_SEPARATOR);
}
