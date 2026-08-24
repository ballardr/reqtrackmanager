import { ArrowDown, ArrowUp } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

export type SortDirection = "asc" | "desc";

/** A table's current sort, or `null` for "unsorted" (the default order the
 * page would render with sorting turned off entirely). */
export interface SortState<K extends string = string> {
  key: K;
  direction: SortDirection;
}

/**
 * Style guide "Pattern: sortable column header" (2026-08 UX audit roadmap,
 * "Column-header sorting on data tables") — a clickable `<th>` that cycles
 * unsorted → ascending → descending → unsorted on click. Renders as a real
 * `<button>` inside the `<th>` (not a bare `<th onClick>`) so it's reachable
 * and operable by keyboard like every other control in the app, and sets
 * `aria-sort` on the `<th>` itself (the standard way screen readers learn a
 * table's current sort column/direction) rather than only relying on the
 * visible `ArrowUp`/`ArrowDown` icon, which is shown only on the currently
 * sorted column so it doesn't imply every other column is sortable too.
 *
 * Shared by every sortable data table in the app (`RequirementsPage`,
 * `ChangeRequestsPage`, `ProjectActionsPage`, Org Admin's Users table)
 * rather than hand-rolled per page — the audit's own Principle 4 ("one
 * component per pattern") was written specifically against the app
 * accumulating a fifth one-off version of a shape like this one.
 */
export function SortableHeader<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  style,
}: {
  label: ReactNode;
  sortKey: K;
  sort: SortState<K> | null;
  onSort: (key: K) => void;
  style?: CSSProperties;
}) {
  const direction = sort?.key === sortKey ? sort.direction : null;
  const ariaSort = direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none";
  return (
    <th style={style} aria-sort={ariaSort}>
      {/* No `aria-label` here deliberately: the WAI-ARIA APG "sortable
          table" pattern this follows puts the sort state on the `<th>`'s
          `aria-sort` (above) and leaves the button's accessible name as
          just the plain column text — an `aria-label` on the button would
          otherwise replace that text in the `<th>`'s own computed name
          (accessible-name-from-content substitutes a labelled descendant's
          label for its content), silently renaming the columnheader from
          e.g. "ID" to "Sort by ID" for every assistive-tech user and any
          `getByRole("columnheader", { name })` query alike. */}
      <button type="button" className="th-sort" onClick={() => onSort(sortKey)}>
        <span>{label}</span>
        {direction === "asc" && <ArrowUp size={14} aria-hidden="true" />}
        {direction === "desc" && <ArrowDown size={14} aria-hidden="true" />}
      </button>
    </th>
  );
}

/** Cycles a table's `SortState` for a header click on `key`: unsorted →
 * ascending → descending → unsorted. Shared so every table's click handler
 * behaves identically rather than each page reimplementing the cycle. */
export function cycleSort<K extends string>(current: SortState<K> | null, key: K): SortState<K> | null {
  if (!current || current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return null;
}
