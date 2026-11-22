/**
 * Module: modules/architecture/symbolLibraryActions
 *
 * The pure parts of what one symbol of the library page is drawn with, shared by the table and the tile view: where a symbol
 * came from, how a count reads, and the actions of a row (Rename, Move up, Move down and Delete, Hide in a project for an
 * organisation symbol), each present only where it applies (never disabled).
 */
import type { ActionMenuItem } from "../../components/ActionMenu";
import { SYMBOL_FILE_TYPE_LABEL, type SymbolLibraryRow } from "./types";

/** Where a symbol came from: Built-in, Uploaded, or Uploaded as an EPS or PDF (converted when it was stored). */
export function sourceText(row: SymbolLibraryRow): string {
  if (row.is_builtin) return "Built-in";
  return row.file_type === "eps" || row.file_type === "pdf" ? `Uploaded (${SYMBOL_FILE_TYPE_LABEL[row.file_type]})` : "Uploaded";
}

/** "1 record" / "5 records". */
export function recordsText(n: number): string {
  return `${n} ${n === 1 ? "record" : "records"}`;
}

/** What a row's actions need from the page. */
export interface SymbolRowActionContext {
  /** Whether the page is a project's. */
  inProject: boolean;
  /** Whether the list is in the library's own order, unfiltered: the only state where a symbol can be moved up or down. */
  reorderable: boolean;
  onRename: (row: SymbolLibraryRow) => void;
  onMove: (row: SymbolLibraryRow, direction: "up" | "down") => void;
  onDelete: (row: SymbolLibraryRow) => void;
}

/**
 * The actions of one symbol, for its `ActionMenu`.
 *
 * @param row The symbol.
 * @param context What the page offers.
 * @returns The rows that apply: none for a built-in's rename, none of Move for another tier's symbol in a project.
 */
export function symbolRowActions(row: SymbolLibraryRow, context: SymbolRowActionContext): ActionMenuItem[] {
  const orgRowInProject = context.inProject && row.tier === "organization";
  const items: ActionMenuItem[] = [];
  if (!row.is_builtin && !orgRowInProject) items.push({ key: "rename", label: "Rename", onSelect: () => context.onRename(row) });
  if (context.reorderable && !orgRowInProject) {
    items.push(
      { key: "up", label: "Move up", onSelect: () => context.onMove(row, "up") },
      { key: "down", label: "Move down", onSelect: () => context.onMove(row, "down") },
    );
  }
  items.push({
    key: "delete", danger: true, onSelect: () => context.onDelete(row),
    label: orgRowInProject ? "Hide symbol in this project" : "Delete symbol",
  });
  return items;
}
