/**
 * Module: modules/architecture/diagramOutlineModel
 *
 * The text form of a diagram as plain data, with no React: the tree of the elements shown and the table of the lines
 * drawn, built from the same layout and resolved lines the canvas draws, so the outline can never show a different
 * diagram from the one on the screen.
 *
 * Responsibilities:
 * - `outlineTree`: nest each visible box under its nearest visible placed ancestor (the rule the roll-up uses to join a
 *   line to a placed parent), so decomposition reads as a tree.
 * - `connectionRows`: one row per drawn line with its ends, direction, type, route kind (direct, rolled up, bridged) and,
 *   for a bridged line, the hidden elements it passes through.
 *
 * Design decisions:
 * - A box a view switch hides is left out, like the canvas; only its count is reported, so the outline follows the
 *   current switch states.
 * - A box the viewer cannot read is named by its code only, never its name.
 */
import { boundaryNodeId, boundaryOutsideName, type EditorBoundary, type EditorBox } from "./diagramEditorModel";
import type { DiagramViewEdge } from "./types";

/** The longest ancestor walk, matching the resolver's cap. */
const WALK_CAP = 13;

/** One element of the outline and the elements nested directly under it. */
export interface OutlineNode {
  /** The element's id (the shared tree shell keys nodes by `id`). */
  id: string;
  box: EditorBox;
  children: OutlineNode[];
}

/** One line of the connection table. */
export interface ConnectionRow {
  /** The resolved line's id, which is also its canvas selection id. */
  id: string;
  from: string;
  to: string;
  /** True for a two-way line (drawn without arrow heads). */
  twoWay: boolean;
  /** The line's type and protocol text, blank when connection detail is off. */
  detail: string;
  /** How many connections the line stands for. */
  count: number;
  route: "direct" | "rolled_up" | "bridged";
  /** The hidden elements a bridged line passes through, as "CODE name" text. */
  via: string[];
}

/** @param box A placed element. @returns Its name for a list: code and name, or the code alone when unreadable. */
export function boxName(box: Pick<EditorBox, "unique_code" | "name" | "locked">): string {
  return box.locked ? box.unique_code : `${box.unique_code} ${box.name}`;
}

/** Orders codes as numbers within a prefix ("ELM-2" before "ELM-10"). */
function byCode(a: EditorBox, b: EditorBox): number {
  return a.unique_code.localeCompare(b.unique_code, undefined, { numeric: true });
}

/**
 * The visible boxes as a tree.
 *
 * @param boxes Every box of the layout.
 * @param parents `{element id: parent id}` for the diagram's elements and their ancestors.
 * @param hidden The elements a view switch hides (left out, with their descendants shown under no hidden parent).
 * @returns The roots, with children nested under their nearest visible placed ancestor; siblings in code order.
 */
export function outlineTree(
  boxes: readonly EditorBox[], parents: Readonly<Record<string, string | null>>, hidden: ReadonlySet<string>,
): OutlineNode[] {
  const visible = boxes.filter((b) => !hidden.has(b.elementId));
  const nodes = new Map(visible.map((b) => [b.elementId, { id: b.elementId, box: b, children: [] as OutlineNode[] }]));
  const roots: OutlineNode[] = [];
  /** Where each box was nested, so a loop in the parents (not possible in stored data) cannot lose boxes. */
  const nestedUnder = new Map<string, string>();
  const nestsInside = (holderId: string, boxId: string): boolean => {
    for (let id: string | undefined = holderId, step = 0; id !== undefined && step < WALK_CAP; id = nestedUnder.get(id), step += 1) {
      if (id === boxId) return true;
    }
    return false;
  };
  for (const box of [...visible].sort(byCode)) {
    const node = nodes.get(box.elementId)!;
    let holder: OutlineNode | undefined;
    let current: string | null | undefined = parents[box.elementId];
    for (let step = 0; step < WALK_CAP && current != null && current !== box.elementId; step += 1) {
      holder = nodes.get(current);
      if (holder) break;
      current = parents[current];
    }
    if (holder && !nestsInside(holder.id, box.elementId)) {
      holder.children.push(node);
      nestedUnder.set(box.elementId, holder.id);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

/** @param tree An outline. @returns The number of elements in it, nested ones included. */
export function outlineSize(tree: readonly OutlineNode[]): number {
  return tree.reduce((total, n) => total + 1 + outlineSize(n.children), 0);
}

/** One row of the element table: the element and the placed element it nests under. */
export interface ElementRow {
  /** The element's id, which is also its canvas selection id. */
  id: string;
  box: EditorBox;
  /** The nearest placed ancestor's name for a list, or null for a top-level element. */
  parent: string | null;
}

/**
 * The elements as table rows.
 *
 * @param tree An outline from {@link outlineTree}.
 * @returns One row per element in tree order (a parent before the elements nested under it), so the table and the tree read alike.
 */
export function elementRows(tree: readonly OutlineNode[]): ElementRow[] {
  const rows: ElementRow[] = [];
  const walk = (nodes: readonly OutlineNode[], parent: string | null) => {
    for (const node of nodes) {
      rows.push({ id: node.id, box: node.box, parent });
      walk(node.children, boxName(node.box));
    }
  };
  walk(tree, null);
  return rows;
}

/** @param tree An outline. @returns The ids of the elements that have elements nested under them. */
export function outlineBranchIds(tree: readonly OutlineNode[]): string[] {
  return tree.flatMap((n) => (n.children.length > 0 ? [n.id, ...outlineBranchIds(n.children)] : []));
}

/**
 * The rows of the connection table.
 *
 * @param edges The resolved lines.
 * @param boxes Every box of the layout, to name the ends.
 * @param boundaries The boundary boxes, which also end lines (named by the outer connection's code and the element outside).
 * @returns One row per line whose ends are both on the diagram.
 */
export function connectionRows(
  edges: readonly DiagramViewEdge[], boxes: readonly EditorBox[], boundaries: readonly EditorBoundary[] = [],
): ConnectionRow[] {
  const names = new Map<string, string>([
    ...boxes.map((b): [string, string] => [b.elementId, boxName(b)]),
    ...boundaries.map((b): [string, string] => [boundaryNodeId(b.connectionId), `${b.connection_code} (${boundaryOutsideName(b)})`]),
  ]);
  const rows: ConnectionRow[] = [];
  for (const edge of edges) {
    const from = names.get(edge.source_element_id);
    const to = names.get(edge.target_element_id);
    if (from === undefined || to === undefined) continue;
    rows.push({
      id: edge.id, from, to, twoWay: edge.two_way, detail: edge.label ?? "", count: edge.count,
      route: edge.bridged ? "bridged" : edge.rolled_up ? "rolled_up" : "direct",
      via: edge.hops.map((h) => `${h.unique_code} ${h.name}`),
    });
  }
  return rows;
}
