import { useState, type ReactNode } from "react";

import { t } from "../i18n/strings";
import { toErrorMessage } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";

const strings = t();

/** A candidate to move what uses the deleted item to; one that cannot take
 * everything is shown disabled with the reason, never silently left out. */
export interface DeleteInUseCandidate {
  id: string;
  label: string;
  /** Why this candidate cannot be chosen; set to disable it. */
  disabledReason?: string;
  /** A caution shown once this candidate is chosen (e.g. "this changes what the links mean"). */
  warning?: string;
}

/** The optional second way out for a vocabulary whose users can be deleted
 * with it (link types): a Tier-2 type-the-name confirmation. */
export interface DeleteInUseRemoveOption {
  /** What choosing it does, in words, including the count. */
  description: string;
  /** Why it is unavailable; set to disable it. */
  blockedReason?: string;
  /** Tier-2 confirmation: the exact text to type (the item's name). */
  confirmText: string;
  confirmMessage: string;
  confirmLabel: string;
  onRemove: () => Promise<void>;
}

/**
 * The one dialog for deleting a definition (status, action type, link type,
 * pain point type, ...) that is still in use — replacing the inline
 * "reassign to" row each list used to open. It says what depends on the item,
 * then offers: move everything to another item (candidates that cannot take it
 * are disabled with the reason), and, where the vocabulary opts in, delete what
 * uses it too behind a Tier-2 type-the-name confirmation (style guide,
 * "confirmation, in two tiers"). Errors from either action stay in the dialog.
 */
export function DeleteInUseDialog({
  title,
  summary,
  details = [],
  candidates,
  onMove,
  remove,
  onClose,
}: {
  title: string;
  /** The server's own message, naming how many things use the item. */
  summary: ReactNode;
  /** Further usage facts, one line each. */
  details?: string[];
  candidates: DeleteInUseCandidate[];
  onMove: (replacementId: string) => Promise<void>;
  remove?: DeleteInUseRemoveOption;
  onClose: () => void;
}) {
  const [replacementId, setReplacementId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const chosen = candidates.find((c) => c.id === replacementId);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setConfirmingRemove(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Modal title={title} onClose={onClose}>
        <div className="stack">
          <p style={{ margin: 0 }}>{summary}</p>
          {details.length > 0 && (
            <ul className="text-muted" style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          {error && (
            <div role="alert" style={{ color: "var(--color-danger)" }}>
              {error}
            </div>
          )}
          <section className="stack" style={{ gap: "0.5rem" }}>
            <strong>{strings.admin.deleteInUseMoveHeading}</strong>
            <span className="text-muted">{strings.admin.deleteInUseMoveHint}</span>
            {candidates.length === 0 ? (
              <span className="text-muted">{strings.admin.deleteInUseNoCandidates}</span>
            ) : (
              <div className="row">
                <select
                  className="input"
                  style={{ maxWidth: 360 }}
                  aria-label={strings.admin.reassignExistingTo}
                  value={replacementId}
                  onChange={(e) => setReplacementId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">—</option>
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id} disabled={c.disabledReason !== undefined}>
                      {c.disabledReason ? strings.admin.deleteInUseCandidateBlocked(c.label, c.disabledReason) : c.label}
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn-danger"
                  disabled={!replacementId || busy}
                  onClick={() => run(() => onMove(replacementId))}
                >
                  {strings.admin.confirmDelete}
                </button>
              </div>
            )}
            {chosen?.warning && (
              <div role="status" className="text-muted">
                {chosen.warning}
              </div>
            )}
          </section>
          {remove && (
            <section className="stack" style={{ gap: "0.5rem" }}>
              <strong>{strings.admin.deleteInUseRemoveHeading}</strong>
              <span className="text-muted">{remove.description}</span>
              <div className="row">
                <button
                  className="btn btn-danger"
                  disabled={busy || remove.blockedReason !== undefined}
                  title={remove.blockedReason ? `${strings.admin.deleteInUseRemoveBlockedPrefix}${remove.blockedReason}` : undefined}
                  onClick={() => setConfirmingRemove(true)}
                >
                  {strings.admin.deleteInUseRemoveButton}
                </button>
                {remove.blockedReason && (
                  <span className="text-muted">
                    {strings.admin.deleteInUseRemoveBlockedPrefix}
                    {remove.blockedReason}
                  </span>
                )}
              </div>
            </section>
          )}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={onClose} disabled={busy}>
              {strings.common.cancel}
            </button>
          </div>
        </div>
      </Modal>
      {remove && confirmingRemove && (
        <ConfirmDialog
          title={title}
          message={remove.confirmMessage}
          confirmLabel={remove.confirmLabel}
          requireTypedText={remove.confirmText}
          onConfirm={() => run(remove.onRemove)}
          onCancel={() => setConfirmingRemove(false)}
        />
      )}
    </>
  );
}
