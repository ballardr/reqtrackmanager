import type { ChangeEntry } from "../api/types";

const ACTION_LABEL: Record<string, string> = {
  created: "created",
  updated: "updated",
  archived: "archived",
  submitted: "submitted",
  withdrawn: "withdrew",
  approved: "approved",
  rejected: "rejected",
};

function describe(entry: ChangeEntry): string {
  const who = entry.actor_display_name ?? "Someone";
  const action = ACTION_LABEL[entry.action] ?? entry.action;
  const changeNote = entry.detail && typeof entry.detail.change_note === "string" ? entry.detail.change_note : "";
  return changeNote ? `${who} ${action} — ${changeNote}` : `${who} ${action}`;
}

/** Right-side activity timeline (mock's "Subscribed" panel): audit events
 * plus version history for one requirement/change request, newest first. */
export function ActivityPanel({ entries }: { entries: ChangeEntry[] }) {
  return (
    <div className="card stack" style={{ alignSelf: "flex-start", minWidth: 220 }}>
      <h2 style={{ margin: 0, fontSize: "1rem" }}>Activity</h2>
      {entries.length === 0 && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>No activity yet.</p>}
      {entries.map((e, i) => (
        <div key={i} className="stack" style={{ gap: "0.15rem" }}>
          <div style={{ fontSize: "0.85rem" }}>{describe(e)}</div>
          <div className="text-muted" style={{ fontSize: "0.75rem" }}>{new Date(e.timestamp).toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}
