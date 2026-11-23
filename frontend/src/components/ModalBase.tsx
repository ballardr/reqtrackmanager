/**
 * Module: components/ModalBase
 *
 * The centred dialog chrome (portal, backdrop, focus trap, header frame) with no unsaved-changes
 * guard. `Modal` wraps it with the guard; `DiscardChangesDialog` (the guard's own prompt) uses it
 * directly so the prompt cannot itself ask to be discarded.
 */
import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useBodyScrollLock } from "../hooks/useBodyScrollLock";
import { useDialogA11y } from "./dialogA11y";
import { DialogFrame, type DialogGuardFrame } from "./DialogHeader";

/** `md` (default, 560px) suits a small form or viewer; `lg` (900px) suits a busy multi-field form such as the CSV
 * import wizard's column-mapping table. Both cap `maxHeight` at 80vh and scroll internally. */
const MODAL_MAX_WIDTH_PX: Record<"md" | "lg", number> = { md: 560, lg: 900 };

/**
 * A centred dialog overlay, rendered through a portal into `document.body` so a scrollable ancestor never clips it
 * (as `Tooltip`). Closes on Escape, the header close button and, when `onBackdropClick` is given, a backdrop click;
 * the dialog stops propagation so inner clicks do not reach the backdrop handler.
 *
 * The title, the form's actions (`FormActions` portals into the header) and the close button are a pinned header
 * row; only the body scrolls, so Save is reachable on a long form (`DialogHeader.tsx`, style guide "Pattern: form
 * header").
 *
 * Tab and Shift+Tab stay inside the dialog while open and focus returns to the trigger on close (style guide
 * Principle 8; `dialogA11y.ts`, shared with `SidePanel` and `Popover`). Initial focus moves in only if nothing inside
 * already has it, so a child with its own `autoFocus` (such as `RichTextEditor`'s link-URL field) wins.
 */
export function ModalBase({
  title,
  onClose,
  onBackdropClick,
  guard,
  children,
  size = "md",
}: {
  title: string;
  /** Called by Escape and the header close button. */
  onClose: () => void;
  /** Called by a click on the backdrop; omit it and the backdrop does nothing. */
  onBackdropClick?: () => void;
  /** The unsaved-changes guard's frame wiring (`useDialogGuard`); omit it for an unguarded dialog. */
  guard?: DialogGuardFrame;
  children: ReactNode;
  /** See `MODAL_MAX_WIDTH_PX` above — "md" (default) for a small form or
   * viewer, "lg" for a busy multi-field form (e.g. `CsvImportWizard`'s
   * column-mapping step). */
  size?: "md" | "lg";
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogA11y(dialogRef, onClose);
  useBodyScrollLock();

  return createPortal(
    <div
      role="presentation"
      onClick={onBackdropClick}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1100,
        padding: "var(--space-5)",
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
        style={{ maxWidth: MODAL_MAX_WIDTH_PX[size], width: "100%", maxHeight: "80vh" }}
      >
        <DialogFrame title={title} onClose={onClose} guard={guard}>
          {children}
        </DialogFrame>
      </div>
    </div>,
    document.body
  );
}
