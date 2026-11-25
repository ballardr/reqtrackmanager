/**
 * Module: components/EditHistoryButtons
 *
 * The Undo and Redo buttons of an editor with a local edit history, and the keys that do the same, so the diagram
 * editors share one wording and key rule. Both buttons are unavailable when there is no step or the editor is
 * read-only; the shortcuts (`useHistoryShortcuts`) are installed here so buttons and keys cannot disagree. Each
 * tooltip names the platform's key and says Undo does not reach a record already created from the editor, since the
 * history covers only the editor's unsaved drawing.
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
