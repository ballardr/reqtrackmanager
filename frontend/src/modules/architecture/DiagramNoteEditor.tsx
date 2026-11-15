/**
 * Module: modules/architecture/DiagramNoteEditor
 *
 * The Selection card's form for an annotation note: its text and tone, and its list of leader lines.
 *
 * Responsibilities:
 * - Edit the text locally and apply it when the field loses focus, so one edit is one undo step (not one per keystroke); the
 *   tone applies at once.
 * - List the note's leaders ("Points at ELM-001 Gateway", with a note when one points at something that is not drawn), open
 *   one in its own card (`DiagramLeaderEditor`) and add another (the keyboard route to drawing a line from the note).
 *
 * Design decisions:
 * - Nothing here stores anything: every change is a callback, and the editor page owns the layout, its undo history and save.
 * - A leader's own settings are not on the note's card: a leader is selectable like any line, and its card holds what is
 *   specific to it, so a note with several leaders stays short.
 */
import { Pencil, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { FieldCaption } from "../../components/FieldHelp";
import { TextAreaField } from "../../components/FormFields";
import { IconAction } from "../../components/IconAction";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useLatest } from "../../hooks/useLatest";
import { labelOptions } from "../../utils/labelOptions";
import { MAX_NOTE_LEADERS, type EditorNote } from "./diagramEditorModel";
import { ARCHITECTURE_HELP } from "./help";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import { NOTE_TONE_LABEL, type NoteTone } from "./types";

/** One of a note's leaders as the card lists it. */
export interface LeaderRow {
  key: string;
  /** What it points at, in words (`leaderSummary`). */
  summary: string;
  /** Whether it is drawn; a leader that is not says so, since it is hidden with its target. */
  drawn: boolean;
}

/**
 * @param note The selected note.
 * @param editable Whether the layout can be changed.
 * @param leaders The note's leaders in order.
 * @param autoFocusText True to put the cursor in the text when the card first appears (a note just placed).
 * @param onFocused Called once the text has taken the focus.
 * @param onText Called with the new text when the field loses focus.
 * @param onTone Called with a new tone.
 * @param onAddLeader Called to add a leader (a line to a free spot beside the note, selected to be edited).
 * @param onOpenLeader Called with a leader's key to select it.
 * @param onRemove Called to remove the note.
 */
export function DiagramNoteEditor({
  note, editable, leaders, autoFocusText, onFocused, onText, onTone, onAddLeader, onOpenLeader, onRemove,
}: {
  note: EditorNote;
  editable: boolean;
  leaders: LeaderRow[];
  autoFocusText: boolean;
  onFocused: () => void;
  onText: (text: string) => void;
  onTone: (tone: NoteTone) => void;
  onAddLeader: () => void;
  onOpenLeader: (key: string) => void;
  onRemove: () => void;
}) {
  const [draft, setDraft] = useState(note.text);
  const focusDone = useLatest(onFocused);
  const [askedFocus] = useState(autoFocusText);
  const textBox = useRef<HTMLDivElement>(null);
  // The focus is moved a frame later, not by `autoFocus`: a note added from the Add menu mounts while that menu is closing, and
  // the menu's own focus return to its button runs after the mount and would take the cursor back.
  useEffect(() => {
    if (!askedFocus) return;
    const frame = requestAnimationFrame(() => {
      textBox.current?.querySelector("textarea")?.focus();
      focusDone.current();
    });
    return () => cancelAnimationFrame(frame);
  }, [askedFocus, focusDone]);

  return (
    <div className="stack">
      <div ref={textBox} className="stack" onBlur={() => { if (draft !== note.text) onText(draft); }}>
        <TextAreaField helpNotNeeded label="Note text" value={draft} onChange={setDraft} disabled={!editable} />
      </div>
      <LabeledSelect
        label="Tone" help={ARCHITECTURE_HELP.noteTone} placeholder={null} disabled={!editable} value={note.tone}
        options={labelOptions(NOTE_TONE_LABEL)} onChange={(value) => onTone(value as NoteTone)}
      />
      {(leaders.length > 0 || editable) && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <FieldCaption label="Leaders" help={ARCHITECTURE_HELP.noteLeaders} />
          {leaders.length === 0 ? <p className="text-muted">No leader lines.</p> : (
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} aria-label="Leaders">
              {leaders.map((l, i) => (
                <li key={l.key} className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap" }}>
                  <span>Points at {l.summary}</span>
                  <IconAction label={`Edit leader ${i + 1}`} onClick={() => onOpenLeader(l.key)}><Pencil /></IconAction>
                </li>
              ))}
            </ul>
          )}
          {leaders.some((l) => !l.drawn) && (
            <p className="text-muted" role="status">A line that points at something that is not drawn on this diagram is hidden. It returns with that item.</p>
          )}
          {editable && (
            <div className="row" role="group" aria-label="Leader actions" style={{ gap: "var(--space-2)" }}>
              <IconAction label="Add leader" disabled={leaders.length >= MAX_NOTE_LEADERS} onClick={onAddLeader}><Plus /></IconAction>
            </div>
          )}
        </div>
      )}
      <SelectionActions actions={[editable && selectionAction.clear("Remove note", onRemove)]} />
    </div>
  );
}
