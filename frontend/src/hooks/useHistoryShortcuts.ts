/**
 * Module: hooks/useHistoryShortcuts
 *
 * The Undo and Redo keys for an editor that keeps its own edit history (the block diagram and state machine diagram editors).
 *
 * Responsibilities:
 * - Match the platform's keys: Undo is Cmd+Z on Apple devices and Ctrl+Z elsewhere; Redo is Cmd+Shift+Z on Apple devices and
 *   Ctrl+Shift+Z or Ctrl+Y elsewhere. The key is matched by the character it types, in either case, never by its position.
 * - Act only where the editor's history is meant: not while text is being typed (the field keeps its own undo), not while a
 *   dialog, menu or pop-over is open, and not when the editor cannot be edited.
 *
 * Design decisions:
 * - One document listener in the capture phase, so the keys work when focus is on the canvas, the toolbar or nowhere in
 *   particular, and run before the graph canvas's own key handling (React Flow marks keys pressed on a node as handled).
 * - `preventDefault` is called only when a step was taken, so the browser keeps every key it was not asked to handle.
 * - The match and the blocking rule are plain exported functions so they are tested without a browser event.
 */
import { useEffect } from "react";

import { useLatest } from "./useLatest";
import { isTextEntryTarget, overlayIsOpen } from "../utils/keyboardTargets";
import { isApplePlatform } from "../utils/platform";

/** What a key press asks of the history. */
export type HistoryAction = "undo" | "redo";

/** The fields of a keyboard event the match reads. */
export type HistoryKeyEvent = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">;

/**
 * @param event The key press.
 * @param apple Whether the device is an Apple one.
 * @returns `"undo"` or `"redo"` for the platform's keys, or null for any other key (including the other platform's modifier).
 */
export function historyAction(event: HistoryKeyEvent, apple: boolean): HistoryAction | null {
  if (event.altKey) return null;
  // Command on Apple devices and Control elsewhere: the other modifier is never accepted, so the Windows key is never taken.
  if (apple ? !event.metaKey || event.ctrlKey : !event.ctrlKey || event.metaKey) return null;
  const key = event.key.toLowerCase();
  if (key === "z") return event.shiftKey ? "redo" : "undo";
  if (key === "y" && !apple && !event.shiftKey) return "redo";
  return null;
}

/**
 * @param target Where the key press happened.
 * @param root The document to look for an open dialog or pop-over in.
 * @returns True when the key must be left alone: text is being typed, or a dialog, menu or pop-over is open.
 */
export function historyShortcutBlocked(target: EventTarget | null, root: Document = document): boolean {
  return isTextEntryTarget(target) || overlayIsOpen(root);
}

/**
 * Listens for the Undo and Redo keys while the calling editor is mounted.
 *
 * @param history `undo` and `redo` are the editor's own steps; `canUndo` and `canRedo` say whether there is a step to take;
 *   `enabled` is false for a read-only editor.
 */
export function useHistoryShortcuts(history: {
  enabled: boolean; canUndo: boolean; canRedo: boolean; undo: () => void; redo: () => void;
}): void {
  const latest = useLatest(history);
  useEffect(() => {
    const apple = isApplePlatform();
    function onKeyDown(event: KeyboardEvent) {
      const current = latest.current;
      if (!current.enabled || event.defaultPrevented || event.isComposing) return;
      const action = historyAction(event, apple);
      if (!action || historyShortcutBlocked(event.target)) return;
      if (action === "undo" ? !current.canUndo : !current.canRedo) return;
      event.preventDefault();
      if (action === "undo") current.undo();
      else current.redo();
    }
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [latest]);
}
