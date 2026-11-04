/**
 * Module: components/Modal
 *
 * The app's centred dialog: `ModalBase` chrome plus the unsaved-changes guard (`useDialogGuard`).
 * A dialog that holds a form is left only by Save, or by the close button / Escape followed by a
 * confirmed discard when it has unsaved changes; a click on the backdrop does nothing. A dialog with
 * no form (a viewer, a picker, a confirm) still closes on a backdrop click.
 */
import type { ReactNode } from "react";

import { ModalBase } from "./ModalBase";
import { useDialogGuard } from "./useDialogGuard";

/**
 * @param title The dialog title.
 * @param onClose Closes the dialog (unmounts it); the guard calls it once nothing is unsaved or the discard is confirmed.
 * @param children The dialog body.
 * @param size "md" (default) for a small form or viewer, "lg" for a busy multi-field form.
 * @param dirty Whether the form has unsaved changes, compared by value against what was opened. Omit it and a
 *   dialog that renders `FormActions` is measured from its inputs instead; pass it for state the DOM does not show.
 * @param dismissOnBackdrop Overrides whether a backdrop click closes (default: only a dialog with no form).
 */
export function Modal({
  title, onClose, children, size = "md", dirty, dismissOnBackdrop,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  size?: "md" | "lg";
  dirty?: boolean;
  dismissOnBackdrop?: boolean;
}) {
  const guard = useDialogGuard(onClose, dirty, dismissOnBackdrop);
  return (
    <>
      <ModalBase
        title={title}
        size={size}
        onClose={guard.requestClose}
        onBackdropClick={guard.backdropCloses ? guard.requestClose : undefined}
        guard={guard.frame}
      >
        {children}
      </ModalBase>
      {guard.prompt}
    </>
  );
}
