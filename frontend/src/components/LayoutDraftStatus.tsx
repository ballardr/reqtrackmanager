/**
 * Module: components/LayoutDraftStatus
 *
 * The draft controls beside the designer's Save new version, shared by the Blocks, Text and JSON views: a quiet
 * status line saying what the shared draft holds, the per-person Autosave switch and, with autosave off, Save
 * draft and Discard changes. It chooses the one sentence true now (saving, saved at a time, not saved and why,
 * changes not in a draft, no draft); failure and unreadable content outrank "Saving..." so a reassurance never
 * covers a problem. The status line is the autosave feedback (a toast every few seconds would be noise); the
 * caller toasts the two actions. It holds no draft state: `useLayoutDraft` supplies it.
 */
import type { DraftFailure } from "../hooks/useLayoutDraft";
import { useStrings } from "../context/TerminologyContext";
import { ToggleField } from "./FormFields";

/**
 * @param autosave Whether autosave is on (the person's preference).
 * @param onAutosave Changes the preference.
 * @param savedAt When the draft the server holds was last written (ISO), `null` when there is none.
 * @param pending The editor holds changes the server does not.
 * @param saving A write is under way.
 * @param failure The last write failed.
 * @param unreadable Why the content cannot be stored yet (already worded: "line 7"), else `null`.
 * @param onSaveDraft Writes the draft now (autosave off).
 * @param onDiscardChanges Asks to put the editor back (autosave off).
 */
export function LayoutDraftStatus({
  autosave, onAutosave, savedAt, pending, saving, failure, unreadable, onSaveDraft, onDiscardChanges,
}: {
  autosave: boolean;
  onAutosave: (next: boolean) => void;
  savedAt: string | null;
  pending: boolean;
  saving: boolean;
  failure: DraftFailure | null;
  unreadable: string | null;
  onSaveDraft: () => void;
  onDiscardChanges: () => void;
}) {
  const strings = useStrings();
  const text = strings.layoutDraft;
  let status: string;
  let problem = false;
  if (failure !== null) {
    status = text.notSaved(failure === "offline" ? text.reasonOffline : text.reasonError);
    problem = true;
  } else if (unreadable !== null) {
    status = text.notSaved(unreadable);
    problem = true;
  } else if (saving || (autosave && pending)) {
    status = text.saving;
  } else if (!autosave && pending) {
    status = text.notInDraft;
  } else if (savedAt !== null) {
    status = text.savedAt(new Date(savedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  } else {
    status = text.none;
  }
  return (
    <div className="designer-bar__draft">
      <span role="status" aria-label={text.statusLabel} className="text-muted" style={problem ? { color: "var(--color-danger)" } : undefined}>
        {status}
      </span>
      {!autosave && (
        <>
          <button type="button" className="btn btn-sm" disabled={!pending || saving || unreadable !== null} onClick={onSaveDraft}>
            {text.saveDraft}
          </button>
          <button type="button" className="btn btn-sm" disabled={!pending || saving} onClick={onDiscardChanges}>
            {text.discardChanges}
          </button>
        </>
      )}
      <ToggleField label={text.autosaveLabel} checked={autosave} onChange={onAutosave} help={strings.help.layoutAutosave} />
    </div>
  );
}
