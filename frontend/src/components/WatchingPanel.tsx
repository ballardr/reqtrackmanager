/**
 * Module: components/WatchingPanel
 *
 * The users and groups watching one requirement or change request (users and groups on parity): each
 * user, and each member of a watching group who can view the project, is notified of the record's
 * comments, alongside people who subscribed themselves (the record header menu's Subscribe action).
 * Project managers and administrators add and remove watchers; everyone else sees who is watching.
 *
 * It is a tab of the detail page's aside card (`DetailLayout`'s `extraTabs`), compact by design: the
 * watchers as chips with a remove button each, and one (+) button that opens the picker in a popover, so
 * a record nobody watches costs one line. `useWatchingTab` (hooks/useWatchingTab) builds the tab.
 */
import type { Principal } from "../api/types";
import type { Watchers } from "../hooks/useWatchers";
import { t } from "../i18n/strings";
import { AddPopoverButton } from "./AddPopoverButton";
import { ClearButton } from "./ClearButton";
import { FieldCaption } from "./FieldHelp";
import { PrincipalBadge } from "./PrincipalBadge";
import { PrincipalPicker } from "./PrincipalPicker";

const strings = t();

/**
 * The tab content: the watchers and, for a manager, the add and remove controls.
 *
 * @param state The record's watchers (`useWatchers`), already loaded.
 * @param organizationId The project's organisation, to list its groups and search its users.
 * @param projectId The record's project, to list its groups and scope the user search.
 * @param canManage Whether the viewer may add and remove watchers (project manager or administrator).
 */
export function WatchingPanel({
  state, organizationId, projectId, canManage,
}: {
  state: Watchers;
  organizationId?: string;
  projectId: string;
  canManage: boolean;
}) {
  const watchers = state.watchers ?? [];
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <FieldCaption muted label={strings.watchers.caption} help={strings.help.watchers} />
      <div className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
        {watchers.length === 0 && <span className="text-muted">{strings.watchers.none}</span>}
        {watchers.map((watcher) => (
          <WatcherChip key={`${watcher.type}:${watcher.id}`} watcher={watcher} onRemove={canManage ? () => state.remove(watcher) : undefined} />
        ))}
        {canManage && (
          <AddPopoverButton label={strings.watchers.add}>
            {(close) => (
              <PrincipalPicker
                orgUsers={[]} organizationId={organizationId} projectId={projectId} value={null}
                onChange={(principal) => { void state.add(principal); close(); }}
                ariaLabel={strings.watchers.add}
              />
            )}
          </AddPopoverButton>
        )}
      </div>
    </div>
  );
}

/** One watcher: its badge and, for a manager, a button that stops it watching. */
function WatcherChip({ watcher, onRemove }: { watcher: Principal; onRemove?: () => void }) {
  const label = `${strings.watchers.stopWatching}: ${watcher.label}`;
  return (
    <span className="row" style={{ gap: "var(--space-1)", alignItems: "center" }}>
      <PrincipalBadge principal={watcher} />
      {onRemove && (
        <ClearButton label={label} onClick={onRemove} />
      )}
    </span>
  );
}
