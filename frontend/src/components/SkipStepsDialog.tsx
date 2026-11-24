/**
 * Module: components/SkipStepsDialog
 *
 * The dialog of the **Skip steps…** row (`useSkipSteps`): the later step a record moves to, with the steps each option
 * passes over, and the required reason (at most 500 characters, as the server accepts), with `FormActions` in the
 * dialog header. It moves nothing itself; the caller runs the move.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { TextAreaField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** The longest reason the server accepts. */
const SKIP_REASON_MAX_LENGTH = 500;

/**
 * The dialog that collects the target step and the reason.
 *
 * @param noun The record type's singular name.
 * @param options The later steps the record may be moved to, each worded with the steps it passes over.
 * @param onClose Closes the dialog without moving the record.
 * @param onSubmit Called with the chosen target and the trimmed reason.
 */
export function SkipStepsDialog({
  noun, options, initialTarget, onClose, onSubmit,
}: {
  noun: string;
  options: Array<{ value: string; label: string }>;
  /** The option chosen when the dialog opens (the first when omitted or not offered). */
  initialTarget?: string;
  onClose: () => void;
  onSubmit: (target: string, reason: string) => Promise<void>;
}) {
  const strings = useStrings();
  const [target, setTarget] = useState(options.find((o) => o.value === initialTarget)?.value ?? options[0]?.value ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmed = reason.trim();

  async function submit() {
    setBusy(true);
    try {
      await onSubmit(target, trimmed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={strings.lifecycle.skipTitle(noun)} onClose={onClose}>
      <div className="stack">
        <LabeledSelect
          required label={strings.lifecycle.skipTarget} help={strings.help.lifecycleSkipTarget} value={target}
          options={options} onChange={setTarget} placeholder={null}
        />
        <TextAreaField
          required label={strings.lifecycle.skipReason} help={strings.help.lifecycleSkipReason} value={reason} onChange={setReason}
          plainText="The reason is one audit note of at most 500 characters, shown as a line in the record's history"
          inputProps={{ maxLength: SKIP_REASON_MAX_LENGTH }}
        />
        <FormActions
          onCancel={onClose} onSave={() => void submit()} saveLabel={strings.lifecycle.skipConfirm}
          saveDisabled={busy || target === "" || trimmed === ""} cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
