/**
 * Module: utils/sortRows
 *
 * Client-side sorting of an already-loaded table for the shared `DirectoryTable`'s sort state. Used by tables that hold
 * their whole list in the browser (a short administrative list); a paged table sorts on the server instead.
 *
 * Responsibilities: order rows by one column's value, ascending or descending; leave the order untouched when there is
 * no sort. Text compares case-insensitively and by locale (digit runs by value, so `ELM-9` precedes `ELM-10`), numbers numerically, and an empty value sorts last in
 * ascending order.
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
