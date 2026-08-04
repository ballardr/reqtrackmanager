import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { activityEntityLabel, describeActivityEntry, ENTITY_TYPE_LABEL, type ChangeEntry } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

const ENTITY_TYPE_FILTER_OPTIONS = Object.keys(ENTITY_TYPE_LABEL);

/**
 * Project changes-over-time view (C-A-10): a unified timeline of
 * requirement/change-request/audit events, with a time-range and
 * entity-type filter. Discussion comments are excluded unless explicitly
 * included.
 */
export function ProjectHistoryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [changes, setChanges] = useState<ChangeEntry[] | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [includeComments, setIncludeComments] = useState(false);
  const [entityTypeFilter, setEntityTypeFilter] = useState("");

  async function reload() {
    if (!projectId) return;
    setChanges(null);
    const params = new URLSearchParams();
    if (since) params.set("since", new Date(since).toISOString());
    if (until) params.set("until", new Date(until).toISOString());
    if (includeComments) params.set("include_comments", "true");
    if (entityTypeFilter) params.set("entity_type", entityTypeFilter);
    const result = await api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/changes?${params.toString()}`);
    setChanges(result);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, since, until, includeComments, entityTypeFilter]);

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
          {strings.history.entityType}
          <select className="input" value={entityTypeFilter} onChange={(e) => setEntityTypeFilter(e.target.value)}>
            <option value="">{strings.history.allEntityTypes}</option>
            {ENTITY_TYPE_FILTER_OPTIONS.map((key) => (
              <option key={key} value={key}>
                {activityEntityLabel(key)}
              </option>
            ))}
          </select>
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
                <span className="badge">{activityEntityLabel(c.entity_type)}</span> {describeActivityEntry(c)}
              </span>
              <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
