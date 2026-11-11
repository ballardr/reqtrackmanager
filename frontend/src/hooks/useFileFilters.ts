/**
 * Module: hooks/useFileFilters
 *
 * The filters the project and organisation Files pages share: file name, source, file type, uploader and an upload
 * window, each kept in the URL so a list comes back as it was left after opening a record.
 *
 * Responsibilities:
 * - Hold the five filters (`useUrlText` / `useUrlChoice`) and expose them for `FileFilterFields`.
 * - Build the request body both search endpoints take (`body`), with the upload window as the two UTC instants
 *   bounding the person's local days (`localDayWindow`), because only the browser knows the person's timezone.
 *
 * Design decisions:
 * - The file name is only ever sent in a POST body, never in a URL the server logs.
 */
import {
  PROJECT_FILE_SOURCES,
  type ProjectFileKind,
  type ProjectFileSource,
} from "../api/types";
import { localDayWindow } from "../utils/localDate";
import { useUrlChoice, useUrlText } from "./useUrlFilter";

/** The file types the page filters by, in the order the filter offers them. */
export const FILE_KINDS: readonly ProjectFileKind[] = ["image", "document", "other"];

/** The Files filters and the request body they produce. */
export interface FileFilterState {
  search: string;
  setSearch: (value: string) => void;
  source: ProjectFileSource | "";
  setSource: (value: ProjectFileSource | "") => void;
  kind: ProjectFileKind | "";
  setKind: (value: ProjectFileKind | "") => void;
  uploader: string;
  setUploader: (value: string) => void;
  from: string;
  setFrom: (value: string) => void;
  to: string;
  setTo: (value: string) => void;
  /** Whether any filter is set (picks the empty-list wording). */
  filtered: boolean;
  /** The values that, when changed, mean the list must be read again. */
  key: string[];
  /** The body of `POST …/files/search` for these filters. */
  body: () => Record<string, unknown>;
}

/**
 * Reads and writes the shared Files filters in the URL.
 *
 * @returns The filter values, their setters and the search request body.
 */
export function useFileFilters(): FileFilterState {
  const [search, setSearch] = useUrlText("q");
  const [source, setSource] = useUrlChoice<ProjectFileSource>("source", PROJECT_FILE_SOURCES);
  const [kind, setKind] = useUrlChoice<ProjectFileKind>("type", FILE_KINDS);
  const [uploader, setUploader] = useUrlText("by");
  const [from, setFrom] = useUrlText("from");
  const [to, setTo] = useUrlText("to");
  return {
    search, setSearch, source, setSource, kind, setKind, uploader, setUploader, from, setFrom, to, setTo,
    filtered: Boolean(search || source || kind || uploader || from || to),
    key: [search, source, kind, uploader, from, to],
    body: () => {
      const range = localDayWindow(from, to);
      return {
        search,
        sources: source ? [source] : [],
        kind: kind || null,
        uploaded_by: uploader || null,
        uploaded_from: range.from ?? null,
        uploaded_before: range.before ?? null,
      };
    },
  };
}
