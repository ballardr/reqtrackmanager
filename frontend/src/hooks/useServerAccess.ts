/**
 * Module: hooks/useServerAccess
 *
 * The signed-in person's server-tier access (`GET /api/v1/system/access`), so the navigation and the server pages
 * show a section only to someone who may use it. The answer is the server's own, from the same role check the
 * protected routes apply, never a client-side guess from `is_server_admin`.
 *
 * Design decisions: unknown counts as no access (a section appears once known rather than appearing and
 * disappearing); a failed read leaves no access, since the routes themselves refuse regardless.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ServerAccess } from "../api/types";

/**
 * @param enabled False while nobody is signed in, so no request is made.
 * @returns The caller's server access, or `null` while loading or when the read failed.
 */
export function useServerAccess(enabled = true): ServerAccess | null {
  const [access, setAccess] = useState<ServerAccess | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .get<ServerAccess>("/api/v1/system/access")
      .then((a) => {
        if (!cancelled) setAccess(a);
      })
      .catch(() => {
        if (!cancelled) setAccess(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return enabled ? access : null;
}
