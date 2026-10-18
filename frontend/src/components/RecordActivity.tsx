/**
 * Module: components/RecordActivity
 *
 * The Activity tab of a detail page's aside: the record's own timeline (what changed, who did it,
 * links added or removed), newest first, 25 at a time. The server authorises it like the record
 * itself, so the component shows what it is given.
 *
 * It loads when it mounts, which is when its tab opens, so switching back to the tab shows fresh
 * entries; a page that changes the record while the tab is open bumps `refreshToken` (the same
 * counter it gives the Links panel). `api` is injectable for stories.
 */
import { useCallback, useEffect, useState } from "react";

import { recordActivityApi, type RecordActivityApi } from "../api/recordActivity";
import type { ChangeEntry } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { ActivityPanel } from "./ActivityPanel";
import { Spinner } from "./Spinner";

const PAGE_SIZE = 25;

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param refreshToken Bump to reload from the first page.
 * @param api The activity API (the live one by default).
 */
export function RecordActivity({
  projectId,
  artefactType,
  artefactId,
  refreshToken = 0,
  api = recordActivityApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  refreshToken?: number;
  api?: RecordActivityApi;
}) {
  const strings = useStrings();
  const [entries, setEntries] = useState<ChangeEntry[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    api.list(projectId, artefactType, artefactId, { limit: PAGE_SIZE })
      .then((page) => {
        if (!active) return;
        setEntries(page.entries);
        setHasMore(page.has_more);
        setFailed(false);
      })
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId, refreshToken]);

  const showMore = useCallback(async () => {
    if (!entries) return;
    setLoadingMore(true);
    try {
      const page = await api.list(projectId, artefactType, artefactId, { limit: PAGE_SIZE, offset: entries.length });
      setEntries([...entries, ...page.entries]);
      setHasMore(page.has_more);
    } catch {
      setFailed(true);
    } finally {
      setLoadingMore(false);
    }
  }, [api, projectId, artefactType, artefactId, entries]);

  if (failed && entries === null) return <p className="text-muted" role="alert">{strings.recordActivity.loadError}</p>;
  if (entries === null) return <Spinner />;
  return (
    <div className="stack">
      <ActivityPanel entries={entries} bare hideEntityTypes={[artefactType]} emptyText={strings.recordActivity.none} />
      {failed && <p className="text-muted" role="alert">{strings.recordActivity.loadError}</p>}
      {hasMore && (
        <button type="button" className="btn" onClick={showMore} disabled={loadingMore} style={{ alignSelf: "flex-start" }}>
          {strings.recordActivity.showMore}
        </button>
      )}
    </div>
  );
}
