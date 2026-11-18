/**
 * Module: modules/architecture/StateMachineNoteCards
 *
 * The Selection card's body for a selected annotation note or leader line on a state machine diagram: the shared note form
 * (`DiagramNoteEditor`) and leader form (`DiagramLeaderEditor`) with the state machine's own targets, a state or a transition.
 *
 * Responsibilities:
 * - Say what each leader points at in words and whether it is drawn, offer the diagram's states and transitions as "Points at",
 *   and suggest where an added vertex goes.
 * - Pass every change on as a callback; nothing is stored here (the page owns the drawing, its undo history and Save).
 *
 * Design decisions:
 * - One mechanism for both diagram types: only what a leader may point at differs, so only that is built here.
 */
import { useRecordCode } from "../../hooks/useRecordCode";
import { DiagramLeaderEditor } from "./DiagramLeaderEditor";
import { DiagramNoteEditor } from "./DiagramNoteEditor";
import { ARCHITECTURE_HELP } from "./help";
import {
  leaderVertexSuggestion, type EditorLeader, type EditorNote, type NoteLeaderTarget, type NotePatch,
} from "./noteModel";
import { leaderIsDrawn, leaderSummary, leaderTargetOptions, type StateMachineLayout } from "./stateMachineModel";
import type { StateMachineModel } from "./types";

/** What the cards do with a change; the page applies each as one undoable edit of the drawing. */
export interface StateMachineNoteHandlers {
  /** The note whose text takes the focus when its card appears (a note just placed), or null. */
  focusNoteKey: string | null;
  onFocused: () => void;
  onChange: (key: string, patch: NotePatch) => void;
  onAddLeader: (noteKey: string) => void;
  onSelectLeader: (leaderKey: string) => void;
  onSelectNote: (noteKey: string) => void;
  onLeaderTarget: (leaderKey: string, target: NoteLeaderTarget) => void;
  onLeaderChange: (leaderKey: string, change: Partial<EditorLeader>) => void;
  onRemoveLeader: (leaderKey: string) => void;
  onRemoveNote: (noteKey: string) => void;
}

/**
 * @param model The model as read (the states and transitions a leader may point at).
 * @param layout The drawing being edited (its notes, and where each state is).
 * @param note The selected note, or null.
 * @param leader The selected leader with its note and its position among the note's leaders (from 1), or null.
 * @param editable False makes the forms read-only.
 * @param handlers What a change does.
 */
export function StateMachineNoteCards({
  model, layout, note, leader, editable, handlers,
}: {
  model: StateMachineModel;
  layout: StateMachineLayout;
  note: EditorNote | null;
  leader: { note: EditorNote; leader: EditorLeader; index: number } | null;
  editable: boolean;
  handlers: StateMachineNoteHandlers;
}) {
  const codeOf = useRecordCode().code;
  if (leader) {
    const centreOf = (target: NoteLeaderTarget) => {
      if (target.kind === "point") return { x: target.x, y: target.y };
      if (target.kind !== "state") return null;
      const box = layout.boxes.find((b) => b.id === target.stateId);
      return box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : null;
    };
    return (
      <DiagramLeaderEditor
        key={leader.leader.key} leader={leader.leader} editable={editable}
        targets={leaderTargetOptions(model, codeOf)} help={ARCHITECTURE_HELP.leaderPointsAtStates}
        drawn={leaderIsDrawn(leader.leader, model)} newPoint={leaderVertexSuggestion(leader.note, leader.leader, centreOf)}
        defaultShape={model.diagram.line_shape}
        onTarget={(target) => handlers.onLeaderTarget(leader.leader.key, target)}
        onChange={(change) => handlers.onLeaderChange(leader.leader.key, change)}
        onOpenNote={() => handlers.onSelectNote(leader.note.key)} onRemove={() => handlers.onRemoveLeader(leader.leader.key)}
      />
    );
  }
  if (!note) return null;
  return (
    <DiagramNoteEditor
      key={note.key} note={note} editable={editable} autoFocusText={handlers.focusNoteKey === note.key} onFocused={handlers.onFocused}
      leaders={note.leaders.map((l) => ({
        key: l.key, summary: leaderSummary(l, model, codeOf), drawn: leaderIsDrawn(l, model),
      }))}
      onChange={(patch) => handlers.onChange(note.key, patch)}
      onAddLeader={() => handlers.onAddLeader(note.key)} onOpenLeader={handlers.onSelectLeader} onRemove={() => handlers.onRemoveNote(note.key)}
    />
  );
}
