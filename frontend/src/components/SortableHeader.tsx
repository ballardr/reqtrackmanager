import { ArrowDown, ArrowUp } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import type { SortState } from "./sortState";

/**
 * Style guide "Pattern: sortable column header": a clickable `<th>` that cycles unsorted, ascending, descending,
 * unsorted on click. It renders a real `<button>` inside the `<th>` so it is keyboard operable, and sets `aria-sort` on
 * the `<th>` (how screen readers learn the sort state) rather than relying on the `ArrowUp`/`ArrowDown` icon, which
 * shows only on the sorted column.
 *
 * Shared by every sortable data table (one component per pattern, not a version per page).
 *
 * `action` is a control that belongs to the column (a settings gear). It sits beside the sort button inside the `<th>`,
 * never inside the button (a button in a button is invalid HTML and would break keyboard sorting), so using it never
 * changes the sort.
 */
export function SortableHeader<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  style,
  className,
  action,
}: {
  label: ReactNode;
  sortKey: K;
  sort: SortState<K> | null;
  onSort: (key: K) => void;
  style?: CSSProperties;
  /** A class on the `<th>` (a column that drops at narrow widths or holds a floor width). */
  className?: string;
  action?: ReactNode;
}) {
  const direction = sort?.key === sortKey ? sort.direction : null;
  const ariaSort = direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none";
  const sortButton = (
    <button type="button" className="th-sort" onClick={() => onSort(sortKey)}>
      <span>{label}</span>
      {direction === "asc" && <ArrowUp size={14} aria-hidden="true" />}
      {direction === "desc" && <ArrowDown size={14} aria-hidden="true" />}
    </button>
  );
  return (
    <th style={style} className={className} aria-sort={ariaSort}>
      {/* No `aria-label` here: the WAI-ARIA APG "sortable table" pattern puts the sort state on the `<th>`'s `aria-sort`
          and leaves the button's accessible name as the plain column text. An `aria-label` on the button would replace
          that text in the `<th>`'s computed name and rename the columnheader (e.g. "ID" to "Sort by ID"). */}
      {action ? (
        <span className="th-with-action">
          {sortButton}
          {action}
        </span>
      ) : sortButton}
    </th>
  );
}
