/**
 * Module: hooks/useActivityColumns
 *
 * The columns of a project's activity table (`ProjectActivityTable`): Time and Event always drawn; Type, Record and
 * Person optional. `useActivityColumns` gives every column (the overview widget draws all of them);
 * `useActivityColumnChoice` adds the shared column chooser for the History page.
 *
 * Design decisions: user text (event, record, person) is shown with `CellText`, so a long title or an unbroken word
 * never changes the table's shape.
 * Dependencies: `useOptionalColumns`, `ActivityLinkEnds`, `ActivityNote`, `CellText`, the activity wording in `api/types`.
 */
import { Link } from "react-router-dom";

import {
  activityEntityLabel, activityEntryNotes, describeActivityAction, describeLinkEventAction, linkEventVerb, sentenceCase,
} from "../api/types";
import { ActivityLinkEnds } from "../components/ActivityLinkEnds";
import { ActivityNote } from "../components/ActivityNote";
import { Badge } from "../components/Badge";
import { CellText } from "../components/CellText";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { activityRecordLink } from "../utils/activityLink";
import type { ActivityRow } from "../utils/activityRows";
import { useOptionalColumns } from "./useOptionalColumns";

/**
 * The activity table's columns, in order.
 *
 * @param projectId The project whose activity it is (a record in another project is named with its project).
 * @param sortable Whether the Time column sorts (a table with an `onSort`).
 * @returns Every column; Type, Record and Person are marked optional for `useOptionalColumns`.
 */
export function useActivityColumns(projectId: string | undefined, sortable: boolean): DirectoryColumn<ActivityRow>[] {
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const columns: DirectoryColumn<ActivityRow>[] = [
    {
      key: "time",
      label: strings.history.columnTime,
      sortable,
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
      optional: true,
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
      optional: true,
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
      optional: true,
      render: ({ entry }) => (
        entry.actor_display_name
          ? <CellText maxWidth="14rem">{entry.actor_display_name}</CellText>
          : <span className="text-muted">{strings.history.unnamedActor}</span>
      ),
    },
  ];
  return columns;
}

/**
 * The activity columns with a column chooser, for a page that lists activity as its main content.
 *
 * @param key Names the list; its choice is remembered per person (`useOptionalColumns`).
 * @param projectId The project whose activity it is.
 * @returns The `columns` to pass to `ProjectActivityTable` and the `chooser` control for the page's actions.
 */
export function useActivityColumnChoice(key: string, projectId: string | undefined) {
  return useOptionalColumns(key, useActivityColumns(projectId, true));
}
