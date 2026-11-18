/**
 * Module: modules/architecture/connectionTypeTree
 *
 * The connection type tree as the screens use it: a type may sit under several parents, to any depth, and a group
 * is itself a usable type. Turns the flat list the API returns into the nodes a `TreeSelect` shows (a type under
 * several parents appears under each), expands a type to itself and everything beneath it (the client-side twin of
 * the server's `connection_tree.closure_of`, for the filters that run in the browser) and names a type by its path.
 *
 * A parent that is not in the list (hidden in this project) leaves its children as roots, so a type is never lost.
 */
import type { TreeSelectNode } from "../../components/TreeSelect";
import type { ConnectionType } from "./types";

/** The longest chain the server accepts; the walks below stop here so a corrupt list cannot loop. */
export const MAX_TYPE_DEPTH = 12;

type Parented = Pick<ConnectionType, "id" | "name" | "sort_order" | "parent_ids">;

/** `{parent id: its children}` in picker order, over the types in `types` only. */
function childrenOf<T extends Parented>(types: T[]): Map<string, T[]> {
  const present = new Set(types.map((t) => t.id));
  const out = new Map<string, T[]>();
  for (const type of [...types].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))) {
    for (const parent of type.parent_ids) {
      if (present.has(parent)) out.set(parent, [...(out.get(parent) ?? []), type]);
    }
  }
  return out;
}

/** The types that have no parent in the list, in picker order. */
export function rootTypes<T extends Parented>(types: T[]): T[] {
  const present = new Set(types.map((t) => t.id));
  return [...types]
    .filter((t) => !t.parent_ids.some((p) => present.has(p)))
    .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
}

/**
 * The tree for a picker.
 *
 * @param types The connection types to show.
 * @param disabled Ids that cannot be chosen, each with the reason (shown as a tooltip); they still show their place.
 */
export function connectionTypeNodes(types: ConnectionType[], disabled: ReadonlyMap<string, string> = new Map()): TreeSelectNode[] {
  const children = childrenOf(types);
  const build = (type: ConnectionType, depth: number): TreeSelectNode => {
    const reason = disabled.get(type.id);
    return {
      id: type.id, label: type.name, disabled: reason !== undefined, title: reason,
      children: depth >= MAX_TYPE_DEPTH ? [] : (children.get(type.id) ?? []).map((c) => build(c, depth + 1)),
    };
  };
  return rootTypes(types).map((t) => build(t, 1));
}

/** The given ids and every type beneath them. */
export function typeClosure(types: ConnectionType[], ids: Iterable<string>): Set<string> {
  const children = childrenOf(types);
  const out = new Set<string>();
  const stack = [...ids];
  while (stack.length > 0) {
    const id = stack.pop() as string;
    if (out.has(id)) continue;
    out.add(id);
    for (const child of children.get(id) ?? []) stack.push(child.id);
  }
  return out;
}

/**
 * The ids a type may not take as a parent: itself and everything beneath it (a cycle), with the reason.
 *
 * @param types The candidates.
 * @param typeId The type being edited; omit when creating.
 */
export function cycleReasons(types: ConnectionType[], typeId?: string): Map<string, string> {
  if (!typeId) return new Map();
  return new Map([...typeClosure(types, [typeId])].map((id) => [id, id === typeId ? "A type cannot sit under itself." : "This type sits beneath it."]));
}

/** Every type in tree order (a type under several parents appears once, at its first place) with how deep it is. */
export function flattenTypes(types: ConnectionType[]): Array<{ type: ConnectionType; depth: number }> {
  const children = childrenOf(types);
  const seen = new Set<string>();
  const out: Array<{ type: ConnectionType; depth: number }> = [];
  const visit = (type: ConnectionType, depth: number) => {
    if (seen.has(type.id) || depth > MAX_TYPE_DEPTH) return;
    seen.add(type.id);
    out.push({ type, depth: depth - 1 });
    (children.get(type.id) ?? []).forEach((c) => visit(c, depth + 1));
  };
  rootTypes(types).forEach((t) => visit(t, 1));
  return out;
}

/** A flat select's options in tree order, each labelled with its place ("Serial bus › I2C"), for a control that cannot show a tree. */
export function pathOptions(types: ConnectionType[]): Array<{ value: string; label: string }> {
  const byId = new Map(types.map((t) => [t.id, t]));
  const pathOf = (type: ConnectionType, depth = 0): string => {
    const parent = depth < MAX_TYPE_DEPTH ? type.parent_ids.map((p) => byId.get(p)).find((p): p is ConnectionType => p !== undefined) : undefined;
    return parent ? `${pathOf(parent, depth + 1)} › ${type.name}` : type.name;
  };
  return flattenTypes(types).map(({ type }) => ({ value: type.id, label: pathOf(type) }));
}
