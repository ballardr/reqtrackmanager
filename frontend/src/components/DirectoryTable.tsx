/**
 * Module: components/DirectoryTable
 *
 * A thin `<table>` shell shared by every "directory" list (Org Users, Org Groups, Project Groups, Project Members,
 * Access Review); see docs/ux-style-guide.md "Pattern: directories at scale" and "Pattern: sortable column header".
 * It renders a caller-supplied, already filtered, sorted and paginated `rows` array with `SortableHeader` for
 * `sortable` columns and `LoadMoreButton` for `total`/`onLoadMore`; it only calls `onSort(key)` and the caller owns
 * `sort` and passes new `rows` back. The first column's cell can be a keyboard-operable `<button>` (`onRowClick`) or
 * `<Link>` (`rowHref`, which wins: a link is bookmarkable), never a bare `<tr onClick>`. `selection` adds a leading
 * checkbox column whose header box selects every selectable row on the page and reports the chosen keys.
 * A column can hold a floor width (`minWidth`, the Name column's 12rem: its text wraps beyond it and the other columns
 * give way first, and it stays at the left edge when the table scrolls sideways), drop when the table is narrow (`hideBelow`)
 * and be chosen by the person (`optional`, `defaultHidden`: see `useOptionalColumns`, which filters the columns
 * before they reach this table). `rowAccent` draws the record type's accent stripe on each row. Excluded: a search box (`FilterPanel`'s own), `.side-grid` wrapping, an add slot and
 * any fetch or mutate logic.
 */
import { useEffect, useRef } from "react";
import type { JSX, ReactNode } from "react";
import { Link } from "react-router-dom";

import type { RecordReferencesApi } from "../api/externalReferences";
import { placementsText, type RecordPlacementsApi } from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { usePagePlacementsByType } from "../hooks/usePagePlacements";
import { usePageReferencesByType } from "../hooks/usePageReferences";

import { InlineCheckbox } from "./FormFields";
import { LoadMoreButton } from "./LoadMoreButton";
import { ReferencesCell } from "./ReferencesCell";
import { SortableHeader } from "./SortableHeader";
import type { SortState } from "./sortState";

/** Row selection for a bulk action: a leading column of checkboxes, with a box in the header that selects every row that can be. */
export interface DirectoryTableSelection<Row> {
  /** The keys (`rowKey`) of the selected rows. The caller owns the set. */
  selected: ReadonlySet<string>;
  /** Called with the new set when a box is ticked or cleared. */
  onChange: (next: Set<string>) => void;
  /** The box's accessible name for a row ("Select ELM-001"). */
  label: (row: Row) => string;
  /** A row that cannot be selected (another owner's record) shows no box; omit when every row can be. */
  selectable?: (row: Row) => boolean;
  /** The header box's accessible name (default "Select all rows"). */
  allLabel?: string;
}

export interface DirectoryColumn<Row> {
  key: string;
  label: ReactNode;
  /** Only for orderable columns (a name, a date), never a badge or actions column with no natural order
   * (style guide "Pattern: sortable column header"). */
  sortable?: boolean;
  /** A control that belongs to the column as a whole (a settings gear), drawn
   * beside the header text. It is a sibling of the sort button, not inside it,
   * so pressing it never changes the sort. */
  headerAction?: ReactNode;
  /** A CSS width (`"40%"`) for a column that should take a set share of the table; a column of long text
   * (a record's title) gets the room a short one (a badge) does not need. Applied to a plain header cell, so
   * it has no effect on a `sortable` column. */
  width?: string;
  render: (row: Row) => ReactNode;
  /** A floor width (a CSS length such as `"12rem"`) the column never shrinks below: the Name column's. The cell stays
   * at the left edge when the table scrolls sideways, so it needs a first column. */
  minWidth?: string;
  /** Drops the column while the table has less than 40rem of room (stacked cards below 720px keep every column), so
   * the columns that matter keep theirs. */
  hideBelow?: boolean;
  /** The person can show or hide this column (`useOptionalColumns`); a column that is not optional is always drawn. */
  optional?: boolean;
  /** An optional column that is off until the person chooses it. */
  defaultHidden?: boolean;
  /** The column's name in the column chooser when `label` is not plain text. */
  chooserLabel?: string;
}

/** The class and inline style a column's header and body cells share (floor width, narrow-width drop). */
function cellProps<Row>(column: DirectoryColumn<Row>): { className?: string; style?: { minWidth: string } } {
  const classes = [column.minWidth ? "directory-table-floor" : "", column.hideBelow ? "directory-table-wide" : ""].filter(Boolean).join(" ");
  return { className: classes || undefined, style: column.minWidth ? { minWidth: column.minWidth } : undefined };
}

/** The row ids on the page grouped by record type, for the Components column's read (one type unless the list mixes several). */
function placementIdsByType<Row>(
  rows: Row[],
  placements: { artefactType: string | ((row: Row) => string); rowId: (row: Row) => string } | undefined,
): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  if (!placements) return found;
  for (const row of rows) {
    const type = typeof placements.artefactType === "string" ? placements.artefactType : placements.artefactType(row);
    (found[type] ??= []).push(placements.rowId(row));
  }
  return found;
}

/**
 * Renders `rows` as a `<table>` (see the module docstring). It owns no data: sorting, pagination and search stay
 * with the caller.
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
  placements,
  selection,
  rowAccent,
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
  /** Called with a sortable column's `key` on that header's click; the caller re-sorts or refetches and passes
   * new `rows` and `sort` back. Omit to render every column as a plain, non-interactive `<th>`. */
  onSort?: (key: string) => void;
  /** Paired with `onLoadMore`, the same contract `LoadMoreButton` already
   * establishes elsewhere in the app. Omit both to render no pagination
   * control (e.g. an already-fully-loaded directory). */
  total?: number;
  onLoadMore?: () => void;
  /** Makes the first column's cell a `<button>` calling this with the clicked row. Mutually exclusive with
   * `rowHref`, which wins if both are passed. */
  onRowClick?: (row: Row) => void;
  /** Makes the first column's cell a `<Link>` to this href, for a bookmarkable, deep-linkable row. Takes priority
   * over `onRowClick`. */
  rowHref?: (row: Row) => string;
  /** Shown instead of the table when `rows` is empty. The caller decides
   * "nothing here yet" vs. "no results match this search/filter" copy —
   * only it knows whether a filter is currently active. */
  emptyState: ReactNode;
  /** Adds a Components column (where each row's record sits in the component tree) and an External references
   * column, each read for the whole page at once. A column appears only when a row has a value. `api` and
   * `referencesApi` are injectable for stories. */
  placements?: {
    projectId: string | undefined;
    /** The record type of the rows, or (a list of several types) a function giving each row's type. */
    artefactType: string | ((row: Row) => string);
    rowId: (row: Row) => string;
    api?: RecordPlacementsApi;
    referencesApi?: RecordReferencesApi;
    /** The sort keys of the Components and External references headers, when the list's server orders by them; the
     * headers are plain text without them. */
    sortKeys?: { places?: string; references?: string };
  };
  /** Adds a leading column of checkboxes for a bulk action; the caller owns the selected keys and the action itself. */
  selection?: DirectoryTableSelection<Row>;
  /** The record type's accent colour (`ENTITY_ACCENT_COLOR`), drawn as a stripe at the left edge of every row. */
  rowAccent?: string;
}): JSX.Element {
  const strings = useStrings();
  const placed = usePagePlacementsByType(placements?.projectId, placementIdsByType(rows, placements), placements?.api);
  const showPlacements = placements !== undefined && rows.some((r) => (placed[placements.rowId(r)] ?? []).length > 0);
  const referenced = usePageReferencesByType(placements?.projectId, placementIdsByType(rows, placements), placements?.referencesApi);
  const showReferences = placements !== undefined && rows.some((r) => (referenced[placements.rowId(r)] ?? []).length > 0);
  const selectAll = useRef<HTMLInputElement>(null);
  const choosable = selection ? rows.filter((r) => selection.selectable?.(r) ?? true) : [];
  const chosen = selection ? choosable.filter((r) => selection.selected.has(rowKey(r))).length : 0;
  // `indeterminate` is a DOM property only, so it is set after render: some, but not all, of the choosable rows are selected.
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = chosen > 0 && chosen < choosable.length;
  }, [chosen, choosable.length]);
  if (rows.length === 0) {
    return <>{emptyState}</>;
  }

  return (
    <div className="stack">
      <div className={columns.some((c) => c.hideBelow) ? "directory-table-scroll--responsive" : undefined} style={{ overflowX: "auto" }}>
        <table aria-label={ariaLabel}>
          <thead>
            <tr>
              {selection && (
                <th style={{ width: "2rem" }}>
                  <input
                    ref={selectAll} type="checkbox" aria-label={selection.allLabel ?? "Select all rows"}
                    checked={choosable.length > 0 && chosen === choosable.length} disabled={choosable.length === 0}
                    onChange={(e) => {
                      const next = new Set(selection.selected);
                      choosable.forEach((r) => (e.target.checked ? next.add(rowKey(r)) : next.delete(rowKey(r))));
                      selection.onChange(next);
                    }}
                  />
                </th>
              )}
              {columns.map((column) =>
                column.sortable && onSort ? (
                  <SortableHeader key={column.key} label={column.label} sortKey={column.key} sort={sort} onSort={onSort} action={column.headerAction} {...cellProps(column)} />
                ) : (
                  <th key={column.key} {...cellProps(column)} style={{ ...cellProps(column).style, ...(column.width ? { width: column.width } : {}) }}>
                    {column.headerAction ? <span className="th-with-action">{column.label}{column.headerAction}</span> : column.label}
                  </th>
                )
              )}
              {showPlacements && (placements?.sortKeys?.places && onSort
                ? <SortableHeader label={strings.placements.label} sortKey={placements.sortKeys.places} sort={sort} onSort={onSort} />
                : <th>{strings.placements.label}</th>)}
              {showReferences && (placements?.sortKeys?.references && onSort
                ? <SortableHeader label={strings.references.column} sortKey={placements.sortKeys.references} sort={sort} onSort={onSort} />
                : <th>{strings.references.column}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={rowAccent ? "entity-accent-row" : undefined}
                style={rowAccent ? { ["--entity-accent-color" as string]: rowAccent } : undefined}
              >
                {selection && (
                  <td>
                    {(selection.selectable?.(row) ?? true) && (
                      <InlineCheckbox
                        ariaLabel={selection.label(row)} checked={selection.selected.has(rowKey(row))}
                        onChange={(checked) => {
                          const next = new Set(selection.selected);
                          if (checked) next.add(rowKey(row));
                          else next.delete(rowKey(row));
                          selection.onChange(next);
                        }}
                      />
                    )}
                  </td>
                )}
                {columns.map((column, index) => (
                  <td key={column.key} {...cellProps(column)}>
                    {index === 0
                      ? renderFirstCell({ row, content: column.render(row), onRowClick, rowHref })
                      : column.render(row)}
                  </td>
                ))}
                {showPlacements && placements && (
                  <td>{placementsText(placed[placements.rowId(row)])}</td>
                )}
                {showReferences && placements && (
                  <td><ReferencesCell references={referenced[placements.rowId(row)]} /></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total !== undefined && onLoadMore && <LoadMoreButton loaded={rows.length} total={total} onClick={onLoadMore} />}
    </div>
  );
}

/** The first column's cell content, optionally wrapped in a `<Link>` or `<button>` (`rowHref` wins). Both use the
 * same `.directory-table-row-trigger` styling, so a navigating row and a panel-opening row look identical. */
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
