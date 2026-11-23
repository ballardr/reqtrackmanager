/**
 * Module: modules/risk_management/RiskTransitionDialog
 *
 * The dialog for one move of a risk's status: the target status is fixed by the control that opened it (Promote or a
 * row of the record's actions menu) and the person may add a comment, recorded on the new version. A refused move (an
 * unmet guard such as "needs a residual rating", or the Risk Acceptor role for Accepted) shows the backend's message
 * inside the dialog and keeps it open.
 *
 * The backend enforces `risk_manager` / `risk_acceptor`, so the dialog is offered whatever the role.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextAreaField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import { RISK_STATUS_LABEL } from "./types";
import type { Risk, RiskStatus } from "./types";

/**
 * @param risk The risk being moved.
 * @param target The status it moves to.
 * @param onTransition Moves the risk; a rejection keeps the dialog open with its message.
 * @param onClose Called when the dialog is dismissed or the move succeeds.
 */
export function RiskTransitionDialog({
  risk, target, onTransition, onClose,
}: {
  risk: Risk;
  target: RiskStatus;
  onTransition: (status: RiskStatus, comment: string) => Promise<void>;
  onClose: () => void;
}) {
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function move() {
    setError(null);
    try {
      await onTransition(target, comment);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, "Could not change this risk's status."));
    }
  }

  return (
    <Modal title={`Move ${risk.unique_code} to ${RISK_STATUS_LABEL[target]}`} onClose={onClose}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          Currently {RISK_STATUS_LABEL[risk.status]}. {target === "accepted"
            ? "Accepting a risk records that its residual risk is tolerable. It needs the Risk Acceptor role, a residual rating and acceptance criteria."
            : `The risk moves to ${RISK_STATUS_LABEL[target]}.`}
        </p>
        <TextAreaField plainText="A status change's comment is stored in the audit event and shown as one line in the activity list" helpNotNeeded
          label="Comment"
          ariaLabel="Status change comment"
          value={comment}
          onChange={setComment}
          rows={2}
        />
        <FormActions error={error} onCancel={onClose} onSave={move} saveLabel={`Move to ${RISK_STATUS_LABEL[target]}`} />
      </div>
    </Modal>
  );
}
