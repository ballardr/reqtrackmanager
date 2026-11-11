/**
 * Module: hooks/useBackendVersion
 *
 * Reads the running backend's build identity (`GET /api/v1/system/version`) for the page footer. The read needs a
 * session, so a signed-out page gets `null`; a failed read also yields `null` because build metadata must never get
 * in the way of the page it sits on.
 */
import { useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { SystemVersion } from "../api/types";
import { AuthContext } from "../context/AuthContextValue";

/** The backend version, or `null` while loading, when signed out or when the read fails. */
export function useBackendVersion(): SystemVersion | null {
  // Read through the context directly: a page that renders outside the provider (a story) is simply signed out.
  const signedIn = (useContext(AuthContext)?.user ?? null) !== null;
  const [version, setVersion] = useState<SystemVersion | null>(null);
  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    api.get<SystemVersion>("/api/v1/system/version").then(
      (loaded) => { if (!cancelled) setVersion(loaded); },
      () => undefined,
    );
    return () => { cancelled = true; };
  }, [signedIn]);
  return signedIn ? version : null;
}
