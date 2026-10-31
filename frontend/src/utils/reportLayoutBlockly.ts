/**
 * Module: utils/reportLayoutBlockly
 *
 * Pure conversion between a report layout tree and the block editor's workspace state (Blockly's serialisation
 * JSON), plus the decisions about how a block type is drawn. It imports nothing from Blockly, so the round trip is
 * testable and the editor chunk stays out of the main bundle.
 *
 * Responsibilities:
 * - Summarise a block's key facts as one read-only line; every value is edited in the block editor beside the
 *   workspace, never on the block.
 * - Turn tree nodes into block states and back without losing any key: a block's `data` holds the whole node
 *   minus its child blocks, so a key the editor does not know survives an edit.
 * - List the blocks an author can add: one entry per block type, with the headings offered by level, the most-used
 *   types first.
 *
 * Design decisions: the tree stays canonical (the editor never keeps a second model); a block's `data` is the node
 * minus its child blocks and is the only thing read back, so opening a tree never rewrites it. Validity is the
 * server's; nothing here judges a value.
 */
import type { BlockType, LayoutFamily } from "../api/reportLayouts";
import { summarise, type Tree, type TreeNode } from "./reportLayoutTree";

/** Prefix of every generated Blockly block type, so a block type never collides with one Blockly ships. */
export const BLOCK_PREFIX = "rl_";
/** The fixed block every layout hangs from. */
export const ROOT_TYPE = `${BLOCK_PREFIX}root`;
/** The root block's statement input, holding the layout's top-level blocks. */
export const ROOT_INPUT = "nodes";

/** The block a node of a type the catalogue does not describe becomes: its whole node is kept in `data`. */
export const UNKNOWN_TYPE = `${BLOCK_PREFIX}unknown`;

/** The block field that shows a read-only summary of the block's key facts (the start of a text, a record type). */
export const SUMMARY_FIELD = "_summary";
/** Longest summary drawn on a block. */
const SUMMARY_LENGTH = 36;

/** A block in Blockly's serialisation JSON, as far as the editor reads or writes it. */
export interface BlockState {
  type: string;
  id?: string;
  fields?: Record<string, unknown>;
  inputs?: Record<string, { block?: BlockState }>;
  next?: { block?: BlockState };
  data?: string;
}

/** One block an author can add. */
export interface PaletteEntry {
  /** Unique within the list (`heading:2`, `table`). */
  key: string;
  type: BlockType;
  /** The node the added block starts as. */
  template: TreeNode;
  /** Whether the type is one of the most used (listed first, under its own heading). */
  common: boolean;
}

/** Headings are offered by level (the text view's toolbar does the same), each as its own palette entry. */
const PALETTE_LEVELS: Record<string, number[]> = { heading: [1, 2, 3] };
/** The block types most layouts start from, in the order they are offered; every other type follows, by name. */
const COMMON_TYPES = ["heading", "text", "table"];

/** @returns The Blockly block type name for a layout block type. */
export function blockName(type: string): string {
  return `${BLOCK_PREFIX}${type}`;
}

/** @returns The layout block type a Blockly block type stands for, or `null` for the root and foreign blocks. */
export function layoutType(blockType: string): string | null {
  return blockType.startsWith(BLOCK_PREFIX) && blockType !== ROOT_TYPE ? blockType.slice(BLOCK_PREFIX.length) : null;
}

/**
 * The read-only line a block shows for its key facts: the start of its text (or its record type), the alias a
 * "for each" names its records, and a heading's level. `undefined` when the block type has no fields to summarise.
 */
export function blockSummary(node: TreeNode, type: BlockType | undefined): string | undefined {
  if (!type || !type.described || type.fields.length === 0) return undefined;
  const line = summarise(node, SUMMARY_LENGTH);
  const alias = typeof node.as === "string" && node.as !== "" ? `as ${node.as}` : "";
  const level = typeof node.level === "number" ? `level ${String(node.level)}` : "";
  return [level, line, alias].filter((part) => part !== "").join(" · ");
}

/** The names of a block type's child-block lists. */
function containerKeys(type: BlockType | undefined): string[] {
  return type?.containers.map((container) => container.key) ?? [];
}

/**
 * Turns one tree node (without its siblings) into a block state.
 *
 * @param node The node.
 * @param types Every block type, to know which fields and child lists it has.
 */
export function nodeToBlockState(node: TreeNode, types: BlockType[]): BlockState {
  const kind = String(node.type ?? "");
  const type = types.find((t) => t.type === kind);
  const lists = containerKeys(type);
  const rest: TreeNode = {};
  for (const [key, value] of Object.entries(node)) {
    // Child lists are blocks, not data; an empty one is remembered so the node comes back with `[]` rather than without the key.
    if (lists.includes(key)) {
      if (!Array.isArray(value) || value.length === 0) rest[key] = [];
    } else rest[key] = value;
  }
  const state: BlockState = { type: type ? blockName(kind) : UNKNOWN_TYPE, data: JSON.stringify(rest) };
  const summary = blockSummary(node, type);
  if (summary !== undefined) state.fields = { [SUMMARY_FIELD]: summary };
  const inputs: Record<string, { block?: BlockState }> = {};
  for (const key of lists) {
    const chain = nodesToChain(node[key], types);
    if (chain) inputs[key] = { block: chain };
  }
  if (Object.keys(inputs).length > 0) state.inputs = inputs;
  return state;
}

/** Links a list of nodes into one chain (each block's `next` is the following sibling); `undefined` when empty. */
export function nodesToChain(nodes: unknown, types: BlockType[]): BlockState | undefined {
  if (!Array.isArray(nodes)) return undefined;
  let head: BlockState | undefined;
  for (let i = nodes.length - 1; i >= 0; i -= 1) {
    const node = nodes[i];
    if (node === null || typeof node !== "object" || Array.isArray(node)) continue;
    const state = nodeToBlockState(node as TreeNode, types);
    if (head) state.next = { block: head };
    head = state;
  }
  return head;
}

/** @returns Blockly's workspace state for a layout: the root block holding the layout's blocks. */
export function treeToWorkspaceState(tree: Tree, types: BlockType[]): { blocks: { languageVersion: 0; blocks: BlockState[] } } {
  const first = nodesToChain(tree[ROOT_INPUT], types);
  const root: BlockState = { type: ROOT_TYPE, ...(first ? { inputs: { [ROOT_INPUT]: { block: first } } } : {}) };
  return { blocks: { languageVersion: 0, blocks: [root] } };
}

/** Reads one block state back into a node. */
export function blockStateToNode(state: BlockState, types: BlockType[]): TreeNode {
  const kind = layoutType(state.type) ?? state.type;
  const type = types.find((t) => t.type === kind);
  const undescribed = state.type === UNKNOWN_TYPE;
  let node: TreeNode = {};
  try {
    const parsed: unknown = state.data ? JSON.parse(state.data) : {};
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) node = parsed as TreeNode;
  } catch {
    node = {};
  }
  // An undescribed node keeps the `type` it came with.
  if (!undescribed) node = { ...node, type: kind };
  for (const key of containerKeys(type)) {
    const children = chainToNodes(state.inputs?.[key]?.block, types);
    if (children.length > 0) node[key] = children;
    else if (!Array.isArray(node[key])) delete node[key];
  }
  return node;
}

/** Reads a chain of blocks (from its first block) back into the list of nodes. */
export function chainToNodes(first: BlockState | undefined, types: BlockType[]): TreeNode[] {
  const nodes: TreeNode[] = [];
  for (let state = first; state; state = state.next?.block) {
    if (layoutType(state.type) !== null) nodes.push(blockStateToNode(state, types));
  }
  return nodes;
}

/**
 * Reads a workspace state back into the layout: the tree `base` with its `nodes` replaced by the blocks under the
 * root. Blocks outside the root are not part of the layout.
 */
export function workspaceStateToTree(base: Tree, state: { blocks?: { blocks?: BlockState[] } }, types: BlockType[]): Tree {
  const root = state.blocks?.blocks?.find((block) => block.type === ROOT_TYPE);
  return { ...base, [ROOT_INPUT]: chainToNodes(root?.inputs?.[ROOT_INPUT]?.block, types) };
}

/** How many blocks sit outside the root in a workspace state (loose blocks the layout does not include). */
export function looseBlockCount(state: { blocks?: { blocks?: BlockState[] } }): number {
  return (state.blocks?.blocks ?? []).filter((block) => block.type !== ROOT_TYPE).length;
}

/**
 * @returns The blocks that can be added to a layout of `family`: the common types (Heading, Text, Table) first, then
 *   the rest by name, so the list reads by how often a block is wanted.
 * @param types Every block type.
 * @param family The layout's family.
 */
export function paletteEntries(types: BlockType[], family: LayoutFamily): PaletteEntry[] {
  const rank = (type: BlockType) => {
    const at = COMMON_TYPES.indexOf(type.type);
    return at === -1 ? COMMON_TYPES.length : at;
  };
  return types
    .filter((type) => type.families.includes(family))
    .sort((a, b) => rank(a) - rank(b) || (rank(a) < COMMON_TYPES.length ? 0 : a.label.localeCompare(b.label)))
    .flatMap((type) => {
      const common = rank(type) < COMMON_TYPES.length;
      const levels = PALETTE_LEVELS[type.type];
      if (!levels) return [{ key: type.type, type, template: type.template, common }];
      return levels.map((level) => ({ key: `${type.type}:${level}`, type, template: { ...type.template, level }, common }));
    });
}

/** The shape of a node list: types and child-list lengths, recursively. Two trees of the same shape differ only in values. */
export function shapeOf(nodes: unknown, types: BlockType[]): string {
  if (!Array.isArray(nodes)) return "";
  return nodes
    .map((raw) => {
      const node = (raw ?? {}) as TreeNode;
      const type = types.find((t) => t.type === node.type);
      const inner = containerKeys(type).map((key) => `${key}(${shapeOf(node[key], types)})`);
      return `${String(node.type)}${inner.length > 0 ? `{${inner.join(",")}}` : ""}`;
    })
    .join(";");
}

/** The node without its child lists: what a block keeps in `data`. */
export function nodeData(node: TreeNode, types: BlockType[]): string {
  const state = nodeToBlockState(node, types);
  return state.data ?? "{}";
}
