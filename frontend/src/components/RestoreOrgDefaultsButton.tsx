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
 *
 * `RestoreOrgDefaultsDialog` is the same dialog without the button, for a list page whose actions menu
 * (`ListPageLayout`'s `menuItems`) opens it (docs/ux-style-guide.md, "Pattern: page actions menu"); the
 * button wraps it.
 */
import { Plus } from "lucide-react";
import { useState } from "react";

import { toErrorMessage } from "../context/ToastContext";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";

/** One hidden organisation default. */
export interface HiddenDefinition {
  id: string;
  name: string;
}

/**
 * The restore dialog: the hidden defaults, all ticked, and the button that shows them again.
 *
 * @param hidden The organisation defaults this project has hidden.
 * @param noun Plural noun for the dialog text, e.g. "Pain Point types".
 * @param onRestore Restores the ticked defaults; may throw, and the message is shown in the dialog.
 * @param onClose Called when the dialog is cancelled or after a restore.
 */
export function RestoreOrgDefaultsDialog({
  hidden,
  noun,
  onRestore,
  onClose,
}: {
  hidden: HiddenDefinition[];
  noun: string;
  onRestore: (ids: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(hidden.map((h) => h.id)));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function restore() {
    setBusy(true);
    setError(null);
    try {
      await onRestore([...ticked]);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, `Could not restore the ${noun}.`));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Add organisation defaults" onClose={onClose}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          These organisation {noun} were hidden in this project. Tick the ones to show again.
        </p>
        {hidden.map((h) => (
          <CheckboxField helpNotNeeded
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
        <FormActions
          error={error} onCancel={onClose} onSave={restore} saveDisabled={busy || ticked.size === 0}
          saveLabel={`Add ${ticked.size === 1 ? "1 default" : `${ticked.size} defaults`}`}
        />
      </div>
    </Modal>
  );
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

  if (hidden.length === 0) return null;

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        <Plus /> Add organisation defaults ({hidden.length})
      </button>
      {open && <RestoreOrgDefaultsDialog hidden={hidden} noun={noun} onRestore={onRestore} onClose={() => setOpen(false)} />}
    </>
  );
}
