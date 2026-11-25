/**
 * Module: components/ReferenceFormModal
 *
 * Adds or changes one external reference from a record's page, in a dialog over the shared `ReferenceFields`. Saving
 * is the caller's (`RecordTags`): it calls the reference endpoint, which does not create a version of the record,
 * and reports a failure through `error`.
 */
import { useState } from "react";

import type { ExternalReference, ReferenceSystem } from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { FormGrid } from "./FormGrid";
import { Modal } from "./Modal";
import { BLANK_REFERENCE, draftFromReference, referenceIsComplete, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFields } from "./ReferenceFields";

/**
 * @param initial The reference being changed; omit to add one.
 * @param systems The systems that can be chosen.
 * @param error A save error to show beside the actions.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the values to save.
 */
export function ReferenceFormModal({
  initial, systems, error, onCancel, onSave,
}: {
  initial?: ExternalReference;
  systems: ReferenceSystem[];
  error?: string | null;
  onCancel: () => void;
  onSave: (draft: ReferenceDraft) => void;
}) {
  const allStrings = useStrings();
  const strings = allStrings.references;
  const [draft, setDraft] = useState<ReferenceDraft>(() => (initial ? draftFromReference(initial) : BLANK_REFERENCE));
  return (
    <Modal title={initial ? strings.editTitle : strings.addTitle} onClose={onCancel}>
      <div className="stack">
        <FieldCaption label={strings.label} help={allStrings.help.recordReferences} />
        <FormGrid minColumn="14rem">
          <ReferenceFields draft={draft} onChange={setDraft} systems={systems} />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(draft)} saveDisabled={!referenceIsComplete(draft)} />
      </div>
    </Modal>
  );
}
