/**
 * Module: hooks/usePlatformBranding
 *
 * Reads the platform-wide branding (`GET /api/v1/system/branding`, public) so an organisation's company settings
 * can show the platform value as the placeholder of an empty field.
 *
 * Responsibilities: fetch once per mount; return `null` until it has loaded or if it fails (the placeholder is
 * then simply omitted, nothing else depends on it).
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ServerSettings } from "../api/types";

/** The platform branding, or `null` while loading or when it could not be read. */
export function usePlatformBranding(): ServerSettings | null {
  const [settings, setSettings] = useState<ServerSettings | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.get<ServerSettings>("/api/v1/system/branding").then(
      (s) => {
        if (!cancelled) setSettings(s);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return settings;
}
