/**
 * Module: utils/reportLayoutTree
 *
 * Pure helpers the block outline uses to place, move and reach blocks in a layout tree, and to work out which
 * `{{name.field}}` names are in scope at a block.
 *
 * Responsibilities:
 * - Paths: read the server's problem paths (`nodes[1].children[0].level`) into segments and back.
 * - Immutable edits of the tree: set a key, insert, remove, move, indent, outdent and duplicate a block.
 * - Scope: the names the enclosing blocks bring in, from each block type's schema (`BlockProvides`).
 *
 * Design decisions: the helpers know where child blocks live only through the block catalogue's `containers`
 * and `provides`, never by block type, so a module's block type needs no change here. Nothing validates: the
 * server's `validate` is the only judge of a tree, and these edits can leave it invalid until the author fills
 * a new block in.
 */
import type { BlockType, TreeProblem } from "../api/reportLayouts";

export type Tree = Record<string, unknown>;
export type TreeNode = Record<string, unknown>;
/** A step in a path: a key, or an index into a list. */
export type Seg = string | number;
/** Where a block is: the segments from the tree to it, always ending in its index (`["nodes", 1, "children", 0]`). */
export type NodeAddr = Seg[];

/** The key of the top-level block list. */
export const ROOT_LIST = "nodes";
/** Keys that hold lists of blocks; an index after one of these is a block rather than, say, a column. */
const BLOCK_LISTS = new Set([ROOT_LIST, "children", "else_children"]);

/** A name a block brings into scope. */
export interface NameInScope {
  name: string;
  kind: "record" | "group";
  /** The record type of the record, or of the group's members; `null` when it could not be told. */
  recordType: string | null;
}

/**
 * Reads a server path into segments.
 *
 * @param path e.g. `nodes[1].children[0].level`; empty means the layout itself.
 */
export function parsePath(path: string): Seg[] {
  const segs: Seg[] = [];
  for (const match of path.matchAll(/([^.[\]]+)|\[(\d+)\]/g)) {
    segs.push(match[2] !== undefined ? Number(match[2]) : match[1]);
  }
  return segs;
}

/** Writes segments as the server writes a path. */
export function formatPath(segs: Seg[]): string {
  return segs.map((seg, i) => (typeof seg === "number" ? `[${seg}]` : i === 0 ? seg : `.${seg}`)).join("");
}

/**
 * Splits a problem path into the block it belongs to and the rest (the key inside that block).
 *
 * @returns The innermost block's address and what follows it (`["level"]`, `["source", "record_type"]`), or `null`
 * for a problem about the layout itself.
 */
export function owningNode(path: string): { addr: NodeAddr; rest: Seg[] } | null {
  const segs = parsePath(path);
  for (let i = segs.length - 1; i >= 1; i -= 1) {
    const here = segs[i];
    const before = segs[i - 1];
    if (typeof here === "number" && typeof before === "string" && BLOCK_LISTS.has(before)) {
      return { addr: segs.slice(0, i + 1), rest: segs.slice(i + 1) };
    }
  }
  return null;
}

/** The value at `segs`, or `undefined` when the path leads nowhere. */
export function getAt(root: unknown, segs: Seg[]): unknown {
  let at: unknown = root;
  for (const seg of segs) {
    if (at === null || typeof at !== "object") return undefined;
    at = (at as Record<Seg, unknown>)[seg];
  }
  return at;
}

/** A copy of `root` with the value at `segs` replaced; `undefined` removes a key. Intermediate containers are copied. */
export function setAt<T>(root: T, segs: Seg[], value: unknown): T {
  if (segs.length === 0) return value as T;
  const [head, ...rest] = segs;
  const copy: unknown = Array.isArray(root) ? [...root] : { ...(root as Record<string, unknown>) };
  const holder = copy as Record<Seg, unknown>;
  const next = rest.length === 0 ? value : setAt(holder[head] ?? (typeof rest[0] === "number" ? [] : {}), rest, value);
  if (next === undefined && !Array.isArray(copy)) delete holder[head];
  else holder[head] = next;
  return copy as T;
}

/** The blocks of the list at `list` (empty when there is none). */
export function listAt(tree: Tree, list: Seg[]): TreeNode[] {
  const found = getAt(tree, list);
  return Array.isArray(found) ? (found as TreeNode[]) : [];
}

/** The block at `addr`. */
export function nodeAt(tree: Tree, addr: NodeAddr): TreeNode | undefined {
  const found = getAt(tree, addr);
  return found !== null && typeof found === "object" ? (found as TreeNode) : undefined;
}

/** The list a block sits in, and its index there. */
function split(addr: NodeAddr): { list: Seg[]; index: number } {
  return { list: addr.slice(0, -1), index: addr[addr.length - 1] as number };
}

/** The address of the block that holds `addr`, or `null` for a top-level block. */
export function parentAddr(addr: NodeAddr): NodeAddr | null {
  return addr.length > 2 ? addr.slice(0, -2) : null;
}

/** A copy of the tree with `node` inserted at `index` of the list at `list`. */
export function insertNode(tree: Tree, list: Seg[], index: number, node: TreeNode): Tree {
  const blocks = [...listAt(tree, list)];
  blocks.splice(index, 0, node);
  return setAt(tree, list, blocks);
}

/** A copy of the tree without the block at `addr`. */
export function removeNode(tree: Tree, addr: NodeAddr): Tree {
  const { list, index } = split(addr);
  const blocks = listAt(tree, list).filter((_, i) => i !== index);
  return setAt(tree, list, blocks);
}

/** A deep copy of a block, so a duplicate shares nothing with the original. */
export function cloneNode(node: TreeNode): TreeNode {
  return JSON.parse(JSON.stringify(node)) as TreeNode;
}

/** A copy of the tree with the block at `addr` copied just after itself; the second value is the copy's address. */
export function duplicateNode(tree: Tree, addr: NodeAddr): { tree: Tree; addr: NodeAddr } | null {
  const node = nodeAt(tree, addr);
  if (!node) return null;
  const { list, index } = split(addr);
  return { tree: insertNode(tree, list, index + 1, cloneNode(node)), addr: [...list, index + 1] };
}

/** Moves a block one place up (`-1`) or down (`1`) in its list; `null` at either end. */
export function moveNode(tree: Tree, addr: NodeAddr, delta: -1 | 1): { tree: Tree; addr: NodeAddr } | null {
  const { list, index } = split(addr);
  const blocks = [...listAt(tree, list)];
  const target = index + delta;
  if (target < 0 || target >= blocks.length) return null;
  [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
  return { tree: setAt(tree, list, blocks), addr: [...list, target] };
}

/**
 * Whether the block at `addr` can move into the block before it, and which of that block's lists it would join.
 *
 * @param types The block catalogue, to know which blocks hold children.
 * @returns The list key (the previous block's first container), or `null` when there is none.
 */
export function indentTarget(tree: Tree, addr: NodeAddr, types: BlockType[]): string | null {
  const { list, index } = split(addr);
  if (index === 0) return null;
  const before = listAt(tree, list)[index - 1];
  const spec = types.find((t) => t.type === before?.type);
  return spec?.containers[0]?.key ?? null;
}

/** Moves a block into the end of the block before it (see {@link indentTarget}); `null` when it cannot. */
export function indentNode(tree: Tree, addr: NodeAddr, types: BlockType[]): { tree: Tree; addr: NodeAddr } | null {
  const key = indentTarget(tree, addr, types);
  const node = nodeAt(tree, addr);
  if (key === null || !node) return null;
  const { list, index } = split(addr);
  const without = removeNode(tree, addr);
  const into = [...list, index - 1, key];
  const at = listAt(without, into).length;
  return { tree: insertNode(without, into, at, node), addr: [...into, at] };
}

/** Moves a block out of its container to just after the block that held it; `null` for a top-level block. */
export function outdentNode(tree: Tree, addr: NodeAddr): { tree: Tree; addr: NodeAddr } | null {
  const parent = parentAddr(addr);
  const node = nodeAt(tree, addr);
  if (parent === null || !node) return null;
  const outer = split(parent);
  const without = removeNode(tree, addr);
  return { tree: insertNode(without, outer.list, outer.index + 1, node), addr: [...outer.list, outer.index + 1] };
}

/** A list key a block with this type could hold (its first container), or `null`. */
export function firstContainer(type: BlockType | undefined): string | null {
  return type?.containers[0]?.key ?? null;
}

/**
 * The names the enclosing blocks of `addr` bring into scope, outermost first.
 *
 * A block's own name is for the blocks inside it, so it is not in scope for the block itself (its source reads
 * the names of the blocks around it).
 *
 * @param tree The tree.
 * @param addr The block whose surroundings to read.
 * @param types The block catalogue, for each type's `provides`.
 */
export function namesInScope(tree: Tree, addr: NodeAddr, types: BlockType[]): NameInScope[] {
  const names: NameInScope[] = [];
  const ancestors: NodeAddr[] = [];
  for (let up = parentAddr(addr); up !== null; up = parentAddr(up)) ancestors.unshift(up);
  for (const ancestor of ancestors) {
    const node = nodeAt(tree, ancestor);
    const provides = types.find((t) => t.type === node?.type)?.provides;
    if (!node || !provides) continue;
    const given = node[provides.key];
    const name = typeof given === "string" && given !== "" ? given : provides.default;
    names.push({ name, kind: provides.kind, recordType: sourceRecordType(node.source, names) });
  }
  return names;
}

/** The record type a source reads: its own `record_type`, or that of the group it takes the members of. */
export function sourceRecordType(source: unknown, visible: NameInScope[]): string | null {
  if (source === null || typeof source !== "object") return null;
  const src = source as Record<string, unknown>;
  if (typeof src.record_type === "string" && src.record_type !== "") return src.record_type;
  if (typeof src.group === "string") return visible.find((n) => n.name === src.group && n.kind === "group")?.recordType ?? null;
  return null;
}

/** A short line naming a block in the outline: its first text-like value, else its source's record type. */
export function summarise(node: TreeNode, maxLength = 60): string {
  const pick = ["text", "name", "tex", "key", "by"].map((k) => node[k]).find((v) => typeof v === "string" && v !== "");
  const source = node.source as Record<string, unknown> | undefined;
  const line = typeof pick === "string" ? pick : typeof source?.record_type === "string" ? source.record_type : "";
  const flat = line.replace(/\s+/g, " ").trim();
  return flat.length > maxLength ? `${flat.slice(0, maxLength - 1)}…` : flat;
}

/** The tree as stable text (sorted keys), to tell whether two trees are the same. */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** A fresh condition test: `{field, op, value}` over a record's fields, or `{ref: "name.field", op, value}` in an `if`. */
export function newLeaf(mode: "record" | "ref"): Record<string, unknown> {
  return mode === "record" ? { field: "", op: "eq", value: "" } : { ref: "", op: "eq", value: "" };
}

/** The problems found for one block, split by where they belong. */
export interface BlockProblems {
  /** By the first key inside the block (`level`, `source`, `children`). */
  byKey: Map<string, string[]>;
  /** Everything about the block as a whole (`nodes[1].type`). */
  own: string[];
  /** All of them, for the count on the card. */
  total: number;
}

/**
 * The server's problems that belong to the block at `path`, split by the key inside it they are about.
 *
 * @param problems Every problem for the tree.
 * @param path The block's path (`nodes[1].children[0]`).
 */
export function problemsForNode(problems: TreeProblem[], path: string): BlockProblems {
  const byKey = new Map<string, string[]>();
  const own: string[] = [];
  let total = 0;
  for (const problem of problems) {
    const owner = owningNode(problem.path);
    if (!owner || formatPath(owner.addr) !== path) continue;
    total += 1;
    const key = owner.rest[0];
    if (typeof key === "string") byKey.set(key, [...(byKey.get(key) ?? []), problem.message]);
    else own.push(problem.message);
  }
  return { byKey, own, total };
}

