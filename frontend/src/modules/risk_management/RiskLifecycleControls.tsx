/**
 * Module: modules/risk_management/RiskLifecycleControls
 *
 * The "Change status" and Archive/Unarchive buttons of a risk's detail page.
 * Change status opens a dialog offering exactly `risk.allowed_next_statuses`
 * (the backend's transition table, so the UI never duplicates it) with an
 * optional comment recorded on the new version. A refused move (an unmet guard
 * such as "needs a residual rating", or the Risk Acceptor role for Accepted)
 * shows the backend's message inside the dialog rather than closing it.
 * Archive is a tier-1 `ConfirmDialog` (docs/ux-style-guide.md).
 *
 * Every button always renders regardless of role; the backend enforces
 * `risk_manager` / `risk_acceptor`.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import { RISK_STATUS_LABEL } from "./types";
import type { Risk, RiskStatus } from "./types";

/**
 * @param risk The risk being managed.
 * @param onTransition Moves the risk; a rejection keeps the dialog open with its message.
 * @param onArchiveToggle Archives or unarchives the risk.
 */
export function RiskLifecycleControls({
  risk, onTransition, onArchiveToggle,
}: {
  risk: Risk;
  onTransition: (status: RiskStatus, comment: string) => Promise<void>;
  onArchiveToggle: () => Promise<void>;
}) {
  const [changing, setChanging] = useState(false);
  const [target, setTarget] = useState<RiskStatus | "">("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [archiveConfirm, setArchiveConfirm] = useState(false);

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
      <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
        <button
          className="btn btn-primary" disabled={risk.is_archived || risk.allowed_next_statuses.length === 0}
          onClick={() => setChanging(true)}
        >
          Change status
        </button>
        <button className="btn" onClick={() => setArchiveConfirm(true)}>{risk.is_archived ? "Unarchive" : "Archive"}</button>
      </div>

      {changing && (
        <Modal title={`Change status of ${risk.unique_code}`} onClose={close}>
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>Currently {RISK_STATUS_LABEL[risk.status]}.</p>
            <LabeledSelect
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
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Comment (optional)</span>
              <textarea className="input" rows={2} aria-label="Status change comment" value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
            {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={close}>Cancel</button>
              <button className="btn btn-primary" disabled={!target} onClick={move}>Change status</button>
            </div>
          </div>
        </Modal>
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={risk.is_archived ? "Unarchive this Risk?" : "Archive this Risk?"}
          message={
            risk.is_archived
              ? "This Risk will count as active again."
              : "This Risk will no longer appear in the active register. Nothing is deleted, and it remains available for historical purposes."
          }
          confirmLabel={risk.is_archived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await onArchiveToggle();
          }}
          onCancel={() => setArchiveConfirm(false)}
        />
      )}
    </>
  );
}
