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
  /** @param keep Whether the "keep for other projects" box was ticked when confirmed. */
  onRemove: (keep: boolean) => Promise<void>;
}

/** The option, for a vocabulary other projects inherit (link types), to leave the item behind
 * for the projects that use it, as a copy owned by each, instead of taking it away from them. */
export interface DeleteInUseKeepOption {
  /** The checkbox label, naming how many projects use it. */
  label: string;
  /** What ticking it does, in words. */
  description: string;
  /** True when, with the box ticked, nothing else is left to move or remove, so the dialog offers a plain delete. */
  nothingElseToMove: boolean;
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
  keep,
  onKeepChange,
  onDeleteKeeping,
  moveBlockedReason,
  onClose,
}: {
  title: string;
  /** The server's own message, naming how many things use the item. */
  summary: ReactNode;
  /** Further usage facts, one line each. */
  details?: string[];
  candidates: DeleteInUseCandidate[];
  /** @param keep Whether the "keep for other projects" box is ticked. */
  onMove: (replacementId: string, keep: boolean) => Promise<void>;
  remove?: DeleteInUseRemoveOption;
  /** Offered for a vocabulary other projects use; ticked by default. */
  keep?: DeleteInUseKeepOption;
  /** Called when the box is toggled, so the caller can reassess candidates against what would still move. */
  onKeepChange?: (keep: boolean) => Promise<void>;
  /** The plain delete offered when `keep.nothingElseToMove` and the box is ticked. */
  onDeleteKeeping?: () => Promise<void>;
  /** Why moving is unavailable (e.g. links held by projects the caller cannot manage); set to disable it. */
  moveBlockedReason?: string;
  onClose: () => void;
}) {
  const [keepChecked, setKeepChecked] = useState(true);
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

  async function toggleKeep(next: boolean) {
    setKeepChecked(next);
    setReplacementId("");
    if (!onKeepChange) return;
    setBusy(true);
    try {
      await onKeepChange(next);
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  const keeping = keep !== undefined && keepChecked;
  const justDelete = keeping && keep.nothingElseToMove && onDeleteKeeping !== undefined;

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
          {keep && (
            <section className="stack" style={{ gap: "0.25rem" }}>
              <label className="row" style={{ gap: "0.5rem" }}>
                <input type="checkbox" checked={keepChecked} disabled={busy} onChange={(e) => void toggleKeep(e.target.checked)} />
                <strong>{keep.label}</strong>
              </label>
              <span className="text-muted">{keep.description}</span>
            </section>
          )}
          {justDelete && (
            <div className="row">
              <button className="btn btn-danger" disabled={busy} onClick={() => run(onDeleteKeeping)}>
                {strings.admin.deleteInUseKeepButton}
              </button>
            </div>
          )}
          {!justDelete && (
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
                  disabled={!replacementId || busy || moveBlockedReason !== undefined}
                  title={moveBlockedReason ? `${strings.admin.deleteInUseRemoveBlockedPrefix}${moveBlockedReason}` : undefined}
                  onClick={() => run(() => onMove(replacementId, keeping))}
                >
                  {strings.admin.confirmDelete}
                </button>
              </div>
            )}
            {moveBlockedReason && (
              <span className="text-muted">
                {strings.admin.deleteInUseRemoveBlockedPrefix}
                {moveBlockedReason}
              </span>
            )}
            {chosen?.warning && (
              <div role="status" className="text-muted">
                {chosen.warning}
              </div>
            )}
          </section>
          )}
          {remove && !justDelete && (
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
          onConfirm={() => run(() => remove.onRemove(keeping))}
          onCancel={() => setConfirmingRemove(false)}
        />
      )}
    </>
  );
}
