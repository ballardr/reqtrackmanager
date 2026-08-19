import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { activityEntityLabel, activityEntryLink, describeActivityEntry, ENTITY_TYPE_LABEL, type ChangeEntry } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";

const PAGE_SIZE = 30;

// "organization" is a valid `entity_type` an org-scoped audit event can
// report but isn't in `ENTITY_TYPE_LABEL` (its label depends on the
// deployment's organisation-label override, see `activityEntityLabel`).
const ENTITY_TYPE_FILTER_OPTIONS = [...Object.keys(ENTITY_TYPE_LABEL), "organization"];

/**
 * Project changes-over-time view (C-A-10): a unified timeline of
 * requirement/change-request/audit events, with a time-range and
 * entity-type filter. Discussion comments are excluded unless explicitly
 * included.
 */
export function ProjectHistoryPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const orgLabelCap = useOrgLabelCapitalized();
  const [changes, setChanges] = useState<ChangeEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [includeComments, setIncludeComments] = useState(false);
  const [entityTypeFilter, setEntityTypeFilter] = useState("");

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (since) params.set("since", new Date(since).toISOString());
    if (until) params.set("until", new Date(until).toISOString());
    if (includeComments) params.set("include_comments", "true");
    if (entityTypeFilter) params.set("entity_type", entityTypeFilter);
    return params;
  }

  async function loadChanges(offset: number, append: boolean) {
    if (!projectId) return;
    const page = await api.getPage<ChangeEntry>(`/api/v1/projects/${projectId}/changes?${listParams(offset).toString()}`);
    setChanges((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    setChanges(null);
    await loadChanges(0, false);
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
                {activityEntityLabel(key, orgLabelCap)}
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
          {changes.map((c, idx) => {
            const link = projectId ? activityEntryLink(c, projectId) : null;
            return (
              <div key={idx} className="row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
                <span>
                  <span className="badge">{activityEntityLabel(c.entity_type, orgLabelCap)}</span> {describeActivityEntry(c)}
                  {link && (
                    <>
                      {" "}
                      <Link to={link.to}>{link.label}</Link>
                    </>
                  )}
                </span>
                <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
              </div>
            );
          })}
        </div>
      )}
      {changes && <LoadMoreButton loaded={changes.length} total={total} onClick={() => loadChanges(changes.length, true)} />}
    </div>
  );
}
