/**
 * Module: utils/historyButtonHelp
 *
 * The words on the Undo and Redo buttons of an editor with a local edit history: the tooltip and the key list for assistive
 * technology, for the person's platform.
 *
 * Design decisions:
 * - The tooltip says what Undo does not reach (a record created at once from the editor is already stored), so the key is
 *   not mistaken for a way to remove it.
 */

/** The tooltip and `aria-keyshortcuts` text for each button on the given platform. */
export function historyButtonHelp(apple: boolean): { undo: string; redo: string; undoKeys: string; redoKeys: string } {
  const modifier = apple ? "Cmd" : "Ctrl";
  const redoKeys = apple ? `${modifier}+Shift+Z` : `${modifier}+Shift+Z or ${modifier}+Y`;
  return {
    undo: `Undo the last change to the drawing (${modifier}+Z). A record added from the diagram is created at once, so Undo does not remove it.`,
    redo: `Redo the change that was undone (${redoKeys}).`,
    undoKeys: apple ? "Meta+Z" : "Control+Z",
    redoKeys: apple ? "Meta+Shift+Z" : "Control+Shift+Z Control+Y",
  };
}
