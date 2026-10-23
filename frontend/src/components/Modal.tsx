import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useDialogA11y } from "./dialogA11y";
import { DialogFrame } from "./DialogHeader";

/** `size="md"` (the default, 560px) is the original fixed width, sized for
 * this component's first use — a small read-only vote-comment viewer.
 * `size="lg"` (900px) is the style guide's "known implementation
 * dependency" resolution for `Pattern: modal dialog for entity
 * create/rename` — a genuinely busy multi-field form (the CSV import
 * wizard's column-mapping table, a future New Project/New Organisation
 * form) needs more horizontal room than a two-sentence viewer does. Both
 * still cap `maxHeight` at 80vh and scroll internally, and both still fit
 * within the same centred-overlay chrome — only the width changes. */
const MODAL_MAX_WIDTH_PX: Record<"md" | "lg", number> = { md: 560, lg: 900 };

/**
 * A simple centred dialog overlay, rendered through a portal into
 * `document.body` so it's never clipped by a scrollable ancestor (same
 * reasoning as `Tooltip`). Closes on Escape or a click on the backdrop;
 * the dialog itself stops propagation so clicks inside it don't bubble to
 * the backdrop's close handler.
 *
 * The title, the form's actions (`FormActions` portals into the header) and the close button are
 * a pinned header row; only the body scrolls, so Save is reachable on a long form (see
 * `DialogHeader.tsx`, style guide "Pattern: form header").
 *
 * Traps Tab/Shift+Tab focus within the dialog while open, and restores
 * focus to whatever triggered it on close (style guide Principle 8 —
 * "every interactive control has a name," extended here to "and keyboard
 * focus never silently escapes it"); see `dialogA11y.ts`, shared with
 * `SidePanel` and `Popover`. Initial focus only moves into the dialog if
 * nothing inside already has it — a child that sets its own `autoFocus`
 * (e.g. `RichTextEditor`'s link-URL field) wins; this only takes over as a
 * fallback for content with no such field of its own (e.g. the read-only
 * vote-comments viewer).
 */
export function Modal({
  title,
  onClose,
  children,
  size = "md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** See `MODAL_MAX_WIDTH_PX` above — "md" (default) for a small form or
   * viewer, "lg" for a busy multi-field form (e.g. `CsvImportWizard`'s
   * column-mapping step). */
  size?: "md" | "lg";
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogA11y(dialogRef, onClose);

  return createPortal(
    <div
      role="presentation"
      onClick={onClose}
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
        <DialogFrame title={title} onClose={onClose}>
          {children}
        </DialogFrame>
      </div>
    </div>,
    document.body
  );
}
