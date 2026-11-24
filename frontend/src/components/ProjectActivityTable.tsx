/**
 * Module: components/ProjectActivityTable
 *
 * The one table of a project's activity: Time, Type, Event, Record(s) and Person, one row per `ChangeEntry`. The
 * project History page (sorted, filtered, paged) and the overview's activity widget (a capped feed) both draw it,
 * so the same event reads the same in both: the event wording (`describeActivityAction`, `describeLinkEventAction`),
 * the notes typed with the change, the record link or the two ends of a link event, and the person.
 *
 * Responsibilities: drawing the table with the columns from `hooks/useActivityColumns` (every column unless the page
 * passes its chosen set: the History page offers a column chooser, the widget keeps every column), and the narrow
 * form. With `stacks` the table measures its own container, not the window, and below 34rem each row becomes a block (type, time and person on the first
 * line, then the event and the record), because the widget sits in a card of any width. A table that sorts keeps its
 * header, so it does not stack.
 * Design decisions: a day is written once, on its first row (`utils/activityRows`); user text in a cell is shown with
 * `CellText` (see the columns), so it never changes the table's shape.
 * Dependencies: `DirectoryTable`, `useActivityColumns`, the `.activity-table*` rules in `styles/theme.css`.
 */
import type { ReactNode } from "react";

import { useActivityColumns } from "../hooks/useActivityColumns";
import type { ActivityRow } from "../utils/activityRows";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import type { SortState } from "./sortState";

/**
 * Draws the activity table.
 *
 * @param rows The rows to show (`toActivityRows`), already in display order.
 * @param projectId The project whose activity it is (a record in another project is named with its project).
 * @param columns The columns to draw (`useActivityColumnChoice` in `hooks/useActivityColumns`); omit to draw every column.
 * @param ariaLabel The table's accessible name.
 * @param emptyState Shown when there are no rows.
 * @param stacks Whether a narrow container stacks each row (a table without sorting).
 * @param sort The table's sort, with `onSort`; omit both for an unsorted table.
 * @param onSort Called with the key of the sortable column whose header was pressed.
 * @param total The number of entries on the server, with `onLoadMore`; omit both for a table with no "Show more".
 * @param onLoadMore Loads the next page.
 */
export function ProjectActivityTable({
  rows, projectId, columns, ariaLabel, emptyState, stacks = false, sort = null, onSort, total, onLoadMore,
}: {
  rows: ActivityRow[];
  projectId: string | undefined;
  columns?: DirectoryColumn<ActivityRow>[];
  ariaLabel: string;
  emptyState: ReactNode;
  stacks?: boolean;
  sort?: SortState | null;
  onSort?: (key: string) => void;
  total?: number;
  onLoadMore?: () => void;
}) {
  const allColumns = useActivityColumns(projectId, onSort !== undefined);

  const table = (
    <DirectoryTable
      ariaLabel={ariaLabel} columns={columns ?? allColumns} rows={rows} rowKey={(row) => row.key} sort={sort} onSort={onSort}
      total={total} onLoadMore={onLoadMore} emptyState={emptyState}
    />
  );
  return stacks ? <div className="activity-table activity-table--stacks">{table}</div> : table;
}
