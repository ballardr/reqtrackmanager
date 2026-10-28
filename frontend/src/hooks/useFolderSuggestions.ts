/**
 * Module: hooks/useFolderSuggestions
 *
 * The folders already used by a list of layouts, packs or placements, for a form's folder field to suggest
 * (`ReportFolderField`). A failed load is no suggestions: the field still accepts any path.
 */
import { useEffect, useState } from "react";

import { distinctFolders } from "../utils/reportFolders";

/**
 * Loads the folders already used by what `load` lists, for a form's suggestions; a failed load is no suggestions.
 *
 * @param load Lists the rows (layouts or packs) whose `folder` to suggest.
 * @returns Distinct folder paths, with the levels above each.
 */
export function useFolderSuggestions(load: () => Promise<{ folder: string }[]>): string[] {
  const [folders, setFolders] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((rows) => !cancelled && setFolders(distinctFolders(rows.map((row) => row.folder))))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // The list call is bound to a scope once; reloading it for every render would only repeat the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return folders;
}
