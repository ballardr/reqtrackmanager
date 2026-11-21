/**
 * Module: hooks/useWatchingTab
 *
 * The "Watching" tab a requirement or change request page passes to `DetailLayout`'s `extraTabs`. It is
 * absent while the watchers load and, for a reader, when no one is watching (an unwatched record stays
 * uncluttered); a manager always has it, to add the first watcher. Its label carries the count, so who is
 * watching is visible before the tab is opened.
 */
import type { DetailAsideTab } from "../components/DetailLayout";
import { WatchingPanel } from "../components/WatchingPanel";
import { t } from "../i18n/strings";
import { useWatchers } from "./useWatchers";

const strings = t();
const WATCHING_TAB_KEY = "watching";

/**
 * @param recordPath API path of the record; undefined until its project is known.
 * @param organizationId The project's organisation.
 * @param projectId The record's project.
 * @param canManage Whether the viewer may add and remove watchers.
 * @param refreshKey Reloads the watchers when it changes (see `useWatchers`).
 * @returns The tab for `DetailLayout`'s `extraTabs`, or null when none applies.
 */
export function useWatchingTab({
  recordPath, organizationId, projectId, canManage, refreshKey,
}: {
  recordPath: string | undefined;
  organizationId?: string;
  projectId: string | undefined;
  canManage: boolean;
  refreshKey?: unknown;
}): DetailAsideTab | null {
  const state = useWatchers(recordPath, refreshKey);
  const count = state.watchers?.length ?? 0;
  if (state.watchers === null || !projectId || (!canManage && count === 0)) return null;
  return {
    key: WATCHING_TAB_KEY,
    label: count > 0 ? `${strings.watchers.title} (${count})` : strings.watchers.title,
    content: <WatchingPanel state={state} organizationId={organizationId} projectId={projectId} canManage={canManage} />,
  };
}
