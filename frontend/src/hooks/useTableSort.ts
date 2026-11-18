/**
 * Module: hooks/useTableSort
 *
 * The sort of a `DirectoryTable` that holds its whole list in the browser and sits inside another page (an
 * administration panel, a card, a dialog), where the sort stays local so it leaves the page's own address alone.
 *
 * Responsibilities: keep the table's `SortState`, cycle it on a header click (unsorted, ascending, descending) and
 * return the rows in that order through `sortRows` (`useSortState` is the state alone, for rows built after an early return). A page-level list keeps its sort in the URL instead
 * (`useUrlSort`, docs/ux-style-guide.md "Pattern: sortable column header"); a paged list sorts on the server.
 */
import { useMemo, useState } from "react";

import { cycleSort, type SortState } from "../components/sortState";
import { sortRows, type SortValue } from "../utils/sortRows";

/**
 * The sort state alone, for a table whose rows only exist after the component's early returns; the caller orders them
 * with `sortRows`.
 *
 * @returns The sort (`null` for the default order) and the header-click handler to pass to `DirectoryTable`.
 */
export function useSortState(): { sort: SortState | null; onSort: (key: string) => void } {
  const [sort, setSort] = useState<SortState | null>(null);
  return { sort, onSort: (key) => setSort((current) => cycleSort(current, key)) };
}

/**
 * @param rows The rows in their default order.
 * @param values The sortable value of a row for each sortable column key; a stable object (module constant or memoised)
 *   keeps the sorted rows from being recomputed on every render.
 * @returns `rows` sorted by the current sort, the sort, and the header-click handler to pass to `DirectoryTable`.
 */
export function useTableSort<Row>(
  rows: Row[],
  values: Record<string, (row: Row) => SortValue>,
): { rows: Row[]; sort: SortState | null; onSort: (key: string) => void } {
  const { sort, onSort } = useSortState();
  const sorted = useMemo(() => sortRows(rows, sort, values), [rows, sort, values]);
  return { rows: sorted, sort, onSort };
}
