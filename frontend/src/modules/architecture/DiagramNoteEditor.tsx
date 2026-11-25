/**
 * Module: modules/architecture/DiagramNoteEditor
 *
 * The Selection card's form for an annotation note: its title, text, tone, alignment and size, and its list of leader lines.
 *
 * Responsibilities:
 * - Edit the title and the text locally and apply each when its field loses focus, so one edit is one undo step (not one per
 *   keystroke); the tone, alignment and size apply at once. The line breaks typed in the text are kept.
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
import { TextAreaField, TextField } from "../../components/FormFields";
import { IconAction } from "../../components/IconAction";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useLatest } from "../../hooks/useLatest";
import { labelOptions } from "../../utils/labelOptions";
import { MAX_NOTE_LEADERS, noteFrame, type EditorNote, type NotePatch } from "./noteModel";
import { ARCHITECTURE_HELP } from "./help";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import {
  NOTE_SIZE_MODE_LABEL, NOTE_TEXT_ALIGN_LABEL, NOTE_TITLE_MAX, NOTE_TONE_LABEL, type NoteSizeMode, type NoteTextAlign, type NoteTone,
} from "./types";

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
 * @param onChange Called with what changed: the title or the text when its field loses focus, the tone, alignment or size at once.
 * @param onAddLeader Called to add a leader (a line to a free spot beside the note, selected to be edited).
 * @param onOpenLeader Called with a leader's key to select it.
 * @param onRemove Called to remove the note.
 */
export function DiagramNoteEditor({
  note, editable, leaders, autoFocusText, onFocused, onChange, onAddLeader, onOpenLeader, onRemove,
}: {
  note: EditorNote;
  editable: boolean;
  leaders: LeaderRow[];
  autoFocusText: boolean;
  onFocused: () => void;
  onChange: (patch: NotePatch) => void;
  onAddLeader: () => void;
  onOpenLeader: (key: string) => void;
  onRemove: () => void;
}) {
  const [draft, setDraft] = useState(note.text);
  const [titleDraft, setTitleDraft] = useState(note.title);
  // An Undo or a Redo changes the note under the card: the fields show it again rather than what was typed before.
  const [seenText, setSeenText] = useState(note.text);
  const [seenTitle, setSeenTitle] = useState(note.title);
  if (seenText !== note.text) {
    setSeenText(note.text);
    setDraft(note.text);
  }
  if (seenTitle !== note.title) {
    setSeenTitle(note.title);
    setTitleDraft(note.title);
  }
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
      <div className="stack" onBlur={() => { if (titleDraft !== note.title) onChange({ title: titleDraft }); }}>
        <TextField
          label="Title" help={ARCHITECTURE_HELP.noteTitle} value={titleDraft} onChange={setTitleDraft} disabled={!editable}
          inputProps={{ maxLength: NOTE_TITLE_MAX }}
        />
      </div>
      <div ref={textBox} className="stack" onBlur={() => { if (draft !== note.text) onChange({ text: draft }); }}>
        <TextAreaField plainText="Text drawn inside a note shape on the diagram, which exports as a diagram label" label="Note text" help={ARCHITECTURE_HELP.noteText} value={draft} onChange={setDraft} disabled={!editable} />
      </div>
      <LabeledSelect
        label="Alignment" help={ARCHITECTURE_HELP.noteAlign} placeholder={null} disabled={!editable} value={note.textAlign}
        options={labelOptions(NOTE_TEXT_ALIGN_LABEL)} onChange={(value) => onChange({ textAlign: value as NoteTextAlign })}
      />
      <LabeledSelect
        label="Tone" help={ARCHITECTURE_HELP.noteTone} placeholder={null} disabled={!editable} value={note.tone}
        options={labelOptions(NOTE_TONE_LABEL)} onChange={(value) => onChange({ tone: value as NoteTone })}
      />
      <LabeledSelect
        label="Size" help={ARCHITECTURE_HELP.noteSize} placeholder={null} disabled={!editable} value={note.sizeMode}
        options={labelOptions(NOTE_SIZE_MODE_LABEL)}
        // Choosing Manual keeps the size the note is drawn at now; choosing Automatic keeps the stored size for a return to Manual.
        onChange={(value) => onChange(value === "manual" ? { sizeMode: "manual", ...noteFrame(note) } : { sizeMode: value as NoteSizeMode })}
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
