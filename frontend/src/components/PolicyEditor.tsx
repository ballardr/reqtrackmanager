/**
 * Module: components/PolicyEditor
 *
 * The create/edit dialog for a policy: title (fixed for a built-in policy), effective date and the visual text
 * editor. Saving writes the working copy only; publishing is a separate, recorded action in `PoliciesPanel`, so an
 * edit never changes what people can already read.
 *
 * The caller saves. The server's own rules (an unsafe link, an oversized text) come back as the error shown above
 * the form.
 */
import { useState } from "react";

import type { Policy, PolicyBody, PolicySlot, PolicyWrite } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { DateField, TextField } from "./FormFields";
import { Modal } from "./Modal";
import { PolicyBodyEditor } from "./PolicyBodyEditor";

const EMPTY_BODY: PolicyBody = { type: "doc", content: [] };
/** The longest title the server accepts. */
const MAX_TITLE_LENGTH = 120;

/**
 * @param policy The policy being edited, or null to create one.
 * @param slot For a new built-in policy, its slot and fixed title; null for any other policy.
 * @param slotTitle The fixed title of `slot`.
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the fields.
 */
export function PolicyEditor({ policy, slot, slotTitle, error, onCancel, onSave }: {
  policy: Policy | null;
  slot?: PolicySlot | null;
  slotTitle?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: PolicyWrite) => void;
}) {
  const strings = useStrings();
  const text = strings.policies;
  const fixedTitle = policy ? (policy.key ? policy.title : null) : (slotTitle ?? null);
  const [title, setTitle] = useState(policy?.title ?? slotTitle ?? "");
  const [body, setBody] = useState<PolicyBody>(policy?.body ?? EMPTY_BODY);
  const [effectiveFrom, setEffectiveFrom] = useState(policy?.effective_from ?? "");
  return (
    <Modal title={policy ? text.editPolicy : (slotTitle ? text.writeSlot(slotTitle) : text.newPolicy)} onClose={onCancel} size="lg">
      <div className="stack">
        {fixedTitle === null ? (
          <TextField
            helpNotNeeded required label={text.title} value={title} onChange={setTitle}
            inputProps={{ maxLength: MAX_TITLE_LENGTH, autoFocus: true }}
          />
        ) : (
          <TextField helpNotNeeded label={text.title} value={fixedTitle} onChange={() => undefined} inputProps={{ readOnly: true }} />
        )}
        <DateField label={text.effectiveFromLabel} help={strings.help.policyEffectiveFrom} value={effectiveFrom} onChange={setEffectiveFrom} />
        <PolicyBodyEditor label={text.body} help={strings.help.policyBody} value={body} onChange={setBody} />
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={fixedTitle === null && title.trim() === ""}
          onSave={() => onSave({
            key: policy ? undefined : (slot ?? null), title: title.trim(), body, effective_from: effectiveFrom === "" ? null : effectiveFrom,
          })}
        />
      </div>
    </Modal>
  );
}
