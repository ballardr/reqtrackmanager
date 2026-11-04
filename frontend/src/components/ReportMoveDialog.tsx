/**
 * Module: components/ReportMoveDialog
 *
 * The dialog that moves one report to a folder in the Report setup list: a `ReportFolderChooser` (the same control a
 * layout's or pack's own folder field uses) with Move and Cancel.
 *
 * Responsibilities: hold the chosen folder while the chooser adds, renames or deletes folders, keep Move disabled while
 * either a save or a folder change is in flight, and hand the tidied path to `onSave`, which decides whether the move
 * edits the report itself (an owned layout or pack) or sets a placement (a shared or module report).
 */
import { useState } from "react";

import type { ReportFolderApi } from "../api/reportFolders";
import { useStrings } from "../context/TerminologyContext";
import { tidyFolder } from "../utils/reportFolders";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { ReportFolderChooser } from "./ReportFolderChooser";

/**
 * @param title The report's title (names the dialog).
 * @param folder Where it files now.
 * @param folders Further folder paths to offer (every folder a listed report files under).
 * @param folderApi The folder calls for the scope.
 * @param noneLabel The first row's words: what an empty folder means for this report (a placement: the top level; an owned
 *   report: its default folder).
 * @param onChanged Called after a folder is added, renamed or deleted, so the list behind can reload.
 * @param onClose Called by Cancel.
 * @param onSave Called with the tidied folder path; the dialog stays open and busy until it settles.
 */
export function ReportMoveDialog({
  title, folder: current, folders, folderApi, noneLabel, onChanged, onClose, onSave,
}: {
  title: string; folder: string; folders: string[]; folderApi: ReportFolderApi; noneLabel?: string; onChanged: () => void; onClose: () => void;
  onSave: (folder: string) => Promise<void>;
}) {
  const text = useStrings().reportPlacements;
  const [folder, setFolder] = useState(current);
  const [busy, setBusy] = useState(false);
  const [folderBusy, setFolderBusy] = useState(false);
  return (
    <Modal title={text.moveTitle(title)} onClose={onClose}>
      <div className="stack">
        <ReportFolderChooser
          value={folder} onChange={setFolder} api={folderApi} label={text.moveField} helpKey="reportPlacementFolder"
          noneLabel={noneLabel ?? text.topLevel} extraPaths={folders} onChanged={onChanged} onBusyChange={setFolderBusy}
        />
        <FormActions
          onCancel={onClose}
          onSave={() => {
            setBusy(true);
            void onSave(tidyFolder(folder)).finally(() => setBusy(false));
          }}
          saveLabel={text.moveSave}
          saveDisabled={busy || folderBusy}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
