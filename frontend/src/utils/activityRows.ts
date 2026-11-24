/**
 * Module: utils/activityRows
 *
 * The row model of the project activity table (`components/ProjectActivityTable`), shared by the project History page
 * and the overview's activity widget: an entry with a React key that does not depend on its position and whether it
 * opens a new local calendar day (a day is written once, on its first row).
 */
import type { ChangeEntry } from "../api/types";

/** One table row: the entry and whether it opens a new local day. */
export interface ActivityRow {
  key: string;
  entry: ChangeEntry;
  showDate: boolean;
}

/**
 * The local calendar day of an instant, for grouping rows.
 *
 * @param iso An ISO 8601 instant.
 * @returns `YYYY-M-D` in the browser's time zone.
 */
function localDay(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/**
 * The table rows of `entries`: each with a React key that does not depend on position (a reload that inserts a
 * newer event shifts nothing) and whether it is the first of its local day.
 *
 * @param entries The loaded entries, in display order.
 * @returns One row per entry, in the same order.
 */
export function toActivityRows(entries: ChangeEntry[]): ActivityRow[] {
  const seen = new Map<string, number>();
  return entries.map((entry, index) => {
    const base = `${entry.timestamp}|${entry.entity_type}|${entry.entity_id}|${entry.action}`;
    const occurrence = (seen.get(base) ?? 0) + 1;
    seen.set(base, occurrence);
    return {
      key: `${base}|${occurrence}`,
      entry,
      showDate: index === 0 || localDay(entry.timestamp) !== localDay(entries[index - 1].timestamp),
    };
  });
}
