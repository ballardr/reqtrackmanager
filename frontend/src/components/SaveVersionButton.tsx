/**
 * Module: components/SaveVersionButton
 *
 * The primary "Save new version" button of an editor that keeps versions (the report layout designer and the report
 * pack editor). Pressing it opens a `Popover` asking for an optional note on the change, rather than leaving a note
 * field on the page; saving from the popover closes it.
 *
 * Responsibilities: own the note while the popover is open, call `onSave(note)` and close the popover when it
 * reports success (a refusal, such as a version conflict, keeps it open with the note intact); disable the button
 * while the editor cannot save. The caller does the save and shows its own errors.
 *
 * Design decisions: one optional field fits a popover (style guide, "Pattern: compact forms and add-on-demand"); the
 * note is never required, so Enter in the field saves.
 */
import { useRef, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { TextField } from "./FormFields";
import { Popover } from "./Popover";

/**
 * @param disabled Whether the editor has nothing valid to save.
 * @param saving Whether a save is under way.
 * @param onSave Saves with the (trimmed) note; resolves to `true` when the version was stored.
 */
export function SaveVersionButton({
  disabled, saving, onSave,
}: { disabled: boolean; saving: boolean; onSave: (note: string) => Promise<boolean> }) {
  const text = useStrings().saveVersion;
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const anchor = useRef<HTMLButtonElement>(null);

  async function submit() {
    if (await onSave(note.trim())) {
      setNote("");
      setOpen(false);
    }
  }

  return (
    <>
      <button ref={anchor} type="button" className="btn btn-primary" disabled={disabled || saving} aria-haspopup="dialog" onClick={() => setOpen(true)}>
        {text.button}
      </button>
      {open && (
        <Popover anchorRef={anchor} title={text.title} onClose={() => setOpen(false)}>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <TextField helpNotNeeded
              label={text.noteLabel} value={note} onChange={setNote} placeholder={text.notePlaceholder}
              inputProps={{ maxLength: 500, autoFocus: true }}
            />
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setOpen(false)}>{text.cancel}</button>
              <button type="submit" className="btn btn-primary" disabled={saving}>{text.save}</button>
            </div>
          </form>
        </Popover>
      )}
    </>
  );
}
