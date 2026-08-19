import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { t } from "../i18n/strings";
import { useDialogA11y } from "./dialogA11y";

const strings = t();

/**
 * A simple centred dialog overlay, rendered through a portal into
 * `document.body` so it's never clipped by a scrollable ancestor (same
 * reasoning as `Tooltip`). Closes on Escape or a click on the backdrop;
 * the dialog itself stops propagation so clicks inside it don't bubble to
 * the backdrop's close handler.
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
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1100,
        padding: "1rem",
      }}
    >
      <div
        ref={dialogRef}
        className="card stack"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 560, width: "100%", maxHeight: "80vh", overflowY: "auto" }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
          <button className="btn" onClick={onClose} aria-label={strings.common.close} title={strings.common.close}>
            <X size={14} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}
