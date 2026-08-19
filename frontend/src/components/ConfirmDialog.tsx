import { useState, type ReactNode } from "react";

import { t } from "../i18n/strings";
import { Modal } from "./Modal";

const strings = t();

/**
 * The two confirmation tiers from style guide "Pattern: confirmation, in
 * two tiers — and feedback, always", as one component rather than the
 * four different patterns the audit found in production (nothing at all,
 * `window.confirm`, and an ad hoc inline card with typed-name confirmation
 * on the org-delete flow): Tier 1 is a plain Cancel/confirm `Modal` for an
 * ordinary, recoverable delete/archive; Tier 2 additionally requires typing
 * `requireTypedText` (typically the exact name of the thing being deleted)
 * before the confirm button enables, for an irreversible, wide-blast-radius
 * action. Which tier renders is driven entirely by whether
 * `requireTypedText` is passed — callers don't choose a variant name.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  requireTypedText,
}: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  requireTypedText?: string;
}) {
  const [typed, setTyped] = useState("");
  const blocked = requireTypedText !== undefined && typed !== requireTypedText;

  return (
    <Modal title={title} onClose={onCancel}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          {message}
        </p>
        {requireTypedText !== undefined && (
          <input
            className="input"
            aria-label={strings.common.typeToConfirmLabel(requireTypedText)}
            placeholder={requireTypedText}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>
            {strings.common.cancel}
          </button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={blocked}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
