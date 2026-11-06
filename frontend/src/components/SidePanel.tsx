import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useBodyScrollLock } from "../hooks/useBodyScrollLock";
import { useDialogA11y } from "./dialogA11y";
import { DialogFrame } from "./DialogHeader";
import { useDialogGuard } from "./useDialogGuard";

/**
 * A right-anchored sliding-in panel for a multi-field create/edit flow —
 * the "layer, not a page reflow" half of style guide Principle 3
 * (`docs/ux-style-guide.md`, "Pattern: create panels, popovers, and one
 * door for bulk"), for content too field-heavy for `Popover`. Structurally
 * the same dialog chrome as `Modal` — portalled to `document.body`,
 * Escape and the close button close it (asking first when a form in it has
 * unsaved changes, and a backdrop click closes it only when it holds no form; see `useDialogGuard.tsx`), focus is
 * trapped and restored (see `dialogA11y.ts`) — but anchored to the right edge and full-height instead
 * of centred, so the page underneath stays visible and in place rather
 * than being replaced.
 */
export function SidePanel({
  title,
  onClose,
  children,
  dirty,
  dismissOnBackdrop,
}: {
  title: string;
  /** Closes the panel (unmounts it); the guard calls it once nothing is unsaved or the discard is confirmed. */
  onClose: () => void;
  children: ReactNode;
  /** Whether the form has unsaved changes; omit it to have a panel that renders `FormActions` measured from its inputs. */
  dirty?: boolean;
  /** Overrides whether a backdrop click closes (default: only a panel with no form). */
  dismissOnBackdrop?: boolean;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const guard = useDialogGuard(onClose, dirty, dismissOnBackdrop);
  useDialogA11y(dialogRef, guard.requestClose);
  useBodyScrollLock();

  return createPortal(
    <>
      <div
        role="presentation"
        onClick={guard.backdropCloses ? guard.requestClose : undefined}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0, 0, 0, 0.5)",
          display: "flex",
          justifyContent: "flex-end",
          zIndex: 1100,
        }}
      >
        <div
          ref={dialogRef}
          className="card dialog-card"
          role="dialog"
          aria-modal="true"
          aria-label={title}
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
          style={{
            width: "100%",
            maxWidth: 420,
            height: "100%",
            maxHeight: "100vh",
            borderRadius: 0,
            margin: 0,
          }}
        >
          <DialogFrame title={title} onClose={guard.requestClose} guard={guard.frame}>
            {children}
          </DialogFrame>
        </div>
      </div>
      {guard.prompt}
    </>,
    document.body
  );
}
