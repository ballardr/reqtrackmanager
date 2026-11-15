/**
 * Module: modules/architecture/DiagramNoteEditor
 *
 * The Selection card's form for an annotation note: its text, tone, what its leader line points at and whether the line
 * ends in an arrowhead.
 *
 * Responsibilities:
 * - Edit the text locally and apply it when the field loses focus, so one edit is one undo step (not one per keystroke); the
 *   other fields apply at once.
 * - Offer the keyboard route to what dragging the line's end does: a "Points at" list of the boxes and connections that are
 *   drawn, and a "Point at a spot" action that waits for a click on the canvas.
 * - Say, rather than hide, that a leader points at something that is not drawn.
 *
 * Design decisions:
 * - Nothing here stores anything: every change is a callback, and the editor page owns the layout, its undo history and save.
 * - The list names only what is drawn, but keeps the current target selectable when it is not drawn, so the control always
 *   shows the truth.
 */
import { useEffect, useRef, useState } from "react";

import { CheckboxField, TextAreaField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useLatest } from "../../hooks/useLatest";
import { labelOptions } from "../../utils/labelOptions";
import { LEADER_SPOT_OPTION, leaderOf, leaderOptionValue, type EditorBox, type EditorNote, type NoteLeaderTarget } from "./diagramEditorModel";
import { boxName } from "./diagramOutlineModel";
import { ARCHITECTURE_HELP } from "./help";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";
import { NOTE_TONE_LABEL, type ArchitectureConnection, type NoteTone } from "./types";

/**
 * @param note The selected note.
 * @param editable Whether the layout can be changed.
 * @param boxes The boxes the diagram draws (switched-off boxes left out).
 * @param connections The connections of the drawn lines.
 * @param autoFocusText True to put the cursor in the text when the card first appears (a note just placed).
 * @param onFocused Called once the text has taken the focus.
 * @param drawn Whether the note's leader target is drawn (a leader to something switched off or removed is not).
 * @param picking Whether the next click on the canvas places the leader's end.
 * @param onText Called with the new text when the field loses focus.
 * @param onTone Called with a new tone.
 * @param onArrow Called with the arrowhead setting.
 * @param onPointAt Called with a box or connection to point at, or `none` to remove the leader.
 * @param onPickSpot Called to start (true) or cancel (false) waiting for a click on the canvas.
 * @param onRemove Called to remove the note.
 */
export function DiagramNoteEditor({
  note, editable, boxes, connections, autoFocusText, onFocused, drawn, picking, onText, onTone, onArrow, onPointAt, onPickSpot, onRemove,
}: {
  note: EditorNote;
  editable: boolean;
  boxes: EditorBox[];
  connections: ArchitectureConnection[];
  autoFocusText: boolean;
  onFocused: () => void;
  drawn: boolean;
  picking: boolean;
  onText: (text: string) => void;
  onTone: (tone: NoteTone) => void;
  onArrow: (arrow: boolean) => void;
  onPointAt: (target: NoteLeaderTarget) => void;
  onPickSpot: (picking: boolean) => void;
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
  const target = leaderOf(note);
  const current = leaderOptionValue(target);
  const options = [
    ...boxes.map((b) => ({ value: `element:${b.elementId}`, label: `Box: ${boxName(b)}` })),
    ...connections.map((c) => ({ value: `connection:${c.id}`, label: `Connection: ${c.unique_code}${c.name ? ` ${c.name}` : ""}` })),
  ];
  if (target.kind === "point") options.push({ value: LEADER_SPOT_OPTION, label: "A spot on the canvas" });
  else if (current && !options.some((o) => o.value === current)) options.push({ value: current, label: "An item not on this diagram" });

  const choose = (value: string) => {
    onPickSpot(false);
    if (value === "") onPointAt({ kind: "none" });
    else if (value.startsWith("element:")) onPointAt({ kind: "element", elementId: value.slice("element:".length) });
    else if (value.startsWith("connection:")) onPointAt({ kind: "connection", connectionId: value.slice("connection:".length) });
  };

  return (
    <div className="stack">
      <div ref={textBox} className="stack" onBlur={() => { if (draft !== note.text) onText(draft); }}>
        <TextAreaField helpNotNeeded label="Note text" value={draft} onChange={setDraft} disabled={!editable} />
      </div>
      <LabeledSelect
        label="Tone" help={ARCHITECTURE_HELP.noteTone} placeholder={null} disabled={!editable} value={note.tone}
        options={labelOptions(NOTE_TONE_LABEL)} onChange={(value) => onTone(value as NoteTone)}
      />
      <LabeledSelect
        label="Points at" help={ARCHITECTURE_HELP.notePointsAt} placeholder="Nothing" disabled={!editable} value={current}
        options={options} onChange={choose}
      />
      {editable && (
        <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
          <button type="button" className="btn btn-sm" aria-pressed={picking} onClick={() => onPickSpot(!picking)}>
            {picking ? "Cancel" : "Point at a spot"}
          </button>
          {picking && <span className="text-muted" role="status">Click the canvas to place the end of the line.</span>}
        </div>
      )}
      {target.kind !== "none" && (
        <CheckboxField
          label="Arrowhead" help={ARCHITECTURE_HELP.noteArrow} checked={note.leader_arrow} onChange={onArrow} disabled={!editable}
        />
      )}
      {target.kind !== "none" && !drawn && (
        <p className="text-muted" role="status">The line points at something that is not drawn on this diagram, so it is hidden. It returns with that item.</p>
      )}
      <SelectionActions actions={[editable && selectionAction.clear("Remove note", onRemove)]} />
    </div>
  );
}
