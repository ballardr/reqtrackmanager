/**
 * Module: components/ApproveChangeRequestDialog
 *
 * The approver's dialog for a change request that proposes links: every proposed link is shown
 * with a tick, all ticked by default, and the approver unticks any or all before approving.
 * Fed by the server's merge preview, which re-checks each link now (never trusting what was
 * valid when it was proposed): a link that cannot be merged (its type is hidden, the record is
 * gone or already linked, the approver cannot see it, the proposer lost the right to link, ...)
 * is shown disabled with the reason and stays on the request.
 *
 * If a ticked link becomes invalid between the preview and the click, the server refuses with a
 * fresh preview; the dialog swaps it in, drops the ticks that no longer apply and asks the
 * approver to confirm again, so a link is never silently left out.
 *
 * Approving with nothing ticked is allowed (the request's other changes still apply); for an
 * add-link request that means applying nothing at all, which the dialog says, pointing to
 * Reject.
 */
import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ChangeRequestKind, ProposedLinkPreview, ProposedLinkPreviewRow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Modal } from "./Modal";
import { ProposedLinkRow } from "./ProposedLinkRow";

export function ApproveChangeRequestDialog({
  projectId,
  crId,
  kind,
  note,
  clearCompletion = false,
  onApproved,
  onClose,
}: {
  projectId: string;
  crId: string;
  kind: ChangeRequestKind;
  /** The decision note typed on the page. */
  note: string;
  /** Also clear the requirement's completion (a modify request whose target is completed). */
  clearCompletion?: boolean;
  /** Called once the request is approved. */
  onApproved: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [rows, setRows] = useState<ProposedLinkPreviewRow[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const base = `/api/v1/projects/${projectId}/change-requests/${crId}`;

  useEffect(() => {
    let active = true;
    api.get<ProposedLinkPreview>(`${base}/link-merge-preview`)
      .then((preview) => {
        if (!active) return;
        setRows(preview.rows);
        setSelected(new Set(preview.rows.filter((r) => r.selectable).map((r) => r.link.id)));
      })
      .catch((err) => {
        if (!active) return;
        setRows([]);
        showToast(toErrorMessage(err, strings.changeRequests.previewFailed), "error");
      });
    return () => {
      active = false;
    };
    // showToast and strings are stable enough for this fetch; refetching on them would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  const selectable = (rows ?? []).filter((r) => r.selectable);
  const count = selectable.filter((r) => selected.has(r.link.id)).length;

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function approve() {
    setSaving(true);
    setNotice(null);
    try {
      await api.post(`${base}/decide`, {
        approve: true, note, clear_completion: clearCompletion || undefined,
        merge_link_ids: selectable.filter((r) => selected.has(r.link.id)).map((r) => r.link.id),
      });
      onApproved();
    } catch (err) {
      const preview = err instanceof ApiError && err.status === 409
        ? (err.detail as { preview?: ProposedLinkPreview } | undefined)?.preview
        : undefined;
      if (preview) {
        // The list changed under the approver: show the fresh one and keep only the ticks that still apply.
        const stillValid = new Set(preview.rows.filter((r) => r.selectable).map((r) => r.link.id));
        setRows(preview.rows);
        setSelected((current) => new Set([...current].filter((id) => stillValid.has(id))));
        setNotice(strings.changeRequests.linksChangedNotice);
      } else {
        showToast(toErrorMessage(err, strings.common.error), "error");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={strings.changeRequests.approveDialogTitle} onClose={onClose} size="lg">
      <div className="stack">
        <p style={{ margin: 0 }}>{strings.changeRequests.approveDialogIntro}</p>
        {rows === null ? (
          <p className="text-muted" style={{ margin: 0 }}>{strings.changeRequests.previewLoading}</p>
        ) : (
          <>
            <div className="row">
              <button
                type="button" className="btn"
                onClick={() => setSelected(new Set(selectable.map((r) => r.link.id)))}
                disabled={selectable.length === 0}
              >
                {strings.changeRequests.selectAllLinks}
              </button>
              <button type="button" className="btn" onClick={() => setSelected(new Set())} disabled={count === 0}>
                {strings.changeRequests.selectNoLinks}
              </button>
            </div>
            <ul className="artefact-links__list">
              {rows.map((row) => {
                const phrase = row.link.phrase ?? "";
                const target = row.link.other_label ?? strings.changeRequests.hiddenRecord;
                return (
                  <ProposedLinkRow
                    key={row.link.id}
                    muted={!row.selectable}
                    view={{
                      phrase: row.link.phrase, label: row.link.other_label, typeLabel: row.link.other_type_label,
                      projectName: row.link.other_project_name,
                    }}
                    leading={
                      <input
                        type="checkbox"
                        aria-label={strings.changeRequests.mergeLinkLabel(phrase, target)}
                        checked={row.selectable && selected.has(row.link.id)}
                        disabled={!row.selectable || saving}
                        onChange={() => toggle(row.link.id)}
                      />
                    }
                    trailing={
                      !row.selectable && (
                        <span className="text-muted">
                          {row.already_linked ? strings.changeRequests.alreadyLinked : row.reason}
                        </span>
                      )
                    }
                  />
                );
              })}
            </ul>
          </>
        )}
        {notice && <p role="status" style={{ margin: 0, color: "var(--color-danger)" }}>{notice}</p>}
        {rows !== null && count === 0 && kind === "add_link" && (
          <p role="status" className="text-muted" style={{ margin: 0 }}>{strings.changeRequests.appliesNothingNotice}</p>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>{strings.common.cancel}</button>
          <button className="btn btn-primary" disabled={rows === null || saving} onClick={() => void approve()}>
            {count > 0 ? strings.changeRequests.approveMergeLinks(count) : strings.changeRequests.approveWithoutLinks}
          </button>
        </div>
      </div>
    </Modal>
  );
}
