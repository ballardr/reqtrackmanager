/**
 * Module: hooks/useSnippetToast
 *
 * Tells the author what a snippet insertion did, as a toast, so nothing above the designer's views changes height.
 *
 * Responsibilities: turn the apply service's change report into one toast. A plain insertion is a one-line success toast
 * that times out; when the snippet also added page styles or variables, or the layout already had problems, those lines
 * are listed and the toast stays until dismissed. Where the view has no undo of its own the toast carries an Undo button.
 * An earlier insertion's toast is replaced, so a stale Undo is never left on screen.
 */
import { useCallback, useRef } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";

/** What the designer is told about an insertion. */
export interface SnippetNoticeData {
  name: string;
  changes: string[];
  problemsElsewhere: number;
}

export interface SnippetToast {
  /**
   * Shows the toast for an insertion.
   *
   * @param notice The insertion to report.
   * @param undo Reverts the insertion; omit where the view undoes with Ctrl+Z (the toast then says so instead).
   */
  announce: (notice: SnippetNoticeData, undo?: () => void) => void;
  /** Removes the current insertion toast, if any (the view changed, so its Undo no longer applies). */
  clear: () => void;
}

/**
 * @returns `announce` and `clear` for the snippet insertion toast.
 */
export function useSnippetToast(): SnippetToast {
  const { showToast, dismissToast } = useToast();
  const text = useStrings().reportSnippets;
  const current = useRef<number | null>(null);

  const clear = useCallback(() => {
    if (current.current !== null) dismissToast(current.current);
    current.current = null;
  }, [dismissToast]);

  const announce = useCallback(
    (notice: SnippetNoticeData, undo?: () => void) => {
      clear();
      // The first change line is the block count the title already implies; the rest (page styles, variables) are worth reading.
      const details = [
        ...notice.changes.slice(1),
        ...(notice.problemsElsewhere > 0 ? [text.problemsElsewhere(notice.problemsElsewhere)] : []),
      ];
      current.current = showToast(
        undo ? text.noticeTitle(notice.name) : text.noticeTitleWithUndoKey(notice.name),
        "success",
        { details: details.length > 0 ? details : undefined, action: undo ? { label: text.undo, onClick: undo } : undefined },
      );
    },
    [clear, showToast, text],
  );

  return { announce, clear };
}
