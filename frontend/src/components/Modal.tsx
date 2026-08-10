import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { t } from "../i18n/strings";

const strings = t();

/**
 * A simple centred dialog overlay, rendered through a portal into
 * `document.body` so it's never clipped by a scrollable ancestor (same
 * reasoning as `Tooltip`). Closes on Escape or a click on the backdrop;
 * the dialog itself stops propagation so clicks inside it don't bubble to
 * the backdrop's close handler.
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
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

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
        className="card stack"
        role="dialog"
        aria-modal="true"
        aria-label={title}
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
