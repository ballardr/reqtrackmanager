/**
 * Module: context/PolicyAcceptanceContext
 *
 * Holds the policies the signed-in person must accept (`GET /api/v1/policies/mine/pending`), so the notice above
 * every page, the sign-in dialog and the Policies page agree and update together when one is accepted.
 *
 * Responsibilities: read the list when the person signs in and when the window regains focus (an administrator may
 * have published a requirement meanwhile), and expose `reload`. A failed read leaves the list as it was: a notice must
 * never get in the way of the page it sits on, and the server enforces the requirement either way.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { PendingPolicy } from "../api/types";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useAuth } from "./AuthContext";
import { PolicyAcceptanceContext } from "./PolicyAcceptanceValue";

/**
 * @param children The signed-in application.
 */
export function PolicyAcceptanceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const [pending, setPending] = useState<PendingPolicy[]>([]);

  const reload = useCallback(async () => {
    if (!userId) {
      setPending([]);
      return;
    }
    try {
      const loaded = await api.get<PendingPolicy[]>("/api/v1/policies/mine/pending");
      setPending(Array.isArray(loaded) ? loaded : []);
    } catch {
      /* keep the last list */
    }
  }, [userId]);

  useLoadOnChange(reload, [userId]);
  useEffect(() => {
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);

  return <PolicyAcceptanceContext.Provider value={{ pending, reload }}>{children}</PolicyAcceptanceContext.Provider>;
}
