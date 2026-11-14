/**
 * Module: utils/editHistory
 *
 * An undo/redo history over any value, with a saved baseline, as plain functions with no React. An editor keeps its
 * pending edits as one value (a layout), records each edit as a step, and compares the present with what was last
 * stored to tell whether Save is needed.
 *
 * Responsibilities:
 * - `History`: past, present, future and the saved baseline.
 * - Record a step (`commitStep`), step back and forward, replace the present without a step (a merged read), and tell
 *   whether the present differs from the saved value.
 *
 * Design decisions:
 * - The value is compared through a caller-supplied signature (the part a save would send), so display data that is not
 *   stored never makes the history look edited.
 * - At most `HISTORY_LIMIT` steps are kept.
 */

/** How many steps of undo are kept. */
export const HISTORY_LIMIT = 100;

/** An undo/redo history over values of type `L`; `saved` is the value last stored on the server. */
export interface History<L> {
  past: L[];
  present: L;
  future: L[];
  saved: L;
}

/** @param value The value just loaded (it is also the saved baseline). @returns A history with no steps. */
export function startHistoryOf<L>(value: L): History<L> {
  return { past: [], present: value, future: [], saved: value };
}

/**
 * Records `next` as the new present and clears redo; an edit that changes nothing (by `signature`) adds no step.
 *
 * @param history The history.
 * @param next The value after the edit.
 * @param signature The part of a value that counts as a change, as comparable text.
 */
export function commitStep<L>(history: History<L>, next: L, signature: (value: L) => string): History<L> {
  if (signature(next) === signature(history.present)) return history;
  return { ...history, past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

/** @returns The history one step back (unchanged when there is none). */
export function undoStep<L>(history: History<L>): History<L> {
  const previous = history.past[history.past.length - 1];
  if (previous === undefined) return history;
  return { ...history, past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] };
}

/** @returns The history one step forward (unchanged when there is none). */
export function redoStep<L>(history: History<L>): History<L> {
  if (history.future.length === 0) return history;
  const [next, ...rest] = history.future;
  return { ...history, past: [...history.past, history.present], present: next, future: rest };
}

/** Replaces the present without a step (a merged read's display data is not an edit). */
export function refreshPresentOf<L>(history: History<L>, present: L): History<L> {
  return { ...history, present };
}

/** @returns True when the present differs from the saved value, by `signature`. */
export function isDirtyBy<L>(history: History<L>, signature: (value: L) => string): boolean {
  return signature(history.present) !== signature(history.saved);
}
