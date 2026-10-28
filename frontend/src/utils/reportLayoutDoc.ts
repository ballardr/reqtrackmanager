/**
 * Module: utils/reportLayoutDoc
 *
 * The converter between a document layout's tree and the rich-text editor's document (ProseMirror JSON), in both
 * directions, with no editor dependency so it can be tested as plain functions.
 *
 * Responsibilities:
 * - `treeToDoc`: the layout's blocks as editor nodes. Headings and text blocks become editable prose; a block
 *   that holds other blocks becomes a container with one slot per child list; every other block is carried whole.
 * - `docToTree`: the editor's document back into the blocks, merged into the tree it came from.
 * - Guarantee identity: for a tree this view can show, `docToTree(treeToDoc(tree))` is the same tree. A tree it
 *   cannot show losslessly is refused with the reason (`NotRepresentableError`), never approximated.
 *
 * Design decisions:
 * - **Prose is Markdown the engine reads.** A paragraph or list item carries bold, italic and code marks, which the
 *   report engine draws in every format; links, images in a sentence and raw HTML are not styles and stay as text.
 * - **A text block is shown as prose only when it round-trips exactly.** Its Markdown is read by a deliberately
 *   strict reader of the canonical spelling (`utils/reportLayoutProse`); `serialize(parse(markdown))` must give back
 *   the same string. Anything else stays a raw-Markdown block, editable as source, so no text is ever rewritten.
 * - **Schema-driven.** Which keys of a block are child lists comes from the block catalogue (`containers`), and every
 *   block type without a special case is a whole-node leaf, so a module's block type needs no code here.
 * - Block props (everything except prose and child lists) are kept as one opaque object and edited with the same
 *   forms as the outline; this module never reads them.
 */
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

import type { BlockType } from "../api/reportLayouts";
import { DOC, headingAnchor, parseMarkdown, serializeMarkdown, textNode, textOf, type DocNode } from "./reportLayoutProse";
import type { NodeAddr, Seg, Tree, TreeNode } from "./reportLayoutTree";

export { DOC, parseMarkdown, serializeMarkdown, type DocNode };

/** A tree this view cannot show without changing it. */
export class NotRepresentableError extends Error {
  constructor(message: string, readonly path: string) {
    super(message);
    this.name = "NotRepresentableError";
  }
}

type Props = Record<string, unknown>;

/** `node` without the named keys. */
function without(node: TreeNode, keys: string[]): Props {
  const rest: Props = {};
  for (const [key, value] of Object.entries(node)) if (!keys.includes(key)) rest[key] = value;
  return rest;
}

// ---- tree -> document ---------------------------------------------------------------------------------------------

/** The child lists a block of this type may hold. */
const containersOf = (types: BlockType[], type: unknown): string[] => types.find((t) => t.type === type)?.containers.map((c) => c.key) ?? [];

function convertNode(node: TreeNode, types: BlockType[], path: string): DocNode {
  const type = node.type;
  if (type === "heading") {
    if (typeof node.text !== "string") throw new NotRepresentableError("A heading has no text.", path);
    return { type: DOC.heading, attrs: { props: without(node, ["type", "text"]) }, content: textNode(node.text) };
  }
  if (type === "text") {
    if (typeof node.text !== "string") throw new NotRepresentableError("A text block has no text.", path);
    const props = without(node, ["type", "text"]);
    const parsed = parseMarkdown(node.text);
    return parsed
      ? { type: DOC.text, attrs: { props }, content: parsed }
      : { type: DOC.raw, attrs: { props, markdown: node.text } };
  }
  const keys = containersOf(types, type).filter((key) => key in node);
  if (keys.length === 0) return { type: DOC.leaf, attrs: { node } };
  const slots = keys.map((key): DocNode => {
    const list = node[key];
    if (!Array.isArray(list)) throw new NotRepresentableError(`"${key}" is not a list of blocks.`, `${path}.${key}`);
    return { type: DOC.slot, attrs: { key }, content: list.map((child, i) => convertNode(child as TreeNode, types, `${path}.${key}[${i}]`)) };
  });
  return { type: DOC.block, attrs: { type, props: without(node, ["type", ...keys]) }, content: slots };
}

/**
 * The editor document for a document layout's blocks.
 *
 * @param tree The layout tree.
 * @param types The block catalogue (to know which keys are child lists).
 * @throws NotRepresentableError When a block cannot be shown without changing it.
 */
export function treeToDoc(tree: Tree, types: BlockType[]): DocNode {
  const nodes = tree.nodes;
  if (!Array.isArray(nodes)) throw new NotRepresentableError("The layout has no list of blocks.", "nodes");
  return { type: "doc", content: nodes.map((node, i) => convertNode(node as TreeNode, types, `nodes[${i}]`)) };
}

// ---- document -> tree ---------------------------------------------------------------------------------------------

function nodeOfDoc(node: DocNode): TreeNode {
  switch (node.type) {
    case DOC.heading:
      return { type: "heading", ...(node.attrs?.props as Props), text: textOf(node.content) };
    case DOC.text:
      return { type: "text", ...(node.attrs?.props as Props), text: serializeMarkdown(node.content ?? []) };
    case DOC.raw:
      return { type: "text", ...(node.attrs?.props as Props), text: String(node.attrs?.markdown ?? "") };
    case DOC.block: {
      const result: TreeNode = { type: node.attrs?.type, ...(node.attrs?.props as Props) };
      for (const slot of node.content ?? []) result[String(slot.attrs?.key)] = (slot.content ?? []).map(nodeOfDoc);
      return result;
    }
    default:
      return JSON.parse(JSON.stringify(node.attrs?.node ?? {})) as TreeNode;
  }
}

/**
 * The tree for an editor document.
 *
 * @param doc The editor's document.
 * @param base The tree the document came from: its other keys (family, orientation, variables) are kept.
 */
export function docToTree(doc: DocNode, base: Tree): Tree {
  return { ...base, nodes: (doc.content ?? []).map(nodeOfDoc) };
}

/**
 * Where, in the layout tree, the editor node at `pos` is.
 *
 * @param doc The editor's document.
 * @param pos The position just before the node.
 * @returns The block's address (`["nodes", 1, "children", 0]`). For a slot's position, the address of the block
 * that holds it (add the slot's `key` for the list itself).
 */
export function addrAt(doc: ProseMirrorNode, pos: number): NodeAddr {
  const $pos = doc.resolve(pos);
  const segs: Seg[] = [];
  for (let depth = 0; depth <= $pos.depth; depth += 1) {
    const holder = $pos.node(depth);
    if (holder.type.name === "doc") segs.push("nodes", $pos.index(depth));
    else if (holder.type.name === DOC.slot) segs.push(String(holder.attrs.key), $pos.index(depth));
  }
  return segs;
}

/** A heading a link can point at: its words and the anchor the report gives it. */
export interface Section {
  label: string;
  anchor: string;
}

/**
 * The headings of a layout in reading order, with the anchors the report will give them (`heading_anchor`, made unique
 * by `-2`, `-3` on repeats).
 *
 * A heading whose words hold a `{{placeholder}}` is left out: its anchor depends on the record, so a link to it cannot
 * be written here. A heading inside a block that repeats per record is listed once.
 *
 * @param tree The layout tree.
 */
export function sectionsOf(tree: Tree): Section[] {
  const words: string[] = [];
  const walk = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach(walk);
    } else if (value !== null && typeof value === "object") {
      const node = value as TreeNode;
      if (node.type === "heading" && typeof node.text === "string") words.push(node.text);
      else if (node.type === "text" && typeof node.text === "string") {
        for (const block of node.text.split("\n\n")) {
          const heading = /^#{1,4} (\S(?:.*\S)?)$/.exec(block);
          if (heading && !block.includes("\n")) words.push(heading[1]);
        }
      }
      Object.values(node).forEach((child) => { if (typeof child === "object") walk(child); });
    }
  };
  walk(tree.nodes);
  const taken = new Set<string>();
  const sections: Section[] = [];
  for (const text of words) {
    const base = headingAnchor(text);
    let anchor = base;
    for (let n = 2; taken.has(anchor); n += 1) anchor = `${base}-${n}`;
    taken.add(anchor);
    if (!text.includes("{{")) sections.push({ label: text, anchor });
  }
  return sections;
}
