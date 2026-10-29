/**
 * Module: hooks/useOpenFolders
 *
 * The folders a person left open in one folder list, kept in their `ui_preferences` (an object of folder ids by list),
 * so the report chooser and the report setup list each reopen as they were left.
 */
import { useMemo } from "react";

import { useUiPreference } from "./useUiPreference";

const OPEN_FOLDERS_KEY = "report_picker_folders";
const MAX_OPEN_FOLDERS = 100;

/**
 * @param listId Names the list, so each remembers its own folders (the chooser's `pickerId`, the setup list's scope).
 * @returns The open folder ids and a setter for one folder's state. A value that is not a list of ids reads as none.
 */
export function useOpenFolders(listId: string): [Set<string>, (id: string, open: boolean) => void] {
  const [saved, setSaved] = useUiPreference<Record<string, string[]>>(OPEN_FOLDERS_KEY, {});
  const stored = saved[listId];
  const open = useMemo(() => new Set(Array.isArray(stored) ? stored.filter((id) => typeof id === "string") : []), [stored]);
  function setOpen(id: string, isOpen: boolean) {
    const next = new Set(open);
    if (isOpen) next.add(id);
    else next.delete(id);
    setSaved({ ...saved, [listId]: [...next].slice(-MAX_OPEN_FOLDERS) });
  }
  return [open, setOpen];
}
