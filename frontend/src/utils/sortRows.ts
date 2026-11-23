/**
 * Module: utils/sortRows
 *
 * Client-side sorting of an already-loaded table for the shared `DirectoryTable`'s sort state; a paged table sorts on
 * the server instead.
 *
 * Responsibilities: order rows by one column's value, ascending or descending, or leave the order untouched with no
 * sort. Text compares case-insensitively and by locale (digit runs by value, so `ELM-9` precedes `ELM-10`), numbers
 * numerically, and an empty value sorts last in ascending order.
 */
import type { SortState } from "../components/sortState";

/** A column's sortable value: text, a number, or `null` when the row has none. */
export type SortValue = string | number | null;

/**
 * @param rows The rows, in their default order.
 * @param sort The table's sort, or `null` for the default order.
 * @param values The sortable value of a row for each sortable column key.
 * @returns A new array in the sorted order (the same rows when `sort` is `null` or its key has no accessor).
 */
export function sortRows<Row>(rows: Row[], sort: SortState | null, values: Record<string, (row: Row) => SortValue>): Row[] {
  const valueOf = sort ? values[sort.key] : undefined;
  if (!sort || !valueOf) return rows;
  const direction = sort.direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const left = valueOf(a);
    const right = valueOf(b);
    if (left === null || right === null) return left === right ? 0 : left === null ? direction : -direction;
    if (typeof left === "number" && typeof right === "number") return (left - right) * direction;
    return String(left).localeCompare(String(right), undefined, { sensitivity: "base", numeric: true }) * direction;
  });
}

/**
 * The `created` and `modified` sort values every record list offers (`TIME_SORT_KEYS` in `hooks/useListSort.ts`), for any
 * row that carries `created_at` and `updated_at`: spread into the list's own values (`{ ...TIME_SORT_VALUES, code: ... }`).
 * A row with no `updated_at` is ordered by its creation time.
 */
export const TIME_SORT_VALUES: Record<"created" | "modified", (row: { created_at?: string; updated_at?: string | null }) => number | null> = {
  created: (row) => instantOf(row.created_at),
  modified: (row) => instantOf(row.updated_at ?? row.created_at),
};

/** @param value An ISO 8601 instant, or nothing. @returns Milliseconds since the epoch, or `null` when there is none. */
export function instantOf(value: string | null | undefined): number | null {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? null : parsed;
}
