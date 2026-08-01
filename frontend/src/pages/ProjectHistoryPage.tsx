import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

interface ChangeEntry {
  timestamp: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string | null;
  detail: Record<string, unknown> | null;
}

/**
 * Project changes-over-time view (C-A-10): a unified timeline of
 * requirement/change-request/audit events, with a time-range filter.
 * Discussion comments are excluded unless explicitly included.
 */
export function ProjectHistoryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [changes, setChanges] = useState<ChangeEntry[] | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [includeComments, setIncludeComments] = useState(false);

  async function reload() {
    if (!projectId) return;
    setChanges(null);
    const params = new URLSearchParams();
    if (since) params.set("since", new Date(since).toISOString());
    if (until) params.set("until", new Date(until).toISOString());
    if (includeComments) params.set("include_comments", "true");
    const result = await api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/changes?${params.toString()}`);
    setChanges(result);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, since, until, includeComments]);

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.history.title}</h1>
      <div className="row">
        <label className="row">
          {strings.history.since}
          <input type="datetime-local" className="input" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label className="row">
          {strings.history.until}
          <input type="datetime-local" className="input" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <label className="row">
          <input type="checkbox" checked={includeComments} onChange={(e) => setIncludeComments(e.target.checked)} />
          {strings.history.includeComments}
        </label>
      </div>

      {!changes && <Spinner />}
      {changes && changes.length === 0 && <p className="text-muted">{strings.history.empty}</p>}
      {changes && changes.length > 0 && (
        <div className="card stack">
          {changes.map((c, idx) => (
            <div key={idx} className="row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              <span>
                <span className="badge">{c.entity_type}</span> {c.action}
                {c.detail && typeof c.detail.unique_code === "string" && ` — ${c.detail.unique_code}`}
                {c.detail && typeof c.detail.proposed_name === "string" && ` — ${c.detail.proposed_name}`}
              </span>
              <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
