/**
 * Module: utils/reportSnippets
 *
 * Pure helpers for the snippet picker and for placing an inserted snippet in the designer's tree. The server builds and
 * validates the result (`ReportLayoutApi.applySnippet`); these only list, filter and read what it returned.
 *
 * Responsibilities:
 * - Group and filter the snippets the picker lists (`snippetCategories`, `filterSnippets`, `suitsFamily`).
 * - Work out which parameters still need a value (`initialValues`, `missingParameters`).
 * - Draw a fragment as an indented outline of its blocks (`outlineLines`) where a rendered sample would mean running a
 *   report.
 * - Read an applied result: where its blocks landed and the root-level keys it changed (`insertedBlocks`, `withBlocksOf`).
 *
 * Design decisions: no tree rules live here; a refused or half-valid insertion is the server's to say.
 */
import type { BlockType, LayoutFamily, ReportSnippet, SnippetApplyResult } from "../api/reportLayouts";
import { listAt, parsePath, summarise, type Seg, type Tree, type TreeNode } from "./reportLayoutTree";

/** The categories the snippets fall in, in the order they first appear. */
export function snippetCategories(snippets: readonly ReportSnippet[]): string[] {
  return [...new Set(snippets.map((s) => s.category))];
}

/** Whether a snippet belongs to a layout of this family. */
export function suitsFamily(snippet: ReportSnippet, family: LayoutFamily): boolean {
  return snippet.family === family;
}

/**
 * The snippets whose name, description or category contains `search` (any case), within `category` when one is chosen.
 *
 * @param snippets Every snippet the scope offers.
 * @param search Text typed in the picker's search box.
 * @param category A category name, or `""` for all.
 */
export function filterSnippets(snippets: readonly ReportSnippet[], search: string, category: string): ReportSnippet[] {
  const needle = search.trim().toLowerCase();
  return snippets.filter((s) => {
    if (category !== "" && s.category !== category) return false;
    return needle === "" || `${s.name} ${s.description} ${s.category}`.toLowerCase().includes(needle);
  });
}

/** The values a snippet's form starts with: each text parameter's default, nothing for a picture or a record type. */
export function initialValues(snippet: ReportSnippet): Record<string, string> {
  return Object.fromEntries(snippet.parameters.map((p) => [p.key, p.kind === "text" ? (p.default ?? "") : ""]));
}

/** The parameters that still need a value: a required one that is empty (a text with a default is never missing). */
export function missingParameters(snippet: ReportSnippet, values: Record<string, string>): string[] {
  return snippet.parameters.filter((p) => p.required && (values[p.key] ?? "").trim() === "").map((p) => p.key);
}

/** One line of a fragment outline: how deep it sits and what it says. */
export interface OutlineLine {
  depth: number;
  label: string;
}

/**
 * Names every block of a fragment, children indented under their parent ("Heading – Requirements").
 *
 * @param nodes The fragment's blocks.
 * @param types The block catalogue, for each type's label.
 */
export function outlineLines(nodes: readonly TreeNode[], types: readonly BlockType[]): OutlineLine[] {
  const lines: OutlineLine[] = [];
  const walk = (list: readonly TreeNode[], depth: number) => {
    for (const node of list) {
      const type = types.find((t) => t.type === node.type);
      const label = type?.label ?? String(node.type ?? "?");
      const start = summarise(node, 40);
      lines.push({ depth, label: start === "" ? label : `${label} – ${start}` });
      for (const container of type?.containers ?? []) {
        const children = node[container.key];
        if (Array.isArray(children)) walk(children as TreeNode[], depth + 1);
      }
    }
  };
  walk(nodes, 0);
  return lines;
}

/** Where an applied snippet's blocks landed and what they are. */
export interface InsertedBlocks {
  /** The list of blocks they went into (`["nodes"]`, `["nodes", 2, "children"]`). */
  list: Seg[];
  /** Their position in that list. */
  index: number;
  nodes: TreeNode[];
}

/**
 * Reads the blocks an applied snippet added from the tree the server returned.
 *
 * @param result An applied result (`ok`, with `tree` and `inserted_at`).
 * @returns The blocks and where they sit, or `null` when the result does not say.
 */
export function insertedBlocks(result: SnippetApplyResult): InsertedBlocks | null {
  if (!result.ok || result.tree === null || result.inserted_at === null) return null;
  const at = parsePath(result.inserted_at);
  const index = at[at.length - 1];
  if (typeof index !== "number") return null;
  const list = at.slice(0, -1);
  return { list, index, nodes: listAt(result.tree, list).slice(index, index + result.count) };
}

/**
 * The returned tree with `current`'s blocks in place of its own: every root-level change the snippet made (page styles,
 * variables) kept, the blocks left to the caller to insert one by one.
 */
export function withBlocksOf(result: Tree, current: Tree): Tree {
  return { ...result, nodes: current.nodes };
}
