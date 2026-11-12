/**
 * Module: components/treeSelectFilter
 *
 * The search rule of `TreeSelect`: which nodes of a tree survive a typed query. Kept apart from the component so the
 * component file exports only components.
 */
import type { TreeSelectNode } from "./TreeSelect";

/** The nodes whose label contains `query` (ignoring case) and the ancestors that lead to them, each with only the
 * children that survive; a node that matches keeps its whole subtree so a group found by name still shows its members. */
export function filterTreeNodes(nodes: TreeSelectNode[], query: string): TreeSelectNode[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return nodes;
  const keep = (n: TreeSelectNode): TreeSelectNode | null => {
    if (n.label.toLowerCase().includes(needle)) return n;
    const children = n.children.map(keep).filter((c): c is TreeSelectNode => c !== null);
    return children.length > 0 ? { ...n, children } : null;
  };
  return nodes.map(keep).filter((n): n is TreeSelectNode => n !== null);
}
