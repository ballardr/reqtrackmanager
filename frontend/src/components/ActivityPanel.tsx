import { Link } from "react-router-dom";

import { activityEntityLabel, describeActivityEntry, type ChangeEntry } from "../api/types";
import { useOrgLabelCapitalized } from "../context/BrandingContext";

/** Right-side activity timeline (mock's "Subscribed" panel): audit events
 * plus version history for one requirement/change request, newest first.
 * Shares its entity/action labelling and actor/action text with the
 * project overview activity card and the project history page
 * (`describeActivityEntry`/`activityEntityLabel` in `api/types.ts`) —
 * previously each of the three built its own, inconsistent rendering.
 *
 * `ProjectHistoryPage.tsx` also renders this component directly (2026-08
 * UX audit roadmap row 515, "same data, duplicated rendering") rather than
 * hand-rolling its own list markup, which needed two additions beyond the
 * original single-requirement/-change-request side panel use:
 * `getLink` — a project-wide list spans many different requirements/change
 * requests, so (unlike a detail page's own side panel, which is always
 * about the one entity already on screen) each row needs to say which item
 * it's about; and `fullWidth` — a project-wide list page is the page's main
 * content, not a narrow sidebar companion. */
export function ActivityPanel({
  entries,
  getLink,
  fullWidth = false,
  bare = false,
}: {
  entries: ChangeEntry[];
  /** Resolves the item an entry is about to a link + label. Omit when the
   * panel is scoped to a single entity already visible on the page (the
   * requirement/change-request detail side panels) — only a project-wide
   * list needs to say which item each row is about. */
  getLink?: (entry: ChangeEntry) => { to: string; label: string } | null;
  /** Renders at natural width, growing to fill its container, instead of
   * the default narrow sidebar sizing — for a project-wide list page
   * rather than a detail page's side panel. */
  fullWidth?: boolean;
  /** Skips the outer `.card` wrapper and "Activity" heading, rendering
   * just the entry list — for a caller that already provides its own card
   * and (possibly toggled) heading, e.g. `RequirementDetailPage`'s merged
   * History/Activity card (2026-08 UX audit roadmap item 516), whose
   * heading switches between "Version history" and "Activity" depending
   * on which view is selected rather than always reading "Activity". */
  bare?: boolean;
}) {
  const orgLabelCap = useOrgLabelCapitalized();
  const list = (
    <>
      {entries.length === 0 && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>No activity yet.</p>}
      {entries.map((e, i) => {
        const link = getLink ? getLink(e) : null;
        return (
          <div key={i} className="stack" style={{ gap: "0.15rem" }}>
            <div className="row" style={{ gap: "0.3rem" }}>
              <span className="badge">{activityEntityLabel(e.entity_type, orgLabelCap)}</span>
            </div>
            <div style={{ fontSize: "0.85rem" }}>
              {describeActivityEntry(e)}
              {link && (
                <>
                  {" "}
                  <Link to={link.to}>{link.label}</Link>
                </>
              )}
            </div>
            <div className="text-muted" style={{ fontSize: "0.75rem" }}>{new Date(e.timestamp).toLocaleString()}</div>
          </div>
        );
      })}
    </>
  );
  if (bare) return list;
  return (
    <div className="card stack" style={fullWidth ? undefined : { alignSelf: "flex-start", minWidth: 220 }}>
      <h2 style={{ margin: 0, fontSize: "1rem" }}>Activity</h2>
      {list}
    </div>
  );
}
