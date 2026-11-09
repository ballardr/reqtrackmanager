/**
 * Module: components/PolicyAcceptancesDialog
 *
 * The administrators' view of who has accepted a policy that requires it: the counts, then each person the policy
 * applies to with their latest acceptance, those yet to accept the current version first. From here an administrator
 * exports the list as a CSV (every person, whatever the dialog shows) and sends a reminder to those who have not accepted.
 *
 * The server scopes the data (server policies to server administrators, an organisation's to its administrators).
 */
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { PolicyAcceptanceStatus } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { downloadBlob } from "../utils/download";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { InlineMessage } from "./InlineMessage";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import { FieldHelp } from "./FieldHelp";

/**
 * @param path The policy's administration path (`…/policies/{id}`); the status, export and reminder hang below it.
 * @param title The policy's title.
 * @param onClose Called when the dialog is dismissed.
 */
export function PolicyAcceptancesDialog({ path, title, onClose }: { path: string; title: string; onClose: () => void }) {
  const strings = useStrings();
  const text = strings.policies;
  const run = useMutation();
  const { showToast } = useToast();
  const [status, setStatus] = useState<PolicyAcceptanceStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<PolicyAcceptanceStatus>(`${path}/acknowledgements`));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, text.acceptanceLoadFailed));
    }
  }, [path, text.acceptanceLoadFailed]);

  useLoadOnChange(load, [path]);

  async function exportCsv() {
    try {
      downloadBlob(await api.getForBlob(`${path}/acknowledgements/export`), "policy-acceptances.csv");
    } catch (err) {
      showToast(toErrorMessage(err, text.exportFailed), "error");
    }
  }

  async function remind() {
    setConfirming(false);
    let notified = 0;
    const ok = await run(async () => {
      notified = (await api.post<{ notified: number }>(`${path}/acknowledgements/remind`, {})).notified;
    }, { failure: text.remindFailed });
    if (ok) showToast(text.reminded(notified));
  }

  return (
    <Modal title={text.acceptanceTitle(title)} onClose={onClose} size="lg" dirty={false}>
      {loadError ? (
        <InlineMessage>{loadError}</InlineMessage>
      ) : !status ? (
        <Spinner />
      ) : (
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="row" style={{ gap: "var(--space-2)" }}>
              <strong>{text.acceptanceSummary(status.accepted, status.required, status.version)}</strong>
              <FieldHelp label={text.acceptance} help={strings.help.policyAcceptanceStatus} />
            </span>
            <span className="row">
              <button className="btn" onClick={() => void exportCsv()}>{text.exportCsv}</button>
              <button className="btn" disabled={status.accepted >= status.required} onClick={() => setConfirming(true)}>{text.remind}</button>
            </span>
          </div>
          {status.people.length === 0 ? (
            <div className="text-muted">{text.acceptanceEmpty}</div>
          ) : (
            <table className="table" aria-label={text.acceptance}>
              <thead>
                <tr><th>{text.person}</th><th>{text.email}</th><th>{text.state}</th><th>{text.acceptedVersion}</th><th>{text.acceptedAt}</th></tr>
              </thead>
              <tbody>
                {status.people.map((p) => (
                  <tr key={p.user_id}>
                    <td>{p.display_name}</td>
                    <td>{p.email}</td>
                    <td>
                      {p.current ? <Badge tone="accent">{text.statusAccepted}</Badge>
                        : p.accepted_version !== null ? <Badge tone="warning">{text.statusEarlier}</Badge>
                        : <Badge tone="muted">{text.statusWaiting}</Badge>}
                    </td>
                    <td>{p.accepted_version ?? ""}</td>
                    <td>{p.accepted_at ? new Date(p.accepted_at).toLocaleString() : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {status.truncated && <div className="text-muted">{text.acceptanceTruncated(status.people.length)}</div>}
        </div>
      )}
      {confirming && (
        <ConfirmDialog title={text.remindTitle} message={text.remindBody} confirmLabel={text.remind} onConfirm={() => void remind()} onCancel={() => setConfirming(false)} />
      )}
    </Modal>
  );
}
