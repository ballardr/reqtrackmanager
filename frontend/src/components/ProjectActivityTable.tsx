/**
 * Module: components/ProjectActivityTable
 *
 * The one table of a project's activity: Time, Type, Event, Record(s) and Person, one row per `ChangeEntry`. The
 * project History page (sorted, filtered, paged) and the overview's activity widget (a capped feed) both draw it,
 * so the same event reads the same in both: the event wording (`describeActivityAction`, `describeLinkEventAction`),
 * the notes typed with the change, the record link or the two ends of a link event, and the person.
 *
 * Responsibilities: the column definitions and cell renderers, and the narrow form. With `stacks` the table measures
 * its own container, not the window, and below 34rem each row becomes a block (type, time and person on the first
 * line, then the event and the record), because the widget sits in a card of any width. A table that sorts keeps its
 * header, so it does not stack.
 * Design decisions: user text (event, record, person) is shown with `CellText`, so a long title or an unbroken word
 * never changes the table's shape; a day is written once, on its first row (`utils/activityRows`).
 * Dependencies: `DirectoryTable`, `CellText`, `ActivityLinkEnds`, `ActivityNote`, the `.activity-table*` rules in
 * `styles/theme.css`.
 */
import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import {
  activityEntityLabel, activityEntryNotes, describeActivityAction, describeLinkEventAction, linkEventVerb, sentenceCase,
} from "../api/types";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { activityRecordLink } from "../utils/activityLink";
import type { ActivityRow } from "../utils/activityRows";
import { ActivityLinkEnds } from "./ActivityLinkEnds";
import { ActivityNote } from "./ActivityNote";
import { Badge } from "./Badge";
import { CellText } from "./CellText";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import type { SortState } from "./sortState";

/**
 * Draws the activity table.
 *
 * @param rows The rows to show (`toActivityRows`), already in display order.
 * @param projectId The project whose activity it is (a record in another project is named with its project).
 * @param ariaLabel The table's accessible name.
 * @param emptyState Shown when there are no rows.
 * @param stacks Whether a narrow container stacks each row (a table without sorting).
 * @param sort The table's sort, with `onSort`; omit both for an unsorted table.
 * @param onSort Called with the key of the sortable column whose header was pressed.
 * @param total The number of entries on the server, with `onLoadMore`; omit both for a table with no "Show more".
 * @param onLoadMore Loads the next page.
 */
export function ProjectActivityTable({
  rows, projectId, ariaLabel, emptyState, stacks = false, sort = null, onSort, total, onLoadMore,
}: {
  rows: ActivityRow[];
  projectId: string | undefined;
  ariaLabel: string;
  emptyState: ReactNode;
  stacks?: boolean;
  sort?: SortState | null;
  onSort?: (key: string) => void;
  total?: number;
  onLoadMore?: () => void;
}) {
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();

  const columns: DirectoryColumn<ActivityRow>[] = [
    {
      key: "time",
      label: strings.history.columnTime,
      sortable: onSort !== undefined,
      render: ({ entry, showDate }) => (
        <time dateTime={entry.timestamp} className="activity-table__time" style={{ whiteSpace: "nowrap" }}>
          {showDate && <strong className="activity-table__day">{new Date(entry.timestamp).toLocaleDateString(undefined, { dateStyle: "medium" })}</strong>}
          <span className="text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
        </time>
      ),
    },
    {
      key: "type",
      label: strings.history.columnType,
      render: ({ entry }) => <Badge>{activityEntityLabel(entry.entity_type, orgLabelCap)}</Badge>,
    },
    {
      key: "event",
      label: strings.history.columnEvent,
      width: "28%",
      render: ({ entry }) => (
        <span className="stack" style={{ gap: "0.15rem" }}>
          <CellText lines={3}>{sentenceCase(describeLinkEventAction(entry) ?? describeActivityAction(entry, projectId))}</CellText>
          {activityEntryNotes(entry).map((note) => <ActivityNote key={note} text={note} />)}
        </span>
      ),
    },
    {
      key: "record",
      label: strings.history.columnRecord,
      width: "42%",
      render: ({ entry }) => {
        if (projectId && linkEventVerb(entry) !== null) return <ActivityLinkEnds entry={entry} projectId={projectId} />;
        const link = projectId ? activityRecordLink(entry, projectId) : null;
        if (link) return <Link to={link.to}><CellText lines={2}>{link.label}</CellText></Link>;
        return entry.record_label ? <CellText lines={2}>{entry.record_label}</CellText> : <span className="text-muted">—</span>;
      },
    },
    {
      key: "person",
      label: strings.history.columnPerson,
      render: ({ entry }) => (
        entry.actor_display_name
          ? <CellText maxWidth="14rem">{entry.actor_display_name}</CellText>
          : <span className="text-muted">{strings.history.unnamedActor}</span>
      ),
    },
  ];

  const table = (
    <DirectoryTable
      ariaLabel={ariaLabel} columns={columns} rows={rows} rowKey={(row) => row.key} sort={sort} onSort={onSort}
      total={total} onLoadMore={onLoadMore} emptyState={emptyState}
    />
  );
  return stacks ? <div className="activity-table activity-table--stacks">{table}</div> : table;
}
