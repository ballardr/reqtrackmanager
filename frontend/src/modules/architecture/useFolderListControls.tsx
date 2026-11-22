/**
 * Module: modules/architecture/useFolderListControls
 *
 * Everything the Elements, Connections and Diagrams lists share for folders, so each list adds one hook call instead of
 * its own copy: the chosen folder and the "Include sub-folders" choice (both in the page address), the folder tree for
 * the filter panel, the folder actions as rows of the page's one actions menu, the filter the list applies and sends to
 * its export, and the selection with its "Move to folder" action. A folder only organises the list: the hook changes
 * nothing about what a record is.
 */
import { useState, type ReactNode } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useUrlText } from "../../hooks/useUrlFilter";
import { FolderPanel } from "./FolderPanel";
import { useFolderActions } from "./useFolderActions";
import { inChosenFolder } from "./folderTree";
import { MoveToFolderDialog } from "./MoveToFolderDialog";
import type { FolderKind } from "./types";
import { useFolders, type FolderOwner } from "./useFolders";

/**
 * @param owner The project (or, for the organisation's own elements, the organisation) whose folders the list uses.
 * @param kind Which tree: `element`, `connection` or `diagram`.
 * @param noun The records in the plural (`elements`), for the messages.
 * @param onMoved Called after records were moved or a folder changed, so the list reads its records again.
 * @param inUrl Keep the chosen folder in the page address (default); false keeps it in component state, for a list shown
 *   inside a page whose own query parameters it must not touch (the organisation administration tabs).
 * @param organization A read-only branch of the organisation's folders for a project's list of records the organisation
 *   also owns (the symbol library): its label and the folders with their counts. Choosing one is kept beside the project's
 *   own choice (`ofolder`), and the two never hold at once.
 * @returns `matches` (a record's folder path is inside the choice), `addParams` (the export's `folder` and `subfolders`, and
 *   `folder_scope` when the choice is in the organisation's branch),
 *   `panel` (the folder tree for the filter panel), `menuItems` (New, Edit and Delete folder, for the page's actions menu),
 *   `selected` / `setSelected` (the chosen record ids, for `DirectoryTable`'s `selection`), `bar` (the bulk bar shown while
 *   records are chosen), `dialog` (the Move dialog and the folder form and confirmation), `folders` (the owner's own folders)
 *   and `chosenFolderId` (the own folder the choice names, or null: where a new record is filed by default).
 */
export function useFolderListControls(
  owner: FolderOwner, kind: FolderKind, noun: string, onMoved: () => void, inUrl = true,
  organization?: { label: string; folders: { path: string; count: number }[] },
) {
  const { showToast } = useToast();
  const [ownPath, setOwnPath] = useUrlText("folder", inUrl);
  const [branchPath, setBranchPath] = useUrlText("ofolder", inUrl);
  // The project's own choice, or else the organisation branch's (never both: choosing one clears the other).
  const folderPath = ownPath || branchPath;
  const inBranch = ownPath === "" && branchPath !== "";
  // One write at a time: two writes to the address in one handler could overwrite each other.
  const setFolderPath = (path: string) => { setOwnPath(path); if (branchPath !== "") setBranchPath(""); };
  // `nosub=1` means only the chosen folder's own records; absent means its sub-folders are included too.
  const [exactText, setExactText] = useUrlText("nosub", inUrl);
  const exactFolder = exactText === "1";
  const setExactFolder = (exact: boolean) => setExactText(exact ? "1" : "");
  const folderState = useFolders(owner, kind);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);

  const chosenFolderId = folderState.folders.find((f) => f.path === ownPath)?.id ?? null;
  const matches = (recordPath: string | null) => inChosenFolder(recordPath, folderPath, !exactFolder);

  function addParams(params: URLSearchParams) {
    if (!folderPath) return;
    params.set("folder", folderPath);
    if (inBranch) params.set("folder_scope", "organization");
    if (!exactFolder) params.set("subfolders", "true");
  }

  const actions = useFolderActions({
    noun, folders: folderState.folders, calls: folderState.calls, selectedPath: ownPath, onSelect: setFolderPath,
    onChanged: () => { folderState.reload(); onMoved(); },
  });

  const panel: ReactNode = (
    <FolderPanel
      folders={folderState.folders} selectedPath={ownPath} onSelect={setFolderPath}
      includeSub={!exactFolder} onIncludeSubChange={(on) => setExactFolder(!on)}
      organization={organization && {
        ...organization, selectedPath: branchPath, onSelect: (path) => { setBranchPath(path); if (ownPath !== "") setOwnPath(""); },
      }}
    />
  );

  const bar: ReactNode = selected.size > 0 && (
    <div className="row" style={{ alignItems: "center" }}>
      <strong>{selected.size} selected</strong>
      <button type="button" className="btn" onClick={() => { setMoveError(null); setMoving(true); }}>Move to folder</button>
      <button type="button" className="btn" onClick={() => setSelected(new Set())}>Clear selection</button>
    </div>
  );

  const moveDialog: ReactNode = moving && (
    <MoveToFolderDialog
      count={selected.size} noun={noun} folders={folderState.folders} error={moveError} onCancel={() => setMoving(false)}
      onMove={async (folderId) => {
        try {
          const result = await folderState.calls?.moveRecords([...selected], folderId);
          if (!result) return;
          setMoving(false);
          setSelected(new Set());
          showToast(`${result.moved} ${result.moved === 1 ? noun.replace(/s$/, "") : noun} moved.`);
          folderState.reload();
          onMoved();
        } catch (err) {
          setMoveError(toErrorMessage(err, `Could not move the ${noun}.`));
        }
      }}
    />
  );

  const dialog: ReactNode = <>{moveDialog}{actions.dialogs}</>;

  return { matches, addParams, panel, menuItems: actions.menuItems, selected, setSelected, bar, dialog, folderPath, exactFolder, inBranch, folders: folderState.folders, chosenFolderId };
}
