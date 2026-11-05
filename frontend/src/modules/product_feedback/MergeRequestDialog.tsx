/**
 * Module: modules/product_feedback/MergeRequestDialog
 *
 * Marks a request a duplicate of another ("canonical") request of the same owner. The duplicate's requesters then
 * count toward the canonical request's demand, and the merge can be undone from the duplicate. The canonical choices
 * are the other open requests of the same project (or the same inbox), so a merge into a declined, delivered or
 * already-duplicate request, or into another owner's, cannot be picked.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { TextAreaField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import type { EnhancementRequest } from "./types";

/**
 * @param request The duplicate.
 * @param candidates The requests it may be merged into (`mergeCandidates`).
 * @param onMerge Called with the canonical request's id and the note; the caller closes the dialog.
 * @param onCancel Dismisses the dialog.
 */
export function MergeRequestDialog({
  request, candidates, onMerge, onCancel,
}: {
  request: EnhancementRequest;
  candidates: EnhancementRequest[];
  onMerge: (canonicalId: string, note: string) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [canonicalId, setCanonicalId] = useState("");
  const [note, setNote] = useState("");
  return (
    <ConfirmDialog
      title={`Merge ${request.unique_code} into another request?`}
      message={
        <span className="stack" style={{ gap: "var(--space-3)" }}>
          <span>
            This request becomes a duplicate. Its requesters count toward the request you choose, and you can undo the merge
            from this request later.
          </span>
          <LabeledSelect
            helpNotNeeded required label="Merge into" value={canonicalId} onChange={setCanonicalId}
            options={candidates.map((c) => ({ value: c.id, label: `${c.unique_code} ${c.title}` }))}
            placeholder={candidates.length === 0 ? "No other open requests" : "Choose a request…"}
            disabled={candidates.length === 0}
          />
          <TextAreaField help={PRODUCT_FEEDBACK_HELP.mergeNote} label="Note" value={note} onChange={setNote} rows={2} />
        </span>
      }
      confirmLabel="Merge"
      confirmDisabled={canonicalId === ""}
      onConfirm={() => void onMerge(canonicalId, note)}
      onCancel={onCancel}
    />
  );
}
