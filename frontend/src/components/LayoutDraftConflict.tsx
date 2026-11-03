/**
 * Module: components/LayoutDraftConflict
 *
 * The banner shown when someone else changed the shared draft while this editor was writing to it: who and when, and
 * the two ways forward, Load their changes (the editor takes their draft) or Keep mine (the editor overwrites it).
 * Autosave stays paused while it shows. The caller carries out the choice; this only words it.
 */
import type { ReportLayoutDraftSummary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param draft The draft as it stands now, `null` when it was published or discarded meanwhile.
 * @param onLoadTheirs Replaces the editor's content with the other draft (or the latest version when it is gone).
 * @param onKeepMine Writes the editor's content over the other draft.
 */
export function LayoutDraftConflict({
  draft, onLoadTheirs, onKeepMine,
}: { draft: ReportLayoutDraftSummary | null; onLoadTheirs: () => void; onKeepMine: () => void }) {
  const text = useStrings().layoutDraft;
  return (
    <div className="card stack" role="alert" aria-label={text.conflictTitle}>
      <strong>{text.conflictTitle}</strong>
      <span>
        {draft
          ? text.conflict(draft.updated_by_name ?? text.noticeUnknownAuthor, new Date(draft.updated_at).toLocaleString())
          : text.conflictGone}
      </span>
      <div className="row">
        <button type="button" className="btn" onClick={onLoadTheirs}>{text.loadTheirs}</button>
        <button type="button" className="btn" onClick={onKeepMine}>{text.keepMine}</button>
      </div>
    </div>
  );
}
