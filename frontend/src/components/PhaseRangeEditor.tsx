/**
 * Module: components/PhaseRangeEditor
 *
 * The dialog for the expected range of one phase of a stage, or of a component's track within it: an
 * expected start and an expected end, both calendar dates (a person's own day, never an instant). Both
 * empty removes the schedule. The caller saves; the server refuses an end before the start and its message
 * is shown here.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { DateField } from "./FormFields";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";

/**
 * @param title The dialog title (the stage and the phase).
 * @param expectedFrom The current expected start (`YYYY-MM-DD`), or null.
 * @param expectedTo The current expected end (`YYYY-MM-DD`), or null.
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the two dates (null for an empty one).
 */
export function PhaseRangeEditor({
  title, expectedFrom, expectedTo, error, onCancel, onSave,
}: {
  title: string;
  expectedFrom: string | null;
  expectedTo: string | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (expectedFrom: string | null, expectedTo: string | null) => void;
}) {
  const strings = useStrings();
  const [from, setFrom] = useState(expectedFrom ?? "");
  const [to, setTo] = useState(expectedTo ?? "");
  const reversed = from !== "" && to !== "" && from > to;
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="stack">
        <DateField label={strings.phaseSchedule.expectedFrom} help={strings.help.phaseExpectedFrom} value={from} onChange={setFrom} />
        <DateField label={strings.phaseSchedule.expectedTo} help={strings.help.phaseExpectedTo} value={to} onChange={setTo} />
        {reversed && <div style={{ color: "var(--color-danger)" }}>{strings.phaseSchedule.reversed}</div>}
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={reversed}
          onSave={() => onSave(from || null, to || null)}
        />
      </div>
    </Modal>
  );
}
