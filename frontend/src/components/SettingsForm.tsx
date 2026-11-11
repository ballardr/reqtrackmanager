/**
 * Module: components/SettingsForm
 *
 * The form of one group of settings that is saved together: its fields, then one Save button beneath them
 * (docs/ux-style-guide.md, Principle 7 and "Pattern: settings group save").
 *
 * Responsibilities: Save is unavailable until something changed and while a save is in flight; success is a toast
 * (nothing persistent is drawn, so a later edit never sits beside an outdated "Saved"); a failure is drawn beside the
 * button and stays until the next attempt. A lone toggle or a per-row control is not a settings group and saves at once.
 *
 * Design decisions: the caller owns the field state and says whether it is `dirty`, so each page keeps its own
 * partial-update payload; `onSave` throws to report a failure, so the component never needs to know the request.
 */
import { useState, type FormEvent, type ReactNode } from "react";

import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { InlineMessage } from "./InlineMessage";

const strings = t();

/**
 * @param dirty Whether any field differs from the saved value; Save is unavailable while false.
 * @param onSave Saves the fields; rejects with an error to report a failure (its message is shown beside Save).
 * @param successMessage The toast shown after a successful save.
 * @param saveLabel Text of the Save button (default "Save").
 * @param children The group's fields.
 */
export function SettingsForm({
  dirty, onSave, successMessage, saveLabel = strings.common.save, children,
}: {
  dirty: boolean;
  onSave: () => Promise<void>;
  successMessage: string;
  saveLabel?: string;
  children: ReactNode;
}) {
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!dirty || saving) return;
    setError(null);
    setSaving(true);
    try {
      await onSave();
      showToast(successMessage);
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      {children}
      <InlineMessage>{error}</InlineMessage>
      <button type="submit" className="btn btn-primary" disabled={!dirty || saving} style={{ alignSelf: "flex-start" }}>
        {saveLabel}
      </button>
    </form>
  );
}
