/**
 * Module: components/FormActions
 *
 * The footer every create/edit dialog ends with: the save error (if any), then Cancel and the primary
 * Save button on the right. One component so the error colour, button order and spacing stay the same
 * in every form (docs/ux-style-guide.md, "Pattern: compact forms and add-on-demand").
 */
import type { ReactNode } from "react";

import { t } from "../i18n/strings";

const strings = t();

/**
 * @param error A save error to show above the buttons.
 * @param onCancel Called by Cancel.
 * @param onSave Called by the primary button.
 * @param saveLabel The primary button's text (default "Save"; callers with a verb such as "Create" pass it).
 * @param saveDisabled Disables the primary button, normally while the form is invalid.
 * @param onSaveAndActivate Offers "Save and activate" beside Save: creates the record already active. Pass it only
 *   on a create form for a type whose activation has no gate beyond creating it (docs/ux-style-guide.md, "Pattern:
 *   Save and activate"); it is disabled with Save.
 * @param leading Controls pinned to the left edge (a Back or Reset button); Cancel and Save stay on the right.
 * @param children Extra controls placed before Cancel (e.g. a secondary action).
 */
export function FormActions({
  error, onCancel, onSave, saveLabel = strings.common.save, saveDisabled, onSaveAndActivate, leading, children,
}: {
  error?: string | null;
  onCancel: () => void;
  onSave: () => void;
  saveLabel?: ReactNode;
  saveDisabled?: boolean;
  onSaveAndActivate?: () => void;
  leading?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <>
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ justifyContent: leading ? "space-between" : "flex-end" }}>
        {leading}
        <div className="row">
          {children}
          <button className="btn" onClick={onCancel}>{strings.common.cancel}</button>
          {onSaveAndActivate && (
            <button className="btn" disabled={saveDisabled} onClick={onSaveAndActivate}>{strings.common.saveAndActivate}</button>
          )}
          <button className="btn btn-primary" disabled={saveDisabled} onClick={onSave}>{saveLabel}</button>
        </div>
      </div>
    </>
  );
}
