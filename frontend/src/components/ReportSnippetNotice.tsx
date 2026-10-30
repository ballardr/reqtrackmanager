/**
 * Module: components/ReportSnippetNotice
 *
 * The honest result of a snippet insertion, shown above the designer's views: what the server did ("Added page style
 * Cover; renamed 'Cover' to 'Cover 2' because it already existed"), how many problems the layout already had, and how to
 * take the insertion back.
 *
 * Responsibilities: draw the change report the apply service returned, with an Undo button where the view has no undo
 * of its own, and a Dismiss button. It holds no state; the designer owns the notice and clears it on the next edit view.
 */
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";

/** What the designer remembers about the last insertion. */
export interface SnippetNoticeData {
  name: string;
  changes: string[];
  problemsElsewhere: number;
}

/**
 * @param notice The insertion to report.
 * @param hint A line about undoing it in the current view.
 * @param onUndo Called by Undo; omit where the view undoes with Ctrl+Z.
 * @param onDismiss Called by Dismiss.
 */
export function ReportSnippetNotice({
  notice, hint, onUndo, onDismiss,
}: {
  notice: SnippetNoticeData;
  hint?: ReactNode;
  onUndo?: () => void;
  onDismiss: () => void;
}) {
  const text = useStrings().reportSnippets;
  return (
    <div className="card stack" role="status" aria-label={text.noticeLabel}>
      <strong>{text.noticeTitle(notice.name)}</strong>
      <ul style={{ margin: 0, paddingLeft: "var(--space-5)" }}>
        {notice.changes.map((change, index) => <li key={index}>{change}</li>)}
      </ul>
      {notice.problemsElsewhere > 0 && <span className="text-muted">{text.problemsElsewhere(notice.problemsElsewhere)}</span>}
      {hint && <span className="text-muted">{hint}</span>}
      <div className="row">
        {onUndo && <button type="button" className="btn" onClick={onUndo}>{text.undo}</button>}
        <button type="button" className="btn" onClick={onDismiss}>{text.dismiss}</button>
      </div>
    </div>
  );
}
