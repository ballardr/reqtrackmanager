/**
 * Module: components/RestoreOrgDefaultsButton
 *
 * The "Add organisation defaults" control for any project-scoped definition list
 * that inherits organisation defaults a project can hide (style guide: "Pattern:
 * organisation defaults in a project"). Renders nothing while nothing is hidden;
 * otherwise a button that opens a dialog listing the hidden defaults, all ticked,
 * so the admin restores everything or a chosen subset.
 *
 * The caller owns the data: it passes the hidden rows and `onRestore`, which
 * receives the ticked ids and performs the call, toast and reload. Used by
 * `ProjectTypeVocabularyPanel`; a future definition table passes its own rows.
 */
import { Plus } from "lucide-react";
import { useState } from "react";

import { toErrorMessage } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { CheckboxField } from "./FormFields";
import { Modal } from "./Modal";

const strings = t();

/** One hidden organisation default. */
export interface HiddenDefinition {
  id: string;
  name: string;
}

export function RestoreOrgDefaultsButton({
  hidden,
  noun,
  onRestore,
}: {
  hidden: HiddenDefinition[];
  /** Plural noun for the dialog text, e.g. "Pain Point types". */
  noun: string;
  /** Restores the ticked defaults; may throw, and the message is shown in the dialog. */
  onRestore: (ids: string[]) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (hidden.length === 0) return null;

  function show() {
    setTicked(new Set(hidden.map((h) => h.id)));
    setError(null);
    setOpen(true);
  }

  async function restore() {
    setBusy(true);
    setError(null);
    try {
      await onRestore([...ticked]);
      setOpen(false);
    } catch (err) {
      setError(toErrorMessage(err, `Could not restore the ${noun}.`));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="btn" onClick={show}>
        <Plus /> Add organisation defaults ({hidden.length})
      </button>
      {open && (
        <Modal title="Add organisation defaults" onClose={() => setOpen(false)}>
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>
              These organisation {noun} were hidden in this project. Tick the ones to show again.
            </p>
            {hidden.map((h) => (
              <CheckboxField
                key={h.id}
                label={h.name}
                checked={ticked.has(h.id)}
                onChange={(on) =>
                  setTicked((current) => {
                    const next = new Set(current);
                    if (on) next.add(h.id);
                    else next.delete(h.id);
                    return next;
                  })
                }
              />
            ))}
            {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setOpen(false)}>
                {strings.common.cancel}
              </button>
              <button className="btn btn-primary" onClick={restore} disabled={busy || ticked.size === 0}>
                Add {ticked.size === 1 ? "1 default" : `${ticked.size} defaults`}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
