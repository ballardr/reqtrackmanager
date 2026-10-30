/**
 * Module: hooks/useFileDetails
 *
 * Reads a picture file's details (`GET /files/{id}/details`) when its id is first wanted and remembers them, for
 * `components/FileDetailsPanel` and the image picker.
 */
import { useEffect, useState } from "react";

import { fetchFileDetails, type FileDetails } from "../api/fileDetails";

/** What `useFileDetails` knows about a file: its details, that they could not be read, or nothing yet (being read). */
export type FileDetailsState = FileDetails | "failed" | undefined;

/**
 * @param fileId The file to read, or `null` for none.
 * @param load Reads the details (the live call by default; stories pass their own).
 * @returns The state for `fileId`; `undefined` while it is being read.
 */
export function useFileDetails(fileId: string | null, load: (id: string) => Promise<FileDetails> = fetchFileDetails): FileDetailsState {
  const [known, setKnown] = useState<Record<string, FileDetails | "failed">>({});
  const wanted = fileId !== null && known[fileId] === undefined;
  useEffect(() => {
    if (!wanted || fileId === null) return;
    let cancelled = false;
    load(fileId).then(
      (found) => { if (!cancelled) setKnown((current) => ({ ...current, [fileId]: found })); },
      () => { if (!cancelled) setKnown((current) => ({ ...current, [fileId]: "failed" })); },
    );
    return () => {
      cancelled = true;
    };
  }, [wanted, fileId, load]);
  return fileId === null ? undefined : known[fileId];
}
