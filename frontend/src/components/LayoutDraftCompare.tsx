/**
 * Module: components/LayoutDraftCompare
 *
 * The read-only comparison behind Show saved version: the layout's latest saved version against the shared draft the server
 * holds, as the text view writes them, so a person can see what the draft changes without touching or discarding it.
 *
 * Responsibilities: read the draft, write it and the saved version as text (`ReportLayoutApi.formatTree`, so the diff reads the way
 * the author writes), and draw the difference with the shared `LayoutDiff`. Nothing is stored.
 */
import { useState } from "react";

import type { ReportLayoutApi, ReportLayoutTree } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { diffLines, type DiffLine } from "../utils/reportLayoutText";
import { LayoutDiff } from "./LayoutDiff";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/**
 * @param api The calls, bound to the layout's scope.
 * @param layoutId The layout whose draft is compared.
 * @param saved The latest saved version's number and tree.
 * @param onClose Closes the dialog.
 */
export function LayoutDraftCompare({
  api, layoutId, saved, onClose,
}: { api: ReportLayoutApi; layoutId: string; saved: { version: number; tree: ReportLayoutTree }; onClose: () => void }) {
  const text = useStrings().layoutDraft;
  const [diff, setDiff] = useState<DiffLine[] | null>(null);
  const [failed, setFailed] = useState(false);

  useLoadOnChange(async () => {
    try {
      const draft = await api.draft(layoutId);
      const [older, newer] = await Promise.all([api.formatTree(saved.tree), api.formatTree(draft.tree)]);
      setDiff(diffLines(older, newer));
    } catch {
      setFailed(true);
    }
  }, [api, layoutId, saved.tree]);

  const changed = diff?.some((line) => line.kind !== "same") ?? false;
  return (
    <Modal title={text.compareTitle(saved.version)} onClose={onClose} size="lg" dirty={false}>
      <div className="stack">
        {failed && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{text.compareFailed}</p>}
        {!diff && !failed && <Spinner />}
        {diff && !changed && <p className="text-muted" style={{ margin: 0 }}>{text.compareIdentical}</p>}
        {diff && changed && <LayoutDiff diff={diff} label={text.compareDiffLabel} />}
      </div>
    </Modal>
  );
}
