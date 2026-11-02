/**
 * Module: components/DiscardChangesDialog
 *
 * The prompt a dialog shows when it is closed with unsaved changes (`useDialogGuard`): Keep editing
 * (the default focus) or Discard. A two-tier-1 confirm like `ConfirmDialog`, built on `ModalBase` so
 * the prompt itself is never guarded, and a click outside it does nothing.
 */
import { t } from "../i18n/strings";
import { ModalBase } from "./ModalBase";

const strings = t();

/**
 * @param onKeepEditing Called by Keep editing, Escape and the close button; the dialog stays open.
 * @param onDiscard Called by Discard; the caller closes the dialog and its changes are lost.
 */
export function DiscardChangesDialog({ onKeepEditing, onDiscard }: { onKeepEditing: () => void; onDiscard: () => void }) {
  return (
    <ModalBase title={strings.common.discardTitle} onClose={onKeepEditing}>
      <p className="text-muted" style={{ margin: 0 }}>{strings.common.discardMessage}</p>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onKeepEditing}>{strings.common.keepEditing}</button>
        <button className="btn btn-danger" onClick={onDiscard}>{strings.common.discardConfirm}</button>
      </div>
    </ModalBase>
  );
}
