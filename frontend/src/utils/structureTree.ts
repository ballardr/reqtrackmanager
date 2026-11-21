/**
 * Module: utils/structureTree
 *
 * The project's component and category tree as the folder tree the Structure page draws: each component a folder, each
 * of its categories an item beneath it, in the tree's own (manual) order. Pure functions over plain data.
 *
 * Responsibilities: build the nodes, and narrow them to a search (a component that matches keeps all its categories; a
 * category that matches keeps its component), reporting which components a search opens.
 *
 * Design decisions: a node's id is the placement tree's (`componentNodeId`, `categoryNodeId`), so every control that
 * draws the tree names a node the same way. A component node's `path` is its component id, and a category's is its
 * component's, so a row finds its component without a second lookup.
 */
import type { PlacementTree } from "../api/placements";
import type { Category } from "../api/types";
import { categoryNodeId, componentNodeId } from "../components/placementTree";
import type { FolderNode } from "./reportFolders";

/** Whether `text` contains `needle`, ignoring case and surrounding space. */
function contains(text: string, needle: string): boolean {
  return text.toLowerCase().includes(needle);
}

/**
 * @param tree The components and categories, each in display order.
 * @param search The text to narrow to (name or prefix); empty shows everything.
 * @returns The component folders with their category items, and the ids of the components a search leaves open
 *   (empty without a search).
 */
export function buildStructureNodes(tree: PlacementTree, search = ""): { nodes: FolderNode<Category>[]; opened: Set<string> } {
  const needle = search.trim().toLowerCase();
  const nodes: FolderNode<Category>[] = [];
  const opened = new Set<string>();
  for (const component of tree.components) {
    const own = tree.categories.filter((c) => c.component_id === component.id);
    const componentMatches = needle === "" || contains(component.name, needle) || contains(component.prefix, needle);
    const kept = componentMatches ? own : own.filter((c) => contains(c.name, needle) || contains(c.prefix, needle));
    if (!componentMatches && kept.length === 0) continue;
    const id = componentNodeId(component.id);
    if (needle !== "") opened.add(id);
    nodes.push({
      id, kind: "folder", name: component.name, path: component.id, count: own.length,
      children: kept.map((category) => ({
        id: categoryNodeId(category.id), kind: "item", name: category.name, path: component.id, item: category, count: 0, children: [],
      })),
    });
  }
  return { nodes, opened };
}
