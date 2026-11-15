/**
 * Module: components/EditHistoryButtons
 *
 * The Undo and Redo buttons of an editor with a local edit history, and the keys that do the same.
 *
 * Responsibilities:
 * - Draw both buttons, unavailable when there is no step to take or the editor cannot be edited.
 * - Install the keyboard shortcuts (`useHistoryShortcuts`) so the buttons and the keys cannot disagree.
 * - Say, in each button's tooltip, which key does the same for the person's platform and what Undo does not reach.
 *
 * Design decisions:
 * - One component for the pair, so the block diagram and state machine diagram editors (and any later editor) share one
 *   wording and one key rule.
 * - The history is the editor's unsaved drawing only. A record created at once from the editor is already stored, so the
 *   tooltip states that Undo does not remove it.
 */
import { Fragment } from "react";

import { Tooltip } from "./Tooltip";
import { useHistoryShortcuts } from "../hooks/useHistoryShortcuts";
import { historyButtonHelp } from "../utils/historyButtonHelp";
import { isApplePlatform } from "../utils/platform";

/**
 * @param props `editable` is false for a read-only editor; `canUndo` and `canRedo` say whether a step is available;
 *   `undo` and `redo` take it.
 * @returns The two buttons, to be placed in the editor's toolbar.
 */
export function EditHistoryButtons({ editable, canUndo, canRedo, undo, redo }: {
  editable: boolean; canUndo: boolean; canRedo: boolean; undo: () => void; redo: () => void;
}) {
  useHistoryShortcuts({ enabled: editable, canUndo, canRedo, undo, redo });
  const help = historyButtonHelp(isApplePlatform());
  return (
    <Fragment>
      <Tooltip label={help.undo} wrap>
        <button type="button" className="btn btn-sm" aria-keyshortcuts={help.undoKeys} disabled={!editable || !canUndo} onClick={undo}>Undo</button>
      </Tooltip>
      <Tooltip label={help.redo} wrap>
        <button type="button" className="btn btn-sm" aria-keyshortcuts={help.redoKeys} disabled={!editable || !canRedo} onClick={redo}>Redo</button>
      </Tooltip>
    </Fragment>
  );
}
