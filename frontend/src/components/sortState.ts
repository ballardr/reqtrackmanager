/**
 * Module: components/sortState
 *
 * `SortState`/`SortDirection`/`cycleSort` split out of `SortableHeader.tsx`
 * so that file can keep exporting only the `SortableHeader` component — a
 * file mixing component and non-component exports breaks Fast Refresh
 * (react-refresh/only-export-components). Unlike this codebase's context
 * modules (which colocate a Provider component with its paired hook via
 * the lint config's own `allowExportNames` escape hatch), `SortableHeader`
 * has no paired hook of its own — `cycleSort` is a plain state-transition
 * helper shared by every page's own click handler — so it gets a real file
 * split instead.
 */

export type SortDirection = "asc" | "desc";

/** A table's current sort, or `null` for "unsorted" (the default order the
 * page would render with sorting turned off entirely). */
export interface SortState<K extends string = string> {
  key: K;
  direction: SortDirection;
}

/** Cycles a table's `SortState` for a header click on `key`: unsorted →
 * ascending → descending → unsorted. Shared so every table's click handler
 * behaves identically rather than each page reimplementing the cycle. */
export function cycleSort<K extends string>(current: SortState<K> | null, key: K): SortState<K> | null {
  if (!current || current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return null;
}
