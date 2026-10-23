import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useDialogA11y } from "./dialogA11y";
import { DialogFrame } from "./DialogHeader";

/**
 * A right-anchored sliding-in panel for a multi-field create/edit flow —
 * the "layer, not a page reflow" half of style guide Principle 3
 * (`docs/ux-style-guide.md`, "Pattern: create panels, popovers, and one
 * door for bulk"), for content too field-heavy for `Popover`. Structurally
 * the same dialog chrome as `Modal` — portalled to `document.body`,
 * backdrop click and Escape close it, focus is trapped and restored (see
 * `dialogA11y.ts`) — but anchored to the right edge and full-height instead
 * of centred, so the page underneath stays visible and in place rather
 * than being replaced.
 */
export function SidePanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
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
        <DialogFrame title={title} onClose={onClose}>
          {children}
        </DialogFrame>
      </div>
    </div>,
    document.body
  );
}
