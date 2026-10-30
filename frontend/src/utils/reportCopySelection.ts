/**
 * Module: utils/reportCopySelection
 *
 * Which rows of the Report setup list can be copied to another project, and what a set of ticked rows and folders adds up
 * to for the copy request.
 *
 * Responsibilities: `isCopyable` (a layout or pack the project can reach and has not hidden, or a module report the
 * project itself placed), `copyItems` (ticked rows and folders to the request's ids and keys) and `copyCount`.
 *
 * Design decisions: a report that only follows a parent's or the organisation's setup (a module report with no setting of this
 * project's own) has nothing to copy, so it cannot be ticked; a shared layout or pack can, and arrives as the target's own.
 * Pure functions over plain data.
 */
import type { CopyItems } from "../api/reportCopy";
import type { ReportSetupRow } from "./reportSetupRows";

/** Whether a row can be ticked for copying. */
export function isCopyable(row: ReportSetupRow): boolean {
  if (row.hidden) return false;
  if (row.type === "module") return row.ownFolder !== null || row.ownHidden !== null;
  return true;
}

/**
 * @param rows Every row of the list.
 * @param pickedKeys The ticked rows' keys.
 * @param pickedFolders The ticked folders' paths.
 * @returns The request's selection, in list order.
 */
export function copyItems(rows: ReportSetupRow[], pickedKeys: ReadonlySet<string>, pickedFolders: readonly string[]): CopyItems {
  const chosen = rows.filter((row) => pickedKeys.has(row.key) && isCopyable(row));
  return {
    layout_ids: chosen.flatMap((r) => (r.layout ? [r.layout.id] : [])),
    pack_ids: chosen.flatMap((r) => (r.pack ? [r.pack.id] : [])),
    folders: [...pickedFolders],
    placement_keys: chosen.filter((r) => r.type === "module").map((r) => r.key),
  };
}

/** How many things a selection holds. */
export function copyCount(items: CopyItems): number {
  return items.layout_ids.length + items.pack_ids.length + items.folders.length + items.placement_keys.length;
}
