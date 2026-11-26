/**
 * Module: modules/traceability/PolicyTable
 *
 * The one table every Governance policy screen draws: a row per record type (a lifecycle, an approval gate, a review
 * schedule) with the policy's own columns after the type's name and one row menu at the end, so a profile's tab and a
 * project's section read the same.
 *
 * Responsibilities:
 * - Order the rows with a header click, the sort kept in the address (`useUrlSort`), every data column sortable.
 * - Offer the row menu only when the row has an action (a person who cannot manage sees a read-only table).
 * - Show `emptyText` when no record type of the organisation has such a policy.
 * - Offer the column chooser (`useOptionalColumns`) when the caller marks columns `optional` and names the table
 *   (`chooserKey`), so a table of five or more data columns lets a person hide the ones they do not need.
 *
 * Design decisions: the table is a `DirectoryTable`; the caller supplies each column's cell and its sort value, so a
 * cell and its order always agree. A row's one action ("Edit ...") opens the caller's dialog; the table owns no edit state.
 */
import type { ReactNode } from "react";

import { ActionMenu, type ActionMenuItem } from "../../components/ActionMenu";
import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { cycleSort, type SortState } from "../../components/sortState";
import { useOptionalColumns } from "../../hooks/useOptionalColumns";
import { useUrlSort } from "../../hooks/useUrlFilter";
import { sortRows, type SortValue } from "../../utils/sortRows";

/** A column after the type's name. */
export interface PolicyColumn<Row> {
  key: string;
  label: string;
  render: (row: Row) => ReactNode;
  /** The value the column is ordered by; it matches what the cell shows. */
  sortValue: (row: Row) => SortValue;
  /** A CSS width for a column of short values (a number of days). */
  width?: string;
  /** The person can hide the column; it is listed in the column chooser. */
  optional?: boolean;
  /** An optional column that is off until the person chooses it. */
  defaultHidden?: boolean;
}

/** The row every policy table holds: a registered record type. */
export interface PolicyRow {
  artefact_type: string;
  label: string;
}

/**
 * @param ariaLabel The table's accessible name ("Approval policy by record type").
 * @param rows One row per record type, in the order the API returned them.
 * @param columns The policy's own columns, after the type's name.
 * @param rowMenu The row's menu items (`Edit approvers`), or `null` for a row with none; the whole menu is left out when no row has one.
 * @param rowMenuLabel The row menu's accessible name, which names the row (`Actions for Decision`).
 * @param emptyText The empty state, shown when there are no rows.
 * @param chooserKey Names the table for the column chooser, which remembers each person's choice; required when a column is `optional`.
 */
export function PolicyTable<Row extends PolicyRow>({
  ariaLabel, rows, columns, rowMenu, rowMenuLabel, emptyText, chooserKey,
}: {
  ariaLabel: string;
  rows: Row[];
  columns: PolicyColumn<Row>[];
  rowMenu?: (row: Row) => ActionMenuItem[] | null;
  rowMenuLabel?: (row: Row) => string;
  emptyText: string;
  chooserKey?: string;
}) {
  const keys = ["type", ...columns.map((c) => c.key)] as const;
  const [sort, setSort] = useUrlSort(keys);
  const values: Record<string, (row: Row) => SortValue> = { type: (row) => row.label };
  for (const column of columns) values[column.key] = column.sortValue;
  const sorted = sortRows(rows, sort, values);
  const hasMenu = rowMenu !== undefined && rows.some((row) => (rowMenu(row) ?? []).length > 0);

  const tableColumns: DirectoryColumn<Row>[] = [
    { key: "type", label: "Record type", sortable: true, minWidth: "10rem", render: (row) => <CellText lines={2}>{row.label}</CellText> },
    ...columns.map((column): DirectoryColumn<Row> => ({
      key: column.key, label: column.label, sortable: true, width: column.width, render: column.render,
      optional: column.optional, defaultHidden: column.defaultHidden,
    })),
  ];
  if (hasMenu && rowMenu) {
    tableColumns.push({
      key: "actions",
      label: <span className="sr-only">Actions</span>,
      width: "3rem",
      render: (row) => {
        const items = rowMenu(row) ?? [];
        return items.length > 0 ? <ActionMenu triggerLabel={rowMenuLabel?.(row) ?? `Actions for ${row.label}`} items={items} /> : null;
      },
    });
  }

  const body = { ariaLabel, rows: sorted, sort, onSort: (key: string) => setSort((current) => cycleSort(current, key as (typeof keys)[number])), emptyText };
  return chooserKey
    ? <ChosenColumnsTable {...body} chooserKey={chooserKey} columns={tableColumns} />
    : <TableBody {...body} columns={tableColumns} chooser={null} />;
}

/** The table with the column chooser bound to its optional columns (`useOptionalColumns` needs the person's preferences). */
function ChosenColumnsTable<Row extends PolicyRow>({ chooserKey, columns, ...body }: Omit<BodyProps<Row>, "chooser"> & { chooserKey: string }) {
  const shown = useOptionalColumns(chooserKey, columns);
  return <TableBody {...body} columns={shown.columns} chooser={shown.chooser} />;
}

interface BodyProps<Row> {
  ariaLabel: string;
  rows: Row[];
  columns: DirectoryColumn<Row>[];
  sort: SortState | null;
  onSort: (key: string) => void;
  emptyText: string;
  chooser: ReactNode;
}

/** The chooser above the shared table. */
function TableBody<Row extends PolicyRow>({ ariaLabel, rows, columns, sort, onSort, emptyText, chooser }: BodyProps<Row>) {
  return (
    <div className="stack">
      {chooser && <div className="row" style={{ justifyContent: "flex-end" }}>{chooser}</div>}
      <DirectoryTable
        ariaLabel={ariaLabel}
        columns={columns}
        rows={rows}
        rowKey={(row) => row.artefact_type}
        sort={sort}
        onSort={onSort}
        emptyState={<p className="text-muted">{emptyText}</p>}
        />
    </div>
  );
}
