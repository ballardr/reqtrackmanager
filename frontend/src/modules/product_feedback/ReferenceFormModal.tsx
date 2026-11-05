/**
 * Module: modules/product_feedback/ReferenceFormModal
 *
 * Adds or changes one external reference from the request page, in a dialog over the shared `ReferenceFields`. Saving
 * is the page's: it calls the reference endpoint (a reference is not a version of the request) and reports the result
 * through `error`.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { BLANK_REFERENCE, draftFromReference, referenceIsComplete, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFields } from "./ReferenceFields";
import type { ExternalRef } from "./types";
import type { ListChoice } from "./useFeedbackLists";

/**
 * @param initial The reference being changed; omit to add one.
 * @param systems The external systems that can be chosen.
 * @param error A save error to show beside the actions.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the values to save.
 */
export function ReferenceFormModal({
  initial, systems, error, onCancel, onSave,
}: {
  initial?: ExternalRef;
  systems: ListChoice[];
  error?: string | null;
  onCancel: () => void;
  onSave: (draft: ReferenceDraft) => void;
}) {
  const [draft, setDraft] = useState<ReferenceDraft>(() => (initial ? draftFromReference(initial) : BLANK_REFERENCE));
  return (
    <Modal title={initial ? "Edit reference" : "Add a reference"} onClose={onCancel}>
      <div className="stack">
        <FormGrid minColumn="14rem">
          <ReferenceFields draft={draft} onChange={setDraft} systems={systems} />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(draft)} saveDisabled={!referenceIsComplete(draft)} />
      </div>
    </Modal>
  );
}
