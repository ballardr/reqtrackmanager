/**
 * Module: components/DirectoryTable
 *
 * A generic, deliberately thin `<table>` shell shared by every "directory"
 * list in the app (Org Users, Org Groups, Project Groups, Project Members,
 * Server Admin's Access Review) — see docs/ux-style-guide.md's "Pattern:
 * directories at scale" and "Pattern: sortable column header". Pulled out
 * as Phase 0 of a follow-up UX batch after a design-review pass found four
 * separate pages about to each hand-roll their own version of the exact
 * shape `MemberRoleTable.tsx` already proved out (see that component's own
 * docstring) — and that the *existing* Project Groups list wasn't a real
 * `<table>` at all, just a `<button>` per row with no `SortableHeader`.
 *
 * Responsibilities:
 * - Renders a real `<table>`/`<thead>`/`<tbody>` over a caller-supplied,
 *   already-filtered/sorted/paginated `rows` array, using `SortableHeader`
 *   for any column marked `sortable` (reusing its `aria-sort` handling
 *   rather than reimplementing it) and `LoadMoreButton` when the caller
 *   passes `total`/`onLoadMore`.
 * - Optionally makes the first column's cell content a real, keyboard-
 *   operable `<button>` (`onRowClick`) or `<Link>` (`rowHref`) — never a
 *   bare `<tr onClick>`, which has no role and isn't reachable by keyboard.
 *   `onRowClick` and `rowHref` are mutually exclusive; if a caller somehow
 *   passes both, `rowHref` wins — a `<Link>` is strictly more capable
 *   (bookmarkable, deep-linkable, openable in a new tab) than a plain click
 *   handler for row navigation, so there's no case where preferring
 *   `onRowClick` instead would be the better silent choice.
 *
 * Deliberately excluded (each already has a better home elsewhere; folding
 * these in would duplicate or misplace them):
 * - No search box — that's `FilterPanel`'s own `search`/`onSearchChange`
 *   header prop, composed beside this component in a `.side-grid` layout by
 *   every real call site, not inside it. Avoids the exact duplicate-search-
 *   input shape `MemberRoleTable` had before this component existed.
 * - No `.side-grid`/`FilterPanel` wrapping — callers compose those
 *   themselves; this component renders inside the content column only.
 * - No "add"/"create" control slot — callers render their own controls
 *   (e.g. "New group", "Invite user", "Add member") as siblings above this
 *   component, same as every call site does today.
 * - No fetch/mutate/merge logic of any kind — 100% presentational over
 *   whatever `rows` the caller already has ready to render. Sorting is the
 *   same contract: this component only calls `onSort(key)` on a header
 *   click — the caller owns `sort` state and decides how to re-sort
 *   (refetch or re-slice), then passes new `rows` back in.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { LoadMoreButton } from "./LoadMoreButton";
import { SortableHeader, type SortState } from "./SortableHeader";

export interface DirectoryColumn<Row> {
  key: string;
  label: ReactNode;
  /** Only for genuinely orderable columns (a name, a date) — never a
   * badge/actions-only column with no natural order, per style guide
   * "Pattern: sortable column header"'s "sortable columns are the obvious
   * ones only" rule. */
  sortable?: boolean;
  render: (row: Row) => ReactNode;
}

/**
 * Renders `rows` as a `<table>`. See the module docstring for the full
 * contract — in short, this component owns none of the data: sorting,
 * pagination, and search all stay caller-side, this just presents the
 * result.
 */
export function DirectoryTable<Row>({
  ariaLabel,
  columns,
  rows,
  rowKey,
  sort = null,
  onSort,
  total,
  onLoadMore,
  onRowClick,
  rowHref,
  emptyState,
}: {
  /** Accessible name for the `<table>` itself. */
  ariaLabel: string;
  columns: DirectoryColumn<Row>[];
  /** Already filtered/sorted/paginated by the caller — this component
   * renders exactly this array, nothing more. */
  rows: Row[];
  /** React list key for each row. */
  rowKey: (row: Row) => string;
  /** The table's current sort, or `null`/omitted for unsorted. Has no
   * effect unless `onSort` is also provided. */
  sort?: SortState | null;
  /** Called with a sortable column's `key` on that header's click — the
   * caller re-sorts/refetches and passes new `rows` (and, typically, a new
   * `sort`) back in; this component doesn't cycle or apply sort itself.
   * Omit to render every column (even ones marked `sortable`) as a plain,
   * non-interactive `<th>`. */
  onSort?: (key: string) => void;
  /** Paired with `onLoadMore`, the same contract `LoadMoreButton` already
   * establishes elsewhere in the app. Omit both to render no pagination
   * control (e.g. an already-fully-loaded directory). */
  total?: number;
  onLoadMore?: () => void;
  /** Makes the first column's cell a real `<button>` calling this with the
   * clicked row, instead of plain (non-interactive) cell content. Mutually
   * exclusive with `rowHref` — see module docstring for which wins if both
   * are passed. */
  onRowClick?: (row: Row) => void;
  /** Makes the first column's cell a real `<Link>` to this href instead of
   * a click handler — for a bookmarkable, deep-linkable row (e.g. an
   * `?openGroup=`-style flow). Takes priority over `onRowClick` if both are
   * passed. */
  rowHref?: (row: Row) => string;
  /** Shown instead of the table when `rows` is empty. The caller decides
   * "nothing here yet" vs. "no results match this search/filter" copy —
   * only it knows whether a filter is currently active. */
  emptyState: ReactNode;
}): JSX.Element {
  if (rows.length === 0) {
    return <>{emptyState}</>;
  }

  return (
    <div className="stack">
      <div style={{ overflowX: "auto" }}>
        <table aria-label={ariaLabel}>
          <thead>
            <tr>
              {columns.map((column) =>
                column.sortable && onSort ? (
                  <SortableHeader key={column.key} label={column.label} sortKey={column.key} sort={sort} onSort={onSort} />
                ) : (
                  <th key={column.key}>{column.label}</th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column, index) => (
                  <td key={column.key}>
                    {index === 0
                      ? renderFirstCell({ row, content: column.render(row), onRowClick, rowHref })
                      : column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total !== undefined && onLoadMore && <LoadMoreButton loaded={rows.length} total={total} onClick={onLoadMore} />}
    </div>
  );
}

/** The first column's cell content, optionally wrapped in a real `<Link>`
 * or `<button>` — see the component docstring for the `rowHref`-wins-over-
 * `onRowClick` rule. Both render with the same `.directory-table-row-
 * trigger` styling (theme.css) so a row that navigates and a row that opens
 * a panel look identical, regardless of which element renders it. */
function renderFirstCell<Row>({
  row,
  content,
  onRowClick,
  rowHref,
}: {
  row: Row;
  content: ReactNode;
  onRowClick: ((row: Row) => void) | undefined;
  rowHref: ((row: Row) => string) | undefined;
}): ReactNode {
  if (rowHref) {
    return (
      <Link to={rowHref(row)} className="directory-table-row-trigger">
        {content}
      </Link>
    );
  }
  if (onRowClick) {
    return (
      <button type="button" className="directory-table-row-trigger" onClick={() => onRowClick(row)}>
        {content}
      </button>
    );
  }
  return content;
}
