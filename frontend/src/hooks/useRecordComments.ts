/**
 * Module: hooks/useRecordComments
 *
 * Loads one record's generic comments (`api/recordComments`) and offers each change as a function that stores it and
 * replaces the thread with the answer.
 *
 * Comments are saved at once and are not live: the thread is read again when the window regains focus (so a reviewer's
 * new comment appears without a reload) and after each change the person makes. A failed change leaves the thread as
 * it was and reports its message in `error`.
 *
 * @param projectId The project the record is opened from.
 * @param artefactType The record's registered type.
 * @param recordId The record; nothing is loaded while it is empty.
 * @param client The API to use; defaults to the live one (injected by stories).
 */
import { useCallback, useEffect, useState } from "react";

import { recordCommentsApi, type NewComment, type PinChange, type PlaceInput, type RecordCommentsApi, type RecordThread } from "../api/recordComments";
import { useLoadOnChange } from "./useLoadOnChange";

/** The actions on a record's comments; each resolves to true when the change was stored. */
export interface RecordCommentsState {
  thread: RecordThread | null;
  error: string | null;
  loading: boolean;
  add: (comment: NewComment) => Promise<boolean>;
  edit: (commentId: string, body: string) => Promise<boolean>;
  remove: (commentId: string) => Promise<boolean>;
  pin: (commentId: string, place: PlaceInput) => Promise<boolean>;
  updatePin: (pinId: string, change: PinChange) => Promise<boolean>;
  removePin: (pinId: string) => Promise<boolean>;
  reload: () => Promise<void>;
}

export function useRecordComments(
  projectId: string, artefactType: string, recordId: string, client: RecordCommentsApi = recordCommentsApi,
): RecordCommentsState {
  const [thread, setThread] = useState<RecordThread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!projectId || !recordId) return;
    try {
      setThread(await client.get(projectId, artefactType, recordId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The comments could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [client, projectId, artefactType, recordId]);

  useLoadOnChange(reload, [projectId, artefactType, recordId]);

  useEffect(() => {
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  /** Runs one change, stores the thread it returns and reports a failure. */
  const run = useCallback(
    async (change: () => Promise<RecordThread>): Promise<boolean> => {
      try {
        setThread(await change());
        setError(null);
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "The change could not be saved.");
        return false;
      }
    },
    [],
  );

  return {
    thread, error, loading, reload,
    add: (comment) => run(() => client.add(projectId, artefactType, recordId, comment)),
    edit: (commentId, body) => run(() => client.edit(projectId, artefactType, recordId, commentId, body)),
    remove: (commentId) => run(() => client.remove(projectId, artefactType, recordId, commentId)),
    pin: (commentId, place) => run(() => client.pin(projectId, artefactType, recordId, commentId, place)),
    updatePin: (pinId, change) => run(() => client.updatePin(projectId, artefactType, recordId, pinId, change)),
    removePin: (pinId) => run(() => client.removePin(projectId, artefactType, recordId, pinId)),
  };
}
