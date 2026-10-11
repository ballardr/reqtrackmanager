/**
 * Module: components/SupersedeAction
 *
 * The "Supersede another <thing>" control some artefact types offer beside the
 * Links panel's "Add link" (Strategy, Future State, Guiding Principle, Decision).
 * Supersession is a dedicated action, not a general link: it also marks the other
 * record Superseded, so the generic add dialog never offers it and each page
 * supplies this control through `ArtefactLinksPanel`'s `actions` slot.
 *
 * The page owns what "supersede" means (which API, which records are candidates);
 * this component owns only the picker dialog, so the four pages share one
 * implementation instead of four copies.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

export interface SupersedeCandidate {
  id: string;
  label: string;
}

export function SupersedeAction({
  artefactLabel,
  loadCandidates,
  onSupersede,
  onDone,
}: {
  /** Singular display name of the record type ("Strategy"), used in the button and dialog. */
  artefactLabel: string;
  /** Loads the records this one could replace (already excluding itself). */
  loadCandidates: () => Promise<SupersedeCandidate[]>;
  /** Records that this record supersedes `oldId`; rejects with the server's message on failure. */
  onSupersede: (oldId: string) => Promise<void>;
  /** Called after a successful supersession so the page can refresh. */
  onDone?: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<SupersedeCandidate[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [saving, setSaving] = useState(false);

  async function openDialog() {
    setOpen(true);
    setChosen("");
    setCandidates(null);
    try {
      setCandidates(await loadCandidates());
    } catch (err) {
      setCandidates([]);
      showToast(toErrorMessage(err, strings.artefactLinks.supersedeFailed), "error");
    }
  }

  async function confirm() {
    setSaving(true);
    try {
      await onSupersede(chosen);
      showToast(strings.artefactLinks.superseded);
      setOpen(false);
      onDone?.();
    } catch (err) {
      showToast(toErrorMessage(err, strings.artefactLinks.supersedeFailed), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <button className="btn" onClick={() => void openDialog()}>
        {strings.artefactLinks.supersedeButton(artefactLabel)}
      </button>
      {open && (
        <Modal title={strings.artefactLinks.supersedeTitle(artefactLabel)} onClose={() => setOpen(false)}>
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.supersedeHelp(artefactLabel)}</p>
            {candidates !== null && candidates.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.supersedeNone}</p>
            ) : (
              <LabeledSelect
                label={artefactLabel}
                value={chosen}
                onChange={setChosen}
                options={(candidates ?? []).map((c) => ({ value: c.id, label: c.label }))}
              />
            )}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setOpen(false)}>{strings.common.cancel}</button>
              <button className="btn btn-primary" disabled={!chosen || saving} onClick={() => void confirm()}>
                {strings.artefactLinks.supersedeConfirm}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
