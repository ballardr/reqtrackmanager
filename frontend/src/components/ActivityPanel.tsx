import { activityEntityLabel, describeActivityEntry, type ChangeEntry } from "../api/types";

/** Right-side activity timeline (mock's "Subscribed" panel): audit events
 * plus version history for one requirement/change request, newest first.
 * Shares its entity/action labelling and actor/action text with the
 * project overview activity card and the project history page
 * (`describeActivityEntry`/`activityEntityLabel` in `api/types.ts`) —
 * previously each of the three built its own, inconsistent rendering. */
export function ActivityPanel({ entries }: { entries: ChangeEntry[] }) {
  return (
    <div className="card stack" style={{ alignSelf: "flex-start", minWidth: 220 }}>
      <h2 style={{ margin: 0, fontSize: "1rem" }}>Activity</h2>
      {entries.length === 0 && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>No activity yet.</p>}
      {entries.map((e, i) => (
        <div key={i} className="stack" style={{ gap: "0.15rem" }}>
          <div className="row" style={{ gap: "0.3rem" }}>
            <span className="badge">{activityEntityLabel(e.entity_type)}</span>
          </div>
          <div style={{ fontSize: "0.85rem" }}>{describeActivityEntry(e)}</div>
          <div className="text-muted" style={{ fontSize: "0.75rem" }}>{new Date(e.timestamp).toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}
