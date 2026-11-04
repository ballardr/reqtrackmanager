/**
 * Module: components/LayoutDraftNotice
 *
 * The line that says a layout has unpublished work: who wrote the shared draft, when, and which version it began from,
 * with Discard draft. The designer shows it on opening a layout that has a draft and History shows it as the Draft row
 * above the published versions, so the two are never confused.
 *
 * Responsibilities: word the draft's author, time and base version; say plainly when versions were published since the
 * draft began (publishing then follows the server's version-conflict rule); offer Discard draft and, where the caller
 * supports it, Show saved version. It stores nothing: the caller confirms and carries out each action.
 */
import type { ReportLayoutDraftSummary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param summary The draft.
 * @param currentVersion The layout's latest published version.
 * @param onDiscard Asks to discard the draft; omit for a reader who cannot.
 * @param onShowSaved Opens the read-only comparison with the saved version; omit where it is not offered.
 */
export function LayoutDraftNotice({
  summary, currentVersion, onDiscard, onShowSaved,
}: {
  summary: ReportLayoutDraftSummary;
  currentVersion: number;
  onDiscard?: () => void;
  onShowSaved?: () => void;
}) {
  const text = useStrings().layoutDraft;
  return (
    <div className="card stack" role="note" aria-label={text.noticeLabel}>
      <span>
        {text.notice(summary.updated_by_name ?? text.noticeUnknownAuthor, new Date(summary.updated_at).toLocaleString(), summary.base_version)}
        {summary.base_version < currentVersion && <> {text.behind(currentVersion)}</>}
      </span>
      {(onDiscard || onShowSaved) && (
        <div className="row">
          {onShowSaved && <button type="button" className="btn btn-sm" onClick={onShowSaved}>{text.showSaved}</button>}
          {onDiscard && <button type="button" className="btn btn-sm btn-danger" onClick={onDiscard}>{text.discardDraft}</button>}
        </div>
      )}
    </div>
  );
}
