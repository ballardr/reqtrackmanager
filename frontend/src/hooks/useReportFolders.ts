/**
 * Module: hooks/useReportFolders
 *
 * The folders a scope can file reports under, with the three changes a person can make to them, for the folder chooser
 * (`ReportFolderChooser`). A failed load is reported through `failed`: the chooser then still shows the folders it was
 * given and the value it holds, but cannot add, rename or delete.
 */
import { useCallback, useState } from "react";

import type { ReportFolder, ReportFolderApi, ReportFolderChange } from "../api/reportFolders";
import { useLoadOnChange } from "./useLoadOnChange";

export interface ReportFolders {
  folders: ReportFolder[];
  loaded: boolean;
  failed: boolean;
  /** Adds a folder; resolves once the list is refreshed. Rejects with the server's refusal. */
  add(path: string): Promise<void>;
  /** Renames the last level of a folder; resolves with what moved. */
  rename(path: string, name: string): Promise<ReportFolderChange>;
  /** Deletes a folder (its contents move up one level); resolves with what moved. */
  remove(path: string): Promise<ReportFolderChange>;
}

/**
 * @param api The calls, bound to an organisation or a project.
 * @returns The folders and the changes, each keeping the list in step with the server's answer.
 */
export function useReportFolders(api: ReportFolderApi): ReportFolders {
  const [folders, setFolders] = useState<ReportFolder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    try {
      setFolders(await api.list());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoaded(true);
    }
  }, [api]);
  useLoadOnChange(load, [api.scope.kind, api.scope.id]);
  return {
    folders, loaded, failed,
    add: async (path) => setFolders(await api.add(path)),
    rename: async (path, name) => {
      const change = await api.rename(path, name);
      setFolders(change.folders);
      return change;
    },
    remove: async (path) => {
      const change = await api.remove(path);
      setFolders(change.folders);
      return change;
    },
  };
}
