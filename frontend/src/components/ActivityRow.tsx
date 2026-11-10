/**
 * Module: components/ActivityRow
 *
 * One activity entry in its stacked form: the record type badge (unless hidden), the sentence ("Alex approved"),
 * the record it is about when the list spans several, the note typed with the change and the time. It is the form
 * a record's narrow Activity aside uses, and its sentence comes from `describeActivityEntry`, the same text the
 * project History table splits into its Person and Event columns (`describeActivityAction`), so one wording
 * change reaches both.
 */
import { Link } from "react-router-dom";

import { activityEntityLabel, activityEntryNotes, describeActivityEntry, type ChangeEntry } from "../api/types";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import type { ActivityLink } from "../utils/activityLink";
import { ActivityNote } from "./ActivityNote";
import { Badge } from "./Badge";

/**
 * @param entry The entry to show.
 * @param link The record it is about, for a list that spans several records; omit in a record's own aside.
 * @param showType Whether the type badge is shown (a record's own timeline leaves out its own type).
 */
export function ActivityRow({ entry, link = null, showType = true }: { entry: ChangeEntry; link?: ActivityLink | null; showType?: boolean }) {
  const orgLabelCap = useOrgLabelCapitalized();
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      {showType && (
        <div className="row" style={{ gap: "0.3rem" }}>
          <Badge>{activityEntityLabel(entry.entity_type, orgLabelCap)}</Badge>
        </div>
      )}
      <div style={{ fontSize: "0.85rem" }}>
        {describeActivityEntry(entry)}
        {link && (
          <>
            {" "}
            <Link to={link.to}>{link.label}</Link>
          </>
        )}
      </div>
      {activityEntryNotes(entry).map((note) => <ActivityNote key={note} text={note} />)}
      <div className="text-muted" style={{ fontSize: "0.75rem" }}>{new Date(entry.timestamp).toLocaleString()}</div>
    </div>
  );
}
