/**
 * Module: components/FormActions
 *
 * The actions of every create/edit form: the save error (if any), then Cancel and the primary
 * Save button on the right. One component so the error colour, button order and spacing stay the same
 * in every form (docs/ux-style-guide.md, "Pattern: form header").
 *
 * Inside a `Modal` or `SidePanel` it renders into the dialog's pinned header (error under the title,
 * buttons beside it) through a portal, so Save is reachable however long the form is; the form's
 * handlers and state are untouched. Outside a dialog, or inside a `Popover`, it renders inline.
 */
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { t } from "../i18n/strings";
import { useDialogSlots } from "./dialogSlots";

const strings = t();

/**
 * @param error A save error to show above the buttons.
 * @param onCancel Called by Cancel.
 * @param onSave Called by the primary button; omit it for a Cancel-only form (no primary button).
 * @param saveLabel The primary button's text (default "Save"; callers with a verb such as "Create" pass it).
 * @param saveTone "danger" styles the primary button as destructive (a reject or delete that needs a note).
 * @param cancelDisabled Disables Cancel, normally while a request is in flight.
 * @param saveDisabled Disables the primary button, normally while the form is invalid.
 * @param onSaveAndActivate Offers "Save and activate" beside Save: creates the record already active. Pass it only
 *   on a create form for a type whose activation has no gate beyond creating it (docs/ux-style-guide.md, "Pattern:
 *   Save and activate"); it is disabled with Save.
 * @param leading Controls pinned to the left edge (a Back or Reset button); Cancel and Save stay on the right.
 * @param children Extra controls placed before Cancel (e.g. a secondary action).
 */
export function FormActions({
  error, onCancel, onSave, saveLabel = strings.common.save, saveDisabled, saveTone, cancelDisabled, onSaveAndActivate, leading, children,
}: {
  error?: string | null;
  onCancel: () => void;
  onSave?: () => void;
  saveLabel?: ReactNode;
  saveDisabled?: boolean;
  saveTone?: "danger";
  cancelDisabled?: boolean;
  onSaveAndActivate?: () => void;
  leading?: ReactNode;
  children?: ReactNode;
}) {
  const slots = useDialogSlots();
  const errorNode = error ? <div style={{ color: "var(--color-danger)" }}>{error}</div> : null;
  const buttons = (
    <div className="row" style={{ justifyContent: leading ? "space-between" : "flex-end" }}>
      {leading}
      <div className="row">
        {children}
        <button className="btn" disabled={cancelDisabled} onClick={onCancel}>{strings.common.cancel}</button>
        {onSave && onSaveAndActivate && (
          <button className="btn" disabled={saveDisabled} onClick={onSaveAndActivate}>{strings.common.saveAndActivate}</button>
        )}
        {onSave && (
          <button className={saveTone === "danger" ? "btn btn-danger" : "btn btn-primary"} disabled={saveDisabled} onClick={onSave}>{saveLabel}</button>
        )}
      </div>
    </div>
  );

  if (!slots) {
    return (
      <>
        {errorNode}
        {buttons}
      </>
    );
  }
  // The header's mount points exist after its first render; until then nothing is shown.
  return (
    <>
      {slots.error && errorNode && createPortal(errorNode, slots.error)}
      {slots.actions && createPortal(buttons, slots.actions)}
    </>
  );
}
