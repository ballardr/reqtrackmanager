/**
 * Module: components/ReportPackSetFormModal
 *
 * The dialog that edits a saved set of a pack's variables: a new set (a name and values), a set's values and name,
 * or one project's override of a shared set (no name; only what the project changes is kept).
 *
 * Responsibilities:
 * - Show one control per pack variable (`ReportVariablesForm`, so options and list controls match the run form).
 *   A variable left empty is simply not part of the set and falls back to its default when the pack runs.
 * - For an override, send only the variables whose value differs from the shared set's, so the rest keeps following
 *   it (the project sees the shared value beside its own on the sets screen).
 * - Show the server's refusal (a taken name, a value that does not fit) in the dialog.
 */
import { useState } from "react";

import type { PackValues } from "../api/reportPacks";
import { hasVariableValue, type ReportVariable, type VariableValue, type VariableValues } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { Modal } from "./Modal";
import { ReportVariablesForm } from "./ReportVariablesForm";

/**
 * @param title The dialog's title.
 * @param variables The pack's variables with their options.
 * @param initialName The set's name; `null` for an override (the name is not editable).
 * @param initialValues The values to start from (the set's own, or for an override the values the project runs with).
 * @param sharedValues Override only: the shared set's values; only differences from these are saved.
 * @param hint A line under the title.
 * @param onSave Saves the name (when editable) and the values to send; it may throw, and the message is shown.
 * @param onClose Called by Cancel and after a save.
 */
export function ReportPackSetFormModal({
  title, variables, initialName, initialValues, sharedValues, hint, onSave, onClose,
}: {
  title: string;
  variables: ReportVariable[];
  initialName: string | null;
  initialValues: PackValues;
  sharedValues?: PackValues;
  hint?: string;
  onSave: (name: string, values: PackValues) => Promise<void>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const [name, setName] = useState(initialName ?? "");
  const [values, setValues] = useState<VariableValues>({ ...initialValues });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    const chosen: PackValues = {};
    for (const variable of variables) {
      const value = values[variable.name];
      if (value === null || value === undefined || !hasVariableValue(value)) continue;
      // An override keeps only what differs from the shared set.
      if (sharedValues && JSON.stringify(sharedValues[variable.name]) === JSON.stringify(value)) continue;
      chosen[variable.name] = value;
    }
    try {
      await onSave(name.trim(), chosen);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        {hint && <p className="text-muted" style={{ margin: 0 }}>{hint}</p>}
        {initialName !== null && (
          <TextField helpNotNeeded required
            label={text.setName} value={name} onChange={setName} inputProps={{ maxLength: 200, autoFocus: true }}
          />
        )}
        {variables.length === 0 ? (
          <p className="text-muted">{text.setsNeedVariables}</p>
        ) : (
          <ReportVariablesForm
            // No variable is required in a set: a non-null default keeps the form from marking one.
            variables={variables.map((v) => ({ ...v, default: v.multiple ? [] : "" }))}
            values={values}
            onChange={(variable: string, value: VariableValue | null) => setValues((current) => ({ ...current, [variable]: value }))}
          />
        )}
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void save()}
          saveLabel={strings.common.save}
          saveDisabled={busy || (initialName !== null && name.trim() === "")}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
