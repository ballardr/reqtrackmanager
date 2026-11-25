/**
 * Module: utils/reportSnippetSelection
 *
 * Pure helpers that turn a designer selection into the run of blocks "Save as snippet" saves.
 *
 * Responsibilities:
 * - Blocks view: a block's tree path becomes `{ container, start, count: 1 }` (`selectionOfBlock`).
 * - Text view: the selected lines (or the caret's line) become the top-level blocks they touch, using the block start
 *   lines of the server's parse (`selectionFromLines`).
 *
 * Design decisions: the Text view saves whole top-level blocks only; nested blocks are saved from the Blocks view. The
 * server validates the result, so nothing here judges validity.
 */
import type { SnippetSelection } from "../api/reportSnippets";
import { formatPath, type Seg } from "./reportLayoutTree";

/**
 * The selection for the block at `path` (`["nodes", 2, "children", 0]`).
 *
 * @returns The block as a run of one in its list, or `null` for a path that does not end in an index.
 */
export function selectionOfBlock(path: Seg[]): SnippetSelection | null {
  const index = path[path.length - 1];
  if (typeof index !== "number" || path.length < 2) return null;
  return { container: formatPath(path.slice(0, -1)), start: index, count: 1 };
}

/**
 * The top-level blocks that lines `firstLine` to `lastLine` (1-based, inclusive) touch.
 *
 * Each block runs from the line it starts on to the line before the next one starts; the last block runs to the end of the
 * text. Lines before the first block (the layout line, page styles, variables) touch nothing.
 *
 * @param blockLines The parse's `block_lines`, by tree path.
 * @param firstLine The first selected line.
 * @param lastLine The last selected line (the same as `firstLine` for a caret).
 * @returns A run of top-level blocks, or `null` when the lines touch none.
 */
export function selectionFromLines(blockLines: Readonly<Record<string, number>>, firstLine: number, lastLine: number): SnippetSelection | null {
  const starts = Object.entries(blockLines)
    .map(([path, line]) => ({ match: /^nodes\[(\d+)\]$/.exec(path), line }))
    .flatMap(({ match, line }) => (match ? [{ index: Number(match[1]), line }] : []))
    .sort((a, b) => a.index - b.index);
  const touched = starts.filter((block, i) => block.line <= lastLine && (i + 1 === starts.length || starts[i + 1].line > firstLine));
  if (touched.length === 0) return null;
  return { container: "nodes", start: touched[0].index, count: touched.length };
}
