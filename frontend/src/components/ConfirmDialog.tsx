import { useState, type ReactNode } from "react";

import { t } from "../i18n/strings";
import { Modal } from "./Modal";

const strings = t();

/**
 * The two confirmation tiers of style guide "Pattern: confirmation, in two tiers": Tier 1 is a plain
 * Cancel/confirm `Modal` for an ordinary, recoverable delete or archive; Tier 2 also requires typing
 * `requireTypedText` (typically the exact name of the thing) before confirm enables, for an irreversible,
 * wide-blast-radius action. The tier is chosen by whether `requireTypedText` is passed.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  requireTypedText,
  confirmDisabled,
}: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  requireTypedText?: string;
  /** Extra gate on the confirm button, alongside `requireTypedText`, for a `message` that embeds its own required
   * input (a "reason for change" on a confirm that submits a change request). */
  confirmDisabled?: boolean;
}) {
  const [typed, setTyped] = useState("");
  const blocked = (requireTypedText !== undefined && typed !== requireTypedText) || !!confirmDisabled;

  return (
    <Modal title={title} onClose={onCancel}>
      <div className="stack">
        {/* A div, not a p: a message may embed block content (a checkbox field) and a p cannot hold a div. */}
        <div className="text-muted" style={{ margin: 0 }}>
          {message}
        </div>
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
