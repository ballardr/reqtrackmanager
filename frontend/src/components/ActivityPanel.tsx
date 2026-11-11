import { type ChangeEntry } from "../api/types";
import type { ActivityLink } from "../utils/activityLink";
import { t } from "../i18n/strings";
import { ActivityRow } from "./ActivityRow";

const strings = t();

/** Activity timeline of one record, newest first: audit events, version history and link events
 * (`RecordActivity` feeds it). Each entry is an `ActivityRow`, whose wording the project History table shares
 * (`describeActivityEntry` / `describeActivityAction` in `api/types.ts`), so the two never describe the same
 * data differently.
 *
 * `getLink` says which record each row is about for a list that spans several records; a record's own aside is
 * about the one record already on screen and omits it. */
export function ActivityPanel({
  entries,
  getLink,
  bare = false,
  hideEntityTypes = [],
  emptyText = strings.activity.none,
}: {
  entries: ChangeEntry[];
  /** Resolves the record an entry is about to a link and label; omit for a single record's own timeline. */
  getLink?: (entry: ChangeEntry) => ActivityLink | null;
  /** Skips the outer `.card` wrapper and "Activity" heading, rendering just the entry list — for a caller that
   * already provides its own card and (possibly toggled) heading, e.g. `RequirementDetailPage`'s merged
   * History/Activity card, whose heading switches between "Version history" and "Activity". */
  bare?: boolean;
  /** Entity types whose badge is left out: a record's own timeline need not badge every entry with the record's own type, only the entries about something else (links). */
  hideEntityTypes?: string[];
  /** Shown when there are no entries. */
  emptyText?: string;
}) {
  const list = (
    <>
      {entries.length === 0 && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{emptyText}</p>}
      {entries.map((entry, index) => (
        <ActivityRow
          key={index} entry={entry} link={getLink ? getLink(entry) : null} showType={!hideEntityTypes.includes(entry.entity_type)}
        />
      ))}
    </>
  );
  if (bare) return list;
  return (
    <div className="card stack" style={{ alignSelf: "flex-start", minWidth: 220 }}>
      <h2 style={{ margin: 0, fontSize: "1rem" }}>{strings.activity.title}</h2>
      {list}
    </div>
  );
}
