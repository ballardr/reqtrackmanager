/**
 * Module: hooks/useWatchers
 *
 * The users and groups watching one requirement or change request, loaded from `{recordPath}/watchers`,
 * with add and remove that post to the same path and toast the outcome. The list holds both the people a
 * project manager added and those who subscribed themselves (the record header menu's Subscribe action).
 * It lives in a hook, not in the panel, because the record page needs the count for its "Watching" tab label
 * and must know whether to show the tab at all.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Principal, PrincipalRef } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";

const strings = t();

export interface Watchers {
  /** The watchers, or null until the first load finishes. */
  watchers: Principal[] | null;
  /** Adds a user or group; a null (the picker cleared) is ignored. */
  add: (principal: PrincipalRef | null) => Promise<void>;
  /** Stops a user or group watching. */
  remove: (principal: Principal) => Promise<void>;
}

/**
 * @param recordPath API path of the record (`/api/v1/projects/{id}/requirements/{id}`); `/watchers` is appended.
 *   Undefined (the record's project is not known yet) loads nothing.
 * @param refreshKey A value that, when it changes, loads the list again (the record's own subscribed flag, so
 *   the Subscribe action in the record menu shows here).
 * @returns The watchers and the two actions.
 */
export function useWatchers(recordPath: string | undefined, refreshKey?: unknown): Watchers {
  const { showToast } = useToast();
  const [watchers, setWatchers] = useState<Principal[] | null>(null);

  useEffect(() => {
    if (!recordPath) return;
    let active = true;
    api.get<Principal[]>(`${recordPath}/watchers`).then((list) => active && setWatchers(list)).catch(() => active && setWatchers([]));
    return () => {
      active = false;
    };
  }, [recordPath, refreshKey]);

  const add = useCallback(async (principal: PrincipalRef | null) => {
    if (!principal || !recordPath) return;
    try {
      setWatchers(await api.post<Principal[]>(`${recordPath}/watchers`, { principal }));
      showToast(strings.watchers.added);
    } catch (err) {
      showToast(toErrorMessage(err, strings.watchers.addFailed), "error");
    }
  }, [recordPath, showToast]);

  const remove = useCallback(async (principal: Principal) => {
    if (!recordPath) return;
    try {
      setWatchers(await api.delete<Principal[]>(`${recordPath}/watchers/${principal.type}/${principal.id}`));
      showToast(strings.watchers.removed);
    } catch (err) {
      showToast(toErrorMessage(err, strings.watchers.removeFailed), "error");
    }
  }, [recordPath, showToast]);

  return { watchers, add, remove };
}
