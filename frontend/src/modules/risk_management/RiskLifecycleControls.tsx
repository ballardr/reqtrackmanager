/**
 * Module: modules/risk_management/RiskLifecycleControls
 *
 * The "Change status" transition button of a risk's detail page (Archive is an object
 * action in the record header's menu).
 * Change status opens a dialog offering exactly `risk.allowed_next_statuses`
 * (the backend's transition table, so the UI never duplicates it) with an
 * optional comment recorded on the new version. A refused move (an unmet guard
 * such as "needs a residual rating", or the Risk Acceptor role for Accepted)
 * shows the backend's message inside the dialog rather than closing it.
 *
 * The button always renders regardless of role; the backend enforces
 * `risk_manager` / `risk_acceptor`.
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import { RISK_STATUS_LABEL } from "./types";
import type { Risk, RiskStatus } from "./types";
import { FormActions } from "../../components/FormActions";
import { TextAreaField } from "../../components/FormFields";

/**
 * @param risk The risk being managed.
 * @param onTransition Moves the risk; a rejection keeps the dialog open with its message.
 */
export function RiskLifecycleControls({
  risk, onTransition,
}: {
  risk: Risk;
  onTransition: (status: RiskStatus, comment: string) => Promise<void>;
}) {
  const [changing, setChanging] = useState(false);
  const [target, setTarget] = useState<RiskStatus | "">("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  function close() {
    setChanging(false);
    setTarget("");
    setComment("");
    setError(null);
  }

  async function move() {
    if (!target) return;
    setError(null);
    try {
      await onTransition(target, comment);
      close();
    } catch (err) {
      setError(toErrorMessage(err, "Could not change this risk's status."));
    }
  }

  return (
    <>
      <button
        className="btn btn-primary" disabled={risk.is_archived || risk.allowed_next_statuses.length === 0}
        onClick={() => setChanging(true)}
      >
        Change status
      </button>

      {changing && (
        <Modal title={`Change status of ${risk.unique_code}`} onClose={close}>
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>Currently {RISK_STATUS_LABEL[risk.status]}.</p>
            <LabeledSelect helpNotNeeded
              label="New status"
              value={target}
              onChange={(next) => setTarget(next as RiskStatus | "")}
              options={risk.allowed_next_statuses.map((s) => ({ value: s, label: RISK_STATUS_LABEL[s] }))}
              placeholder="Select a status…"
            />
            {target === "accepted" && (
              <p className="text-muted" style={{ margin: 0 }}>
                Accepting a risk records that its residual risk is tolerable. It needs the Risk Acceptor role, a residual
                rating and acceptance criteria.
              </p>
            )}
            <TextAreaField helpNotNeeded
              label="Comment (optional)"
              ariaLabel="Status change comment"
              value={comment}
              onChange={setComment}
              rows={2}
            />
            <FormActions
              error={error}
              onCancel={close}
              onSave={move}
              saveLabel="Change status"
              saveDisabled={!target}
            />
          </div>
        </Modal>
      )}
    </>
  );
}
