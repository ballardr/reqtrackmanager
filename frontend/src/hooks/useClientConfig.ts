/**
 * Module: useClientConfig
 *
 * Fetches the deployment's frontend-facing settings once per mount
 * (`GET /api/v1/system/client-config`: the Help link's `HELP_ENABLED` /
 * `HELP_URL`). Shared by the header (`Layout`) and the `/help` redirect page
 * so neither re-implements the fetch.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ClientConfig } from "../api/types";

/**
 * Loads the client config for the signed-in user.
 *
 * @param enabled - Skip the request (return `null`) until true, e.g. while signed out.
 * @returns The config, or `null` while loading or if the request failed (callers hide
 *   config-dependent UI rather than guess a default).
 */
export function useClientConfig(enabled = true): ClientConfig | null {
  const [config, setConfig] = useState<ClientConfig | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .get<ClientConfig>("/api/v1/system/client-config")
      .then((c) => {
        if (!cancelled) setConfig(c);
      })
      .catch(() => {
        if (!cancelled) setConfig(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return config;
}
