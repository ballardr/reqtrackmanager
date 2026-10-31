/**
 * Module: components/ReportFolderField
 *
 * The folder field of a layout or pack form: a button styled as a field that only says where the report is filed now
 * (the folder path, or "No folder") and opens a `Popover` holding the `ReportFolderChooser` to move it. The form's
 * Save writes the choice, so cancelling the form discards a move.
 *
 * Responsibilities: show the current folder as the field's value; open the chooser; close it when a folder is picked;
 * stay open while a folder change is in flight or its delete confirmation is up (a click in that dialog is outside the
 * popover, which would otherwise close it and unmount the chooser behind the dialog).
 *
 * Dependencies: `ReportFolderChooser`, `Popover`, `FieldShell`.
 */
import { ChevronDown } from "lucide-react";
import { useCallback, useId, useRef, useState } from "react";

import type { ReportFolderApi } from "../api/reportFolders";
import { useStrings } from "../context/TerminologyContext";
import { tidyFolder } from "../utils/reportFolders";
import { FieldShell } from "./FieldHelp";
import { Popover } from "./Popover";
import { ReportFolderChooser } from "./ReportFolderChooser";

/**
 * @param value The folder path the report is filed under (`""` = none).
 * @param onChange Called with the path when a folder is chosen, and when a rename or delete moves the chosen folder.
 * @param api The folder calls, bound to the organisation or project the report belongs to.
 * @param onChanged Called after a folder is added, renamed or deleted, so the page behind can reload.
 * @param onBusyChange Told while a folder change is in flight, so the form can keep Save disabled.
 */
export function ReportFolderField({
  value, onChange, api, onChanged, onBusyChange,
}: {
  value: string;
  onChange: (path: string) => void;
  api: ReportFolderApi;
  onChanged?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportFolders;
  const controlId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const holdOpen = useRef({ busy: false, confirming: false });
  const chosen = tidyFolder(value);

  const busyChange = useCallback((busy: boolean) => {
    holdOpen.current.busy = busy;
    onBusyChange?.(busy);
  }, [onBusyChange]);
  const confirmChange = useCallback((confirming: boolean) => {
    holdOpen.current.confirming = confirming;
  }, []);
  const close = useCallback(() => {
    if (!holdOpen.current.busy && !holdOpen.current.confirming) setOpen(false);
  }, []);

  return (
    <FieldShell label={text.folderLabel} controlId={controlId} help={strings.help.reportFolder}>
      <button
        ref={triggerRef} id={controlId} type="button" className="btn" aria-haspopup="dialog" aria-expanded={open}
        aria-label={text.fieldName(chosen === "" ? text.noneShort : chosen)}
        style={{ justifyContent: "space-between", textAlign: "left", width: "100%" }}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={chosen === "" ? "text-muted" : undefined}>{chosen === "" ? text.noneShort : chosen}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={text.moveTitle} onClose={close} fit>
          <ReportFolderChooser
            value={value} onChange={onChange} api={api} label={text.moveLabel} onChanged={onChanged}
            onBusyChange={busyChange} onConfirmChange={confirmChange} onPick={() => setOpen(false)}
          />
        </Popover>
      )}
    </FieldShell>
  );
}
